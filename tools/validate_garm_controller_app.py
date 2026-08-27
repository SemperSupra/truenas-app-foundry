#!/usr/bin/env python3
"""Public-safe qualification for the native TrueNAS GARM controller App candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = REPO_ROOT / "candidates" / "garm-controller-app" / "candidate.json"
SOURCE = REPO_ROOT / "candidates" / "garm-controller-app" / "ix-dev" / "community" / "garm"
EXPECTED_SERVICES = {"garm", "garm-config-seed"}


class ValidationError(RuntimeError):
    pass


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        input=input_text,
        capture_output=True,
        check=False,
    )
    if check and cp.returncode:
        detail = (cp.stderr or cp.stdout or "")[-5000:]
        raise ValidationError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{detail}")
    return cp


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load {path}: {exc}") from exc


def checkout_upstream(root: Path, manifest: dict[str, Any]) -> Path:
    materializer = manifest["source_materializer"]
    checkout = root / "truenas-apps"
    run(["git", "init", "--quiet", str(checkout)], cwd=root)
    run(["git", "-C", str(checkout), "remote", "add", "origin", materializer["repository"]], cwd=root)
    run(
        ["git", "-C", str(checkout), "fetch", "--quiet", "--depth", "1", "origin", materializer["commit"]],
        cwd=root,
    )
    run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=root)
    actual = run(["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if actual != materializer["commit"]:
        raise ValidationError(f"materializer checkout drift: expected {materializer['commit']}, got {actual}")
    return checkout


def install_candidate(checkout: Path, manifest: dict[str, Any]) -> Path:
    app_dir = checkout / "ix-dev" / "community" / "garm"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    shutil.copytree(SOURCE, app_dir)

    # Source apps use the exact library declared in app.yaml. For this external
    # candidate, vendor that library deterministically from the pinned upstream tree.
    lib_name = f"base_v{str(manifest['source_materializer']['lib_version']).replace('.', '_')}"
    lib_src = checkout / "ix-dev" / "community" / "ntfy" / "templates" / "library" / lib_name
    lib_dst = app_dir / "templates" / "library" / lib_name
    if not lib_src.is_dir():
        raise ValidationError(f"pinned TrueNAS library source missing: {lib_src}")
    shutil.copytree(lib_src, lib_dst)
    return app_dir


def render_candidate(checkout: Path, app_dir: Path) -> dict[str, Any]:
    run(
        [
            "python3",
            ".github/scripts/ci.py",
            "--app",
            "garm",
            "--train",
            "community",
            "--test-file",
            "basic-values.yaml",
            "--render-only=true",
        ],
        cwd=checkout,
    )
    rendered = app_dir / "templates" / "rendered" / "docker-compose.yaml"
    if not rendered.is_file():
        raise ValidationError("candidate produced no rendered Compose")
    normalized = run(
        ["docker", "compose", "-p", "foundry-garm", "-f", str(rendered), "config", "--format", "json"],
        cwd=checkout,
    )
    try:
        compose = json.loads(normalized.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError("Docker Compose normalization did not return JSON") from exc
    compose.pop("name", None)
    return compose


def mounts(service: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in service.get("volumes") or []:
        if isinstance(value, dict):
            result.append(
                {
                    "type": str(value.get("type") or ""),
                    "source": str(value.get("source") or ""),
                    "target": str(value.get("target") or ""),
                }
            )
    return result


def assert_security(name: str, service: dict[str, Any], *, root_expected: bool) -> None:
    if service.get("privileged"):
        raise ValidationError(f"{name}: privileged mode materialized")
    caps = {str(v).upper() for v in service.get("cap_drop") or []}
    if "ALL" not in caps:
        raise ValidationError(f"{name}: cap_drop ALL missing")
    opts = {str(v).lower().replace(":", "=") for v in service.get("security_opt") or []}
    if not any(v.startswith("no-new-privileges=true") for v in opts):
        raise ValidationError(f"{name}: no-new-privileges missing")
    user = str(service.get("user") or "")
    if root_expected and user not in {"0", "0:0", "root"}:
        raise ValidationError(f"{name}: expected explicitly-qualified root runtime, got {user!r}")


def assert_render(compose: dict[str, Any], manifest: dict[str, Any]) -> tuple[str, str]:
    services = compose.get("services") or {}
    if set(services) != EXPECTED_SERVICES:
        raise ValidationError(f"service inventory drift: expected {sorted(EXPECTED_SERVICES)}, got {sorted(services)}")
    image = manifest["appliance"]["reference"]
    if ":mvp" in json.dumps(compose):
        raise ValidationError("mutable :mvp reference leaked into deployment artifact")

    controller = services["garm"]
    seed = services["garm-config-seed"]
    for name, service in (("garm", controller), ("garm-config-seed", seed)):
        if service.get("image") != image:
            raise ValidationError(f"{name}: exact appliance digest mismatch: {service.get('image')!r}")
        assert_security(name, service, root_expected=True)
        targets = [m["target"] for m in mounts(service)]
        if targets != ["/etc/garm"]:
            raise ValidationError(f"{name}: unexpected persistent mount targets: {targets!r}")
        if any("docker.sock" in (m["source"] + m["target"]) for m in mounts(service)):
            raise ValidationError(f"{name}: container runtime socket materialized")

    if controller.get("restart") != "unless-stopped":
        raise ValidationError(f"garm: unexpected restart policy {controller.get('restart')!r}")
    if seed.get("restart") not in {"on-failure:1", "on-failure: 1"}:
        raise ValidationError(f"garm-config-seed: unexpected restart policy {seed.get('restart')!r}")
    if seed.get("network_mode") != "none":
        raise ValidationError("garm-config-seed: helper network is not disabled")

    depends = controller.get("depends_on") or {}
    dep = depends.get("garm-config-seed") or {}
    if dep.get("condition") != "service_completed_successfully":
        raise ValidationError("garm: controller does not wait for successful config seed")

    ports = controller.get("ports") or []
    if not ports or not any(int(p.get("target", 0)) == 8080 for p in ports if isinstance(p, dict)):
        raise ValidationError("garm: fixed internal port 8080 not materialized")

    hc = controller.get("healthcheck") or {}
    hc_text = json.dumps(hc)
    if "wget" not in hc_text or "http://127.0.0.1:8080/ui/" not in hc_text:
        raise ValidationError("garm: expected BusyBox wget /ui/ health probe not materialized")

    command = seed.get("command") or []
    command_text = " ".join(str(v) for v in command)
    for required in (
        "if [ -e /etc/garm/config.toml ]",
        "[ ! -s /etc/garm/config.toml ]",
        "exit 42",
        "cp /seed/config.toml /etc/garm/config.toml",
    ):
        if required not in command_text:
            raise ValidationError(f"garm-config-seed: missing fail-closed seed invariant {required!r}")

    configs = compose.get("configs") or {}
    initial = configs.get("garm-initial-config") or {}
    content = str(initial.get("content") or "")
    if "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in content or "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB" not in content:
        raise ValidationError("dummy bootstrap configuration did not materialize as expected")
    if "github" in content.lower() and "credential" in content.lower():
        raise ValidationError("GitHub credential material unexpectedly present in bootstrap config")

    return image, command_text


def seed_behavior(image: str, seed_command: str, root: Path) -> None:
    state = root / "state"
    state.mkdir()
    seed_a = root / "seed-a.toml"
    seed_b = root / "seed-b.toml"
    seed_a.write_text("marker = 'first'\n", encoding="utf-8")
    seed_b.write_text("marker = 'second'\n", encoding="utf-8")

    def invoke(seed_file: Path, expected: int = 0) -> subprocess.CompletedProcess[str]:
        cp = run(
            [
                "docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges=true", "--entrypoint", "/bin/sh",
                "-v", f"{state}:/etc/garm", "-v", f"{seed_file}:/seed/config.toml:ro",
                image, "-ec", seed_command,
            ],
            check=False,
        )
        if cp.returncode != expected:
            raise ValidationError(
                f"seed behavior expected exit {expected}, got {cp.returncode}: {(cp.stderr or cp.stdout)[-1000:]}"
            )
        return cp

    invoke(seed_a)
    config = state / "config.toml"
    if not config.is_file() or config.read_text(encoding="utf-8") != seed_a.read_text(encoding="utf-8"):
        raise ValidationError("seed helper did not create initial config")
    before = hashlib.sha256(config.read_bytes()).hexdigest()
    invoke(seed_b)
    after = hashlib.sha256(config.read_bytes()).hexdigest()
    if before != after:
        raise ValidationError("seed helper overwrote non-empty persistent config")
    config.write_bytes(b"")
    invoke(seed_b, expected=42)


def controller_smoke(image: str, root: Path) -> None:
    state = root / "controller-state"
    state.mkdir()
    config = state / "config.toml"
    config.write_text(
        """[default]\nenable_webhook_management = true\n\n[logging]\nenable_log_file = true\nlog_file = \"/etc/garm/garm.log\"\nlog_level = \"info\"\nlog_rotate_max_size = 100\nlog_rotate_backups = 3\nlog_rotate_compress = true\n\n[metrics]\ndisable_auth = false\n\n[jwt_auth]\nsecret = \"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\"\ntime_to_live = \"8760h\"\n\n[apiserver]\nbind = \"0.0.0.0\"\nport = 8080\nuse_tls = false\n\n[apiserver.webui]\nenable = true\n\n[database]\nbackend = \"sqlite3\"\npassphrase = \"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\"\n\n[database.sqlite3]\ndb_file = \"/etc/garm/garm.db\"\n""",
        encoding="utf-8",
    )
    name = f"foundry-garm-smoke-{os.getpid()}"
    try:
        run(
            [
                "docker", "run", "-d", "--name", name, "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges=true", "-v", f"{state}:/etc/garm", image,
            ]
        )
        deadline = time.time() + 45
        last = ""
        while time.time() < deadline:
            status = run(["docker", "inspect", "-f", "{{.State.Status}}", name], check=False).stdout.strip()
            if status != "running":
                last = run(["docker", "logs", "--tail", "80", name], check=False).stdout[-4000:]
                break
            probe = run(
                ["docker", "exec", name, "wget", "--quiet", "-O", "/dev/null", "http://127.0.0.1:8080/ui/"],
                check=False,
            )
            if probe.returncode == 0:
                return
            last = (probe.stderr or probe.stdout)[-1000:]
            time.sleep(2)
        logs = run(["docker", "logs", "--tail", "80", name], check=False)
        raise ValidationError(f"controller /ui/ smoke probe did not become ready: {last}\n{logs.stdout[-4000:]}")
    finally:
        run(["docker", "rm", "-f", name], check=False)


