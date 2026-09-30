#!/usr/bin/env python3
"""Public-safe render/runtime qualification for the WOW Sidecar TrueNAS App candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = REPO_ROOT / "candidates" / "wow-sidecar-app" / "candidate.json"
SOURCE = REPO_ROOT / "candidates" / "wow-sidecar-app" / "ix-dev" / "community" / "wow-sidecar"
EXPECTED_SERVICES = {"wow-sidecar", "wow-sidecar-config-seed", "permissions"}
FIXTURE_KEY_MARKER = "PUBLIC-QUALIFICATION-FIXTURE"
FIXTURE_PROFILE_REPOSITORY = "ExampleOrg/operator"

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
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path} did not contain a JSON object")
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
        raise ValidationError(f"TrueNAS materializer drift: expected {source['commit']}, got {actual}")
    return checkout

def install_candidate(checkout: Path, candidate: dict[str, Any]) -> Path:
    app_dir = checkout / "ix-dev" / "community" / "wow-sidecar"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    shutil.copytree(SOURCE, app_dir)
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
        "docker", "compose", "-p", "foundry-wow-sidecar", "-f", str(rendered),
        "config", "--format", "json",
    ], cwd=checkout)
    try:
        compose = json.loads(normalized.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError("Docker Compose normalization did not return JSON") from exc
    compose.pop("name", None)
    return compose

def mounts(service: dict[str, Any]) -> list[dict[str, Any]]:
    return [value for value in (service.get("volumes") or []) if isinstance(value, dict)]

def mount_by_target(service: dict[str, Any], target: str) -> dict[str, Any]:
    matches = [m for m in mounts(service) if str(m.get("target") or "") == target]
    if len(matches) != 1:
        raise ValidationError(f"expected exactly one mount at {target}, got {len(matches)}")
    return matches[0]

def assert_common_wow_security(
    name: str,
    service: dict[str, Any],
    *,
    network_none: bool,
    rootfs_read_only: bool,
) -> None:
    if service.get("privileged"):
        raise ValidationError(f"{name}: privileged mode materialized")
    if str(service.get("user") or "") != "10001:10001":
        raise ValidationError(f"{name}: runtime identity drift: {service.get('user')!r}")
    caps = {str(v).upper() for v in service.get("cap_drop") or []}
    if "ALL" not in caps:
        raise ValidationError(f"{name}: cap_drop ALL missing")
    opts = {str(v).lower().replace(":", "=") for v in service.get("security_opt") or []}
    if not any(v.startswith("no-new-privileges=true") for v in opts):
        raise ValidationError(f"{name}: no-new-privileges missing")
    if rootfs_read_only and service.get("read_only") is not True:
        raise ValidationError(f"{name}: root filesystem is not read-only")
    if not rootfs_read_only and service.get("read_only") is not False:
        raise ValidationError(f"{name}: bounded writable rootfs exception is not explicit")
    if service.get("network_mode") == "host":
        raise ValidationError(f"{name}: host network materialized")
    if network_none and service.get("network_mode") != "none":
        raise ValidationError(f"{name}: helper network is not disabled")
    if not network_none and service.get("network_mode") == "none":
        raise ValidationError(f"{name}: worker unexpectedly has no network")
    if service.get("ports"):
        raise ValidationError(f"{name}: network ports unexpectedly published")
    serialized = json.dumps(service, sort_keys=True).lower()
    for forbidden in ("docker.sock", "/var/run/docker", "/run/udev"):
        if forbidden in serialized:
            raise ValidationError(f"{name}: forbidden host/runtime surface materialized: {forbidden}")

def extract_seed_script(seed: dict[str, Any]) -> str:
    command = seed.get("command")
    if not isinstance(command, list):
        raise ValidationError("seed: command is not a list")
    parts = [str(v) for v in command]
    if len(parts) == 2 and parts[0] == "-ec":
        # Compose escapes shell-dollar characters as a doubled pair. Direct
        # docker-run replay bypasses Compose, so restore the container-visible script.
        return parts[1].replace(chr(36) * 2, chr(36))
    raise ValidationError(f"seed: unexpected command shape: {parts!r}")

def assert_render(compose: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, str]:
    services = compose.get("services") or {}
    if set(services) != EXPECTED_SERVICES:
        raise ValidationError(f"service inventory drift: {sorted(services)}")

    image = candidate["container"]["registry_reference"]
    helper = candidate["permissions_helper"]["reference"]
    if helper is None:
        raise ValidationError("permissions helper is not digest pinned")

    worker = services["wow-sidecar"]
    seed = services["wow-sidecar-config-seed"]
    perms = services["permissions"]

    if worker.get("image") != image or seed.get("image") != image:
        raise ValidationError("WOW service image does not match immutable registry reference")
    if perms.get("image") != helper:
        raise ValidationError("permissions helper image does not match immutable reference")

    assert_common_wow_security(
        "wow-sidecar", worker, network_none=False, rootfs_read_only=True
    )
    assert_common_wow_security(
        "wow-sidecar-config-seed", seed, network_none=True, rootfs_read_only=False
    )

    groups = {str(v) for v in worker.get("group_add") or []}
    if groups != {"568"}:
        raise ValidationError(f"worker supplemental groups drift: {groups}")

    config = mount_by_target(worker, "/etc/wow-sidecar")
    state = mount_by_target(worker, "/var/lib/wow-sidecar")
    if config.get("read_only") is not True:
        raise ValidationError("worker config mount is not read-only")
    if state.get("read_only") is True:
        raise ValidationError("worker state mount unexpectedly read-only")

    tmpfs = [str(v) for v in worker.get("tmpfs") or []]
    if not any(v.startswith("/tmp:") for v in tmpfs):
        raise ValidationError("worker /tmp tmpfs missing")

    env = worker.get("environment") or {}
    if env.get("GITHUB_APP_ID") != "12345":
        raise ValidationError("worker GitHub App ID not materialized")
    if env.get("GITHUB_APP_PRIVATE_KEY_FILE") != "/etc/wow-sidecar/github-app.pem":
        raise ValidationError("worker private-key file path drift")

    command = [str(v) for v in worker.get("command") or []]
    expected = [
        "--control-repository", "ExampleOrg/control",
        "--profile", "/etc/wow-sidecar/profiles/operator.json",
        "--revision-file", "/usr/share/wow-sidecar/source-revision",
        "--serve", "--poll-seconds", "15",
    ]
    if command != expected:
        raise ValidationError(f"worker command drift: {command!r}")

    depends = worker.get("depends_on") or {}
    for dependency in ("wow-sidecar-config-seed", "permissions"):
        dep = depends.get(dependency) or {}
        if dep.get("condition") != "service_completed_successfully":
            raise ValidationError(f"worker does not gate on {dependency}")

    seed_config = mount_by_target(seed, "/etc/wow-sidecar")
    if seed_config.get("read_only") is True:
        raise ValidationError("seed config mount unexpectedly read-only")
    script = extract_seed_script(seed)
    for required in (
        ".initialized-v1", "github-app.pem", "profiles/operator.json",
        "partial or unexpected WOW configuration exists", "exit 42", "chmod 0400",
    ):
        if required not in script:
            raise ValidationError(f"seed invariant missing: {required!r}")

    configs = compose.get("configs") or {}
    key_content = str((configs.get("wow-github-app-private-key") or {}).get("content") or "")
    profile_content = str((configs.get("wow-operator-profile") or {}).get("content") or "")
    if FIXTURE_KEY_MARKER not in key_content:
        raise ValidationError("GitHub App private-key fixture did not materialize")
    if FIXTURE_PROFILE_REPOSITORY not in profile_content:
        raise ValidationError("operator-profile fixture did not materialize")

    if perms.get("network_mode") != "none":
        raise ValidationError("permissions helper network is not disabled")
    if perms.get("privileged"):
        raise ValidationError("permissions helper is privileged")
    if str(perms.get("user") or "") not in {"0", "0:0", "root"}:
        raise ValidationError("permissions helper is not bounded root helper")
    cap_add = {str(v).upper() for v in perms.get("cap_add") or []}
    if cap_add != {"CHOWN", "FOWNER", "DAC_OVERRIDE"}:
        raise ValidationError(f"permissions helper capability drift: {cap_add}")
    targets = sorted(str(m.get("target") or "") for m in mounts(perms))
    if targets != ["/mnt/permission/config", "/mnt/permission/state"]:
        raise ValidationError(f"permissions helper mount scope drift: {targets}")

    return image, script

def seed_behavior(image: str, script: str, root: Path) -> None:
    config = root / "config"
    config.mkdir()
    os.chown(config, 10001, 10001)
    os.chmod(config, 0o750)

    def make_seed(name: str, key: str, profile: str) -> Path:
        directory = root / name
        directory.mkdir()
        key_path = directory / "github-app.pem"
        profile_path = directory / "operator-profile.json"
        key_path.write_text(key + "\n", encoding="utf-8")
        profile_path.write_text(profile + "\n", encoding="utf-8")
        os.chmod(key_path, 0o444)
        os.chmod(profile_path, 0o444)
        return directory

    seed_a = make_seed("seed-a", "first-key", '{"profile":"first"}')
    seed_b = make_seed("seed-b", "second-key", '{"profile":"second"}')

    def invoke(seed_dir: Path, expected: int = 0) -> None:
        cp = run([
            "docker", "run", "--rm", "--network", "none", "--user", "10001:10001",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=0700,uid=10001,gid=10001",
            "--entrypoint", "/bin/sh",
            "-v", f"{config}:/etc/wow-sidecar",
            "-v", f"{seed_dir / 'github-app.pem'}:/seed/github-app.pem:ro",
            "-v", f"{seed_dir / 'operator-profile.json'}:/seed/operator-profile.json:ro",
            image, "-ec", script,
        ], check=False)
        if cp.returncode != expected:
            detail = (cp.stderr or cp.stdout or "")[-1200:]
            raise ValidationError(f"seed behavior expected {expected}, got {cp.returncode}: {detail}")

    invoke(seed_a)
    key_path = config / "github-app.pem"
    profile_path = config / "profiles" / "operator.json"
    marker = config / ".initialized-v1"
    first = (key_path.read_bytes(), profile_path.read_bytes(), marker.read_bytes())
    invoke(seed_b)
    second = (key_path.read_bytes(), profile_path.read_bytes(), marker.read_bytes())
    if first != second:
        raise ValidationError("seed helper overwrote initialized configuration")

    marker.unlink()
    invoke(seed_b, expected=42)
    if key_path.read_bytes() != first[0] or profile_path.read_bytes() != first[1]:
        raise ValidationError("partial-state refusal mutated managed configuration")

def full_compose_behavior(compose: dict[str, Any], root: Path) -> None:
    fixture_root = Path("/opt/tests/mnt/wow-sidecar")
    config = fixture_root / "config"
    state = fixture_root / "state"
    project = "foundry-wow-sidecar-full"
    compose_path = root / "wow-sidecar-full-compose.json"
    compose_path.write_text(json.dumps(compose, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    shutil.rmtree(fixture_root, ignore_errors=True)
    config.mkdir(parents=True)
    state.mkdir(parents=True)
    os.chown(config, 0, 0)
    os.chown(state, 0, 0)
    os.chmod(config, 0o750)
    os.chmod(state, 0o750)

    base = ["docker", "compose", "-p", project, "-f", str(compose_path)]
    try:
        up = run(base + ["up", "-d"], check=False)
        if up.returncode:
            logs = run(base + ["logs", "--no-color", "--tail", "100"], check=False)
            detail = (up.stderr or up.stdout or "")[-3000:] + "\n" + (logs.stdout or logs.stderr or "")[-5000:]
            raise ValidationError(f"full Compose graph failed to start: {detail}")

        running = set(run(base + ["ps", "--services", "--status", "running"]).stdout.split())
        exited = set(run(base + ["ps", "--services", "--status", "exited"]).stdout.split())
        if "wow-sidecar" not in running:
            raise ValidationError(f"worker is not running after full Compose start: {sorted(running)}")
        if not {"permissions", "wow-sidecar-config-seed"}.issubset(exited):
            raise ValidationError(f"one-shot helpers did not exit after full Compose start: {sorted(exited)}")

        expected = {
            config: (10001, 10001, 0o750),
            state: (10001, 10001, 0o750),
            config / "github-app.pem": (10001, 10001, 0o400),
            config / "profiles" / "operator.json": (10001, 10001, 0o400),
            config / ".initialized-v1": (10001, 10001, 0o444),
        }
        for target, (uid, gid, mode) in expected.items():
            st = target.stat()
            if (st.st_uid, st.st_gid, st.st_mode & 0o777) != (uid, gid, mode):
                raise ValidationError(
                    f"full Compose metadata drift at {target}: "
                    f"{st.st_uid}:{st.st_gid}:{oct(st.st_mode & 0o777)}"
                )

        # The synthetic key is intentionally invalid. The service loop must fail closed per-cycle, not exit.
        import time
        time.sleep(6)
        running = set(run(base + ["ps", "--services", "--status", "running"]).stdout.split())
        if "wow-sidecar" not in running:
            logs = run(base + ["logs", "--no-color", "--tail", "50", "wow-sidecar"], check=False)
            raise ValidationError(f"worker exited under public fixture: {(logs.stdout or logs.stderr or '')[-3000:]}")
    finally:
        run(base + ["down", "--remove-orphans"], check=False)
        shutil.rmtree(fixture_root, ignore_errors=True)


def validate(public_pull: bool) -> dict[str, Any]:
    for tool in ("git", "docker", "python3"):
        if not shutil.which(tool):
            raise ValidationError(f"required tool missing: {tool}")
    candidate = load_json(CANDIDATE_PATH)
    if not candidate["permissions_helper"].get("reference"):
        raise ValidationError("permissions helper reference is not pinned")

    root = Path(tempfile.mkdtemp(prefix="foundry-wow-sidecar-"))
    try:
        checkout = checkout_upstream(root, candidate)
        app_dir = install_candidate(checkout, candidate)
        compose = render_candidate(checkout, app_dir)
        image, seed_script = assert_render(compose, candidate)
        seed_behavior(image, seed_script, root)
        full_compose_behavior(compose, root)

        worker_help = run(["docker", "run", "--rm", image, "--help"])
        if "bounded trusted-host worker" not in (worker_help.stdout + worker_help.stderr):
            raise ValidationError("WOW worker entrypoint smoke output drift")
        run(["docker", "run", "--rm", "--entrypoint", "/bin/sh", image, "-ec", "command -v bash; command -v git; ! command -v gh"])

        canonical = json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()
        return {
            "result": "PASS",
            "candidate": "wow-sidecar-truenas-app",
            "wow_image": image,
            "permissions_helper": candidate["permissions_helper"]["reference"],
            "materializer": candidate["truenas_source"],
            "compose_sha256": hashlib.sha256(canonical).hexdigest(),
            "services": sorted((compose.get("services") or {}).keys()),
            "security": {
                "wow_runtime_uid_gid": "10001:10001",
                "wow_cap_drop_all": True,
                "wow_no_new_privileges": True,
                "worker_rootfs_read_only": True,
                "seed_rootfs_read_only": False,
                "seed_rootfs_exception": "inline-content configs require writable one-shot service rootfs",
                "wow_config_read_only": True,
                "host_paths_allowed_by_source_schema": False,
                "runtime_socket_allowed": False,
                "host_network": False,
                "privileged": False,
                "permissions_helper_scope": "ixVolume ownership only",
            },
            "seed_behavior": "PASS:create-once/preserve/fail-partial",
            "full_compose_behavior": "PASS:permissions/seed/worker",
            "ghcr_anonymous_pull": public_pull,
            "non_claims": [
                "no TrueNAS runtime realization",
                "no site credential use",
                "no execution-control request/claim/receipt mutation",
                "no GARM/root integration migration",
                "no live cutover or rollback claim",
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
