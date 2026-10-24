#!/usr/bin/env python3
"""Public-safe official TrueNAS render qualification for the WOW Go App."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = REPO_ROOT / "candidates" / "wow-sidecar-go-app" / "candidate.json"
SOURCE = REPO_ROOT / "candidates" / "wow-sidecar-go-app" / "ix-dev" / "community" / "wow-sidecar"
EXPECTED_SERVICES = {"wow-sidecar", "permissions"}


class ValidationError(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if check and cp.returncode:
        detail = (cp.stderr or cp.stdout or "")[-5000:]
        raise ValidationError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{detail}")
    return cp


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValidationError(f"{path} did not contain an object")
    return value


def checkout_upstream(root: Path, candidate: dict[str, Any]) -> Path:
    source = candidate["truenas_source"]
    checkout = root / "truenas-apps"
    run(["git", "init", "--quiet", str(checkout)], cwd=root)
    run(["git", "-C", str(checkout), "remote", "add", "origin", source["repository"]], cwd=root)
    run(["git", "-C", str(checkout), "fetch", "--quiet", "--depth", "1", "origin", source["commit"]], cwd=root)
    run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=root)
    actual = run(["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if actual != source["commit"]:
        raise ValidationError(f"TrueNAS source drift: expected {source['commit']}, got {actual}")
    return checkout


def install_candidate(checkout: Path, candidate: dict[str, Any]) -> Path:
    app_dir = checkout / "ix-dev" / "community" / "wow-sidecar"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    shutil.copytree(SOURCE, app_dir)

    # The upstream materializer overlays ix_values.yaml after the named test
    # values file. Keep shipped defaults secret-free, but inject a public
    # synthetic key into this disposable checkout so the file-backed config
    # path is actually rendered and validated.
    ix_values_path = app_dir / "ix_values.yaml"
    ix_values = yaml.safe_load(ix_values_path.read_text(encoding="utf-8"))
    ix_values["wow"]["github_app_private_key"] = (
        "-----BEGIN PRIVATE KEY-----\n"
        "PUBLIC-QUALIFICATION-FIXTURE\n"
        "-----END PRIVATE KEY-----\n"
    )
    ix_values_path.write_text(
        yaml.safe_dump(ix_values, sort_keys=False),
        encoding="utf-8",
    )

    lib_name = f"base_v{str(candidate['truenas_source']['lib_version']).replace('.', '_')}"
    lib_src = checkout / "ix-dev" / "community" / "ntfy" / "templates" / "library" / lib_name
    lib_dst = app_dir / "templates" / "library" / lib_name
    if not lib_src.is_dir():
        raise ValidationError(f"pinned TrueNAS library source missing: {lib_src}")
    shutil.copytree(lib_src, lib_dst)
    return app_dir


def render_candidate(checkout: Path, app_dir: Path) -> dict[str, Any]:
    run([
        "python3", ".github/scripts/ci.py", "--app", "wow-sidecar", "--train", "community",
        "--test-file", "basic-values.yaml", "--render-only=true",
    ], cwd=checkout)
    rendered = app_dir / "templates" / "rendered" / "docker-compose.yaml"
    if not rendered.is_file():
        raise ValidationError("candidate produced no rendered Compose")
    normalized = run([
        "docker", "compose", "-p", "foundry-wow-sidecar-go", "-f", str(rendered),
        "config", "--format", "json",
    ], cwd=checkout)
    compose = json.loads(normalized.stdout)
    compose.pop("name", None)
    return compose


def mount_by_target(service: dict[str, Any], target: str) -> dict[str, Any]:
    matches = [
        m for m in service.get("volumes") or []
        if isinstance(m, dict) and str(m.get("target") or "") == target
    ]
    if len(matches) != 1:
        raise ValidationError(f"expected one mount at {target}, got {len(matches)}")
    return matches[0]


def assert_no_forbidden_surface(name: str, service: dict[str, Any]) -> None:
    if service.get("privileged"):
        raise ValidationError(f"{name}: privileged mode materialized")
    if service.get("network_mode") == "host":
        raise ValidationError(f"{name}: host network materialized")
    serialized = json.dumps(service, sort_keys=True).lower()
    for forbidden in ("docker.sock", "/var/run/docker", "/run/podman/podman.sock"):
        if forbidden in serialized:
            raise ValidationError(f"{name}: runtime socket surfaced: {forbidden}")


def assert_render(compose: dict[str, Any], candidate: dict[str, Any]) -> str:
    services = compose.get("services") or {}
    if set(services) != EXPECTED_SERVICES:
        raise ValidationError(f"service inventory drift: {sorted(services)}")

    worker = services["wow-sidecar"]
    perms = services["permissions"]
    image = candidate["container"]["registry_reference"]
    helper = candidate["permissions_helper"]["reference"]

    if worker.get("image") != image:
        raise ValidationError("worker image does not equal admitted manifest")
    if perms.get("image") != helper:
        raise ValidationError("permissions helper image drift")

    assert_no_forbidden_surface("wow-sidecar", worker)
    assert_no_forbidden_surface("permissions", perms)

    if str(worker.get("user") or "") != "10001:10001":
        raise ValidationError("worker runtime identity drift")
    if worker.get("read_only") is not True:
        raise ValidationError("worker root filesystem is not read-only")
    caps = {str(v).upper() for v in worker.get("cap_drop") or []}
    if "ALL" not in caps:
        raise ValidationError("worker cap_drop ALL missing")
    opts = {str(v).lower().replace(":", "=") for v in worker.get("security_opt") or []}
    if not any(v.startswith("no-new-privileges=true") for v in opts):
        raise ValidationError("worker no-new-privileges missing")

    state = mount_by_target(worker, "/var/lib/wow-sidecar")
    if state.get("read_only") is True:
        raise ValidationError("state mount unexpectedly read-only")
    tmpfs = [m for m in worker.get("tmpfs") or []]
    if not tmpfs and not any(
        isinstance(m, dict) and str(m.get("target") or "") == "/tmp"
        for m in worker.get("volumes") or []
    ):
        raise ValidationError("worker /tmp tmpfs missing")

    env = worker.get("environment") or {}
    if env.get("GITHUB_APP_PRIVATE_KEY_FILE") != "/run/secrets/github-app.pem":
        raise ValidationError("GitHub App key file projection drift")
    if "WOW_PEER_RENDEZVOUS_ENABLED" in env or "WOW_PEER_CREDENTIALS_FILE" in env:
        raise ValidationError("peer mutation unexpectedly enabled by default")
    if "WOW_PUBLIC_ENDPOINT" in env:
        raise ValidationError("public endpoint advertised by default")
    for value in env.values():
        text = str(value)
        if "PRIVATE KEY" in text or "BEGIN " in text:
            raise ValidationError("secret content leaked into environment")

    configs = compose.get("configs") or {}
    key = configs.get("wow-github-app-private-key") or {}
    if str(key.get("target") or "") != "/run/secrets/github-app.pem":
        raise ValidationError("GitHub App key config target drift")
    if "wow-peer-credentials" in configs:
        raise ValidationError("peer credential config unexpectedly materialized")

    ports = worker.get("ports") or []
    if len(ports) != 1:
        raise ValidationError(f"expected exactly one published port, got {len(ports)}")
    port = ports[0]
    if isinstance(port, dict):
        if int(port.get("published") or 0) != 18080 or int(port.get("target") or 0) != 8080:
            raise ValidationError(f"published port drift: {port}")

    if perms.get("network_mode") != "none":
        raise ValidationError("permissions helper network must be disabled")
    if perms.get("privileged"):
        raise ValidationError("permissions helper is privileged")
    targets = sorted(
        str(m.get("target") or "")
        for m in perms.get("volumes") or []
        if isinstance(m, dict)
    )
    if targets != ["/mnt/permission/state"]:
        raise ValidationError(f"permissions helper mount scope drift: {targets}")

    return image


def validate(public_pull: bool) -> dict[str, Any]:
    for tool in ("git", "docker", "python3"):
        if not shutil.which(tool):
            raise ValidationError(f"required tool missing: {tool}")

    candidate = load_json(CANDIDATE_PATH)
    root = Path(tempfile.mkdtemp(prefix="foundry-wow-sidecar-go-"))
    try:
        checkout = checkout_upstream(root, candidate)
        app_dir = install_candidate(checkout, candidate)
        compose = render_candidate(checkout, app_dir)
        image = assert_render(compose, candidate)

        inspect = json.loads(run(["docker", "image", "inspect", image]).stdout)[0]
        if inspect.get("Architecture") != "amd64":
            raise ValidationError(f"host image architecture drift: {inspect.get('Architecture')}")
        if inspect.get("Config", {}).get("User") != "10001:10001":
            raise ValidationError("published image user drift")
        labels = inspect.get("Config", {}).get("Labels") or {}
        source = candidate["wow_source"]["public_candidate_revision"]
        if labels.get("org.opencontainers.image.revision") != source:
            raise ValidationError("published image source label drift")

        shell = run(["docker", "run", "--rm", "--entrypoint", "/bin/sh", image, "-c", "true"], check=False)
        if shell.returncode == 0:
            raise ValidationError("scratch image unexpectedly contains /bin/sh")

        canonical = json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()
        return {
            "result": "PASS",
            "candidate": "wow-sidecar-go-truenas-app",
            "wow_image": image,
            "permissions_helper": candidate["permissions_helper"]["reference"],
            "materializer": candidate["truenas_source"],
            "compose_sha256": hashlib.sha256(canonical).hexdigest(),
            "services": sorted((compose.get("services") or {}).keys()),
            "ghcr_anonymous_pull": public_pull,
            "security": {
                "wow_runtime_uid_gid": "10001:10001",
                "wow_cap_drop_all": True,
                "wow_no_new_privileges": True,
                "wow_rootfs_read_only": True,
                "github_app_secret_file_backed": True,
                "peer_mutation_default_absent": True,
                "host_network": False,
                "privileged": False,
                "runtime_socket_allowed": False,
                "permissions_helper_scope": "ixVolume state ownership only",
            },
            "non_claims": [
                "no TrueNAS runtime realization",
                "no production credential use",
                "no live cutover",
                "no state migration",
            ],
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--public-pull", choices=("true", "false"), default="false")
    args = parser.parse_args()
    try:
        evidence = validate(args.public_pull == "true")
        payload = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        if args.evidence:
            args.evidence.write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