def validate(public_pull: bool) -> dict[str, Any]:
    for tool in ("git", "docker", "python3"):
        if not shutil.which(tool):
            raise ValidationError(f"required tool missing: {tool}")
    manifest = load_json(CANDIDATE)
    root = Path(tempfile.mkdtemp(prefix="foundry-garm-controller-"))
    try:
        checkout = checkout_upstream(root, manifest)
        app_dir = install_candidate(checkout, manifest)
        compose = render_candidate(checkout, app_dir)
        image, seed_command = assert_render(compose, manifest)
        seed_behavior(image, seed_command, root)
        controller_smoke(image, root)
        canonical = json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()
        return {
            "result": "PASS",
            "candidate": "garm-controller-app",
            "appliance": image,
            "materializer": manifest["source_materializer"],
            "compose_sha256": hashlib.sha256(canonical).hexdigest(),
            "services": sorted((compose.get("services") or {}).keys()),
            "security": {
                "cap_drop_all": True,
                "no_new_privileges": True,
                "privileged": False,
                "host_paths_allowed": False,
                "runtime_socket_allowed": False,
                "qualified_root_runtime": True,
            },
            "seed_behavior": "PASS:create-once/preserve/fail-empty",
            "controller_smoke": "PASS:wget http://127.0.0.1:8080/ui/",
            "ghcr_anonymous_pull": public_pull,
            "non_claims": [
                "no TrueNAS runtime realization",
                "no provider HIL correctness",
                "no site credential use",
                "GHCR public visibility is only proven when ghcr_anonymous_pull=true",
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
    except (ValidationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
