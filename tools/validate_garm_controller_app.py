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
DUMMY_JWT_SECRET = "N4vR8xK2mQ7pL5sD9wF3cH6yT1jB0zUa"
DUMMY_DATABASE_PASSPHRASE = "Y7cD2mQ9vK4sR8pL1xF6nH3wT5jB0zUa"


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
        [
            "git",
            "-C",
            str(checkout),
            "fetch",
            "--quiet",
            "--depth",
            "1",
            "origin",
            materializer["commit"],
        ],
        cwd=root,
    )
    run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=root)
    actual = run(["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if actual != materializer["commit"]:
        raise ValidationError(
            f"materializer checkout drift: expected {materializer['commit']}, got {actual}"
        )
    return checkout


def install_candidate(checkout: Path, manifest: dict[str, Any]) -> Path:
    app_dir = checkout / "ix-dev" / "community" / "garm"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    shutil.copytree(SOURCE, app_dir)

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
        [
            "docker",
            "compose",
            "-p",
            "foundry-garm",
            "-f",
            str(rendered),
            "config",
            "--format",
            "json",
        ],
        cwd=checkout,
    )
    try:
        compose = json.loads(normalized.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError("Docker Compose normalization did not return JSON") from exc
    compose.pop("name", None)
    return compose


def mounts(service: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for value in service.get("volumes") or []:
        if isinstance(value, dict):
            result.append(
                {
                    "type": str(value.get("type") or ""),
                    "source": str(value.get("source") or ""),
                    "target": str(value.get("target") or ""),
                }
            )
        elif isinstance(value, str):
            parts = value.split(":")
            if len(parts) >= 2:
                result.append({"type": "string", "source": parts[0], "target": parts[1]})
    return result


def normalized_user(service: dict[str, Any], name: str) -> str:
    user = str(service.get("user") or "")
    if user in {"0", "root"}:
        return "0:0"
    if user == "0:0":
        return user
    raise ValidationError(f"{name}: expected explicitly-qualified root runtime, got {user!r}")


def assert_security(name: str, service: dict[str, Any]) -> str:
    if service.get("privileged"):
        raise ValidationError(f"{name}: privileged mode materialized")
    caps = {str(v).upper() for v in service.get("cap_drop") or []}
    if "ALL" not in caps:
        raise ValidationError(f"{name}: cap_drop ALL missing")
    opts = {str(v).lower().replace(":", "=") for v in service.get("security_opt") or []}
    if not any(v.startswith("no-new-privileges=true") for v in opts):
        raise ValidationError(f"{name}: no-new-privileges missing")
    return normalized_user(service, name)


def extract_seed_script(seed: dict[str, Any]) -> str:
    command = seed.get("command")
    if not isinstance(command, list):
        raise ValidationError(
            f"garm-config-seed: expected list command, got {type(command).__name__}"
        )
    parts = [str(v) for v in command]
    if len(parts) == 2 and parts[0] == "-ec":
        return parts[1]
    raise ValidationError(f"garm-config-seed: unexpected command shape {parts!r}")


def assert_render(
    compose: dict[str, Any], manifest: dict[str, Any]
) -> tuple[str, str, str, str]:
    services = compose.get("services") or {}
    if set(services) != EXPECTED_SERVICES:
        raise ValidationError(
            f"service inventory drift: expected {sorted(EXPECTED_SERVICES)}, got {sorted(services)}"
        )

    image = manifest["appliance"]["reference"]
    if ":mvp" in json.dumps(compose):
        raise ValidationError("mutable :mvp reference leaked into deployment artifact")

    controller = services["garm"]
    seed = services["garm-config-seed"]
    users: dict[str, str] = {}
    for name, service in (("garm", controller), ("garm-config-seed", seed)):
        if service.get("image") != image:
            raise ValidationError(f"{name}: exact appliance digest mismatch: {service.get('image')!r}")
        users[name] = assert_security(name, service)
        service_mounts = mounts(service)
        targets = [m["target"] for m in service_mounts]
        if targets != ["/etc/garm"]:
            raise ValidationError(f"{name}: unexpected persistent mount targets: {targets!r}")
        if any("docker.sock" in (m["source"] + m["target"]) for m in service_mounts):
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
    if not any(
        isinstance(port, dict) and int(port.get("target", 0)) == 8080
        for port in ports
    ):
        raise ValidationError("garm: fixed internal port 8080 not materialized")

    healthcheck = controller.get("healthcheck") or {}
    health_text = json.dumps(healthcheck)
    if "wget" not in health_text or "http://127.0.0.1:8080/ui/" not in health_text:
        raise ValidationError("garm: expected BusyBox wget /ui/ health probe not materialized")

    seed_script = extract_seed_script(seed)
    for required in (
        "if [ -e /etc/garm/config.toml ]",
        "[ ! -s /etc/garm/config.toml ]",
        "exit 42",
        "cp /seed/config.toml /etc/garm/config.toml",
    ):
        if required not in seed_script:
            raise ValidationError(
                f"garm-config-seed: missing fail-closed seed invariant {required!r}"
            )

    configs = compose.get("configs") or {}
    initial = configs.get("garm-initial-config") or {}
    content = str(initial.get("content") or "")
    if DUMMY_JWT_SECRET not in content or DUMMY_DATABASE_PASSPHRASE not in content:
        raise ValidationError("qualified dummy bootstrap configuration did not materialize as expected")
    for forbidden in ("enable_log_file", "log_file", "log_rotate_max_size", "log_rotate_backups", "log_rotate_compress"):
        if forbidden in content:
            raise ValidationError(f"unsupported file-logging key materialized: {forbidden}")
    if '[logging]\nlog_level = "info"' not in content:
        raise ValidationError("container-native logging level did not materialize as expected")
    lower = content.lower()
    if "github" in lower and "credential" in lower:
        raise ValidationError("GitHub credential material unexpectedly present in bootstrap config")

    return image, seed_script, users["garm-config-seed"], users["garm"]


def docker_hash(image: str, state: Path, user: str) -> str:
    cp = run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            user,
            "--entrypoint",
            "/bin/sh",
            "-v",
            f"{state}:/etc/garm",
            image,
            "-ec",
            "sha256sum /etc/garm/config.toml | awk '{print $1}'",
        ]
    )
    digest = cp.stdout.strip()
    if len(digest) != 64:
        raise ValidationError(f"unexpected config digest output: {digest!r}")
    return digest


def seed_behavior(image: str, seed_script: str, user: str, root: Path) -> None:
    state = root / "state"
    state.mkdir()
    seed_a = root / "seed-a.toml"
    seed_b = root / "seed-b.toml"
    seed_a.write_text("marker = 'first'\n", encoding="utf-8")
    seed_b.write_text("marker = 'second'\n", encoding="utf-8")

    def invoke(seed_file: Path, expected: int = 0) -> None:
        cp = run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                user,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges=true",
                "--entrypoint",
                "/bin/sh",
                "-v",
                f"{state}:/etc/garm",
                "-v",
                f"{seed_file}:/seed/config.toml:ro",
                image,
                "-ec",
                seed_script,
            ],
            check=False,
        )
        if cp.returncode != expected:
            detail = (cp.stderr or cp.stdout or "")[-1000:]
            raise ValidationError(
                f"seed behavior expected exit {expected}, got {cp.returncode}: {detail}"
            )

    invoke(seed_a)
    first = docker_hash(image, state, user)
    invoke(seed_b)
    second = docker_hash(image, state, user)
    if first != second:
        raise ValidationError("seed helper overwrote non-empty persistent config")

    run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            user,
            "--entrypoint",
            "/bin/sh",
            "-v",
            f"{state}:/etc/garm",
            image,
            "-ec",
            ": > /etc/garm/config.toml",
        ]
    )
    invoke(seed_b, expected=42)


def controller_smoke(image: str, user: str, root: Path) -> None:
    state = root / "controller-state"
    state.mkdir()
    (state / "config.toml").write_text(
        f"""[default]
enable_webhook_management = true

[logging]
log_level = "info"

[metrics]
disable_auth = false

[jwt_auth]
secret = "{DUMMY_JWT_SECRET}"
time_to_live = "8760h"

[apiserver]
bind = "0.0.0.0"
port = 8080
use_tls = false

[apiserver.webui]
enable = true

[database]
backend = "sqlite3"
passphrase = "{DUMMY_DATABASE_PASSPHRASE}"

[database.sqlite3]
db_file = "/etc/garm/garm.db"
""",
        encoding="utf-8",
    )
    name = f"foundry-garm-smoke-{os.getpid()}"
    try:
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--user",
                user,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges=true",
                "-v",
                f"{state}:/etc/garm",
                image,
            ]
        )
        deadline = time.time() + 45
        last = ""
        while time.time() < deadline:
            status = run(
                ["docker", "inspect", "-f", "{{.State.Status}}", name], check=False
            ).stdout.strip()
            if status != "running":
                last = run(
                    ["docker", "logs", "--tail", "80", name], check=False
                ).stdout[-4000:]
                break
            probe = run(
                [
                    "docker",
                    "exec",
                    name,
                    "wget",
                    "--quiet",
                    "-O",
                    "/dev/null",
                    "http://127.0.0.1:8080/ui/",
                ],
                check=False,
            )
            if probe.returncode == 0:
                return
            last = (probe.stderr or probe.stdout or "")[-1000:]
            time.sleep(2)
        logs = run(["docker", "logs", "--tail", "80", name], check=False)
        raise ValidationError(
            f"controller /ui/ smoke probe did not become ready: {last}\n{logs.stdout[-4000:]}"
        )
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
        image, seed_script, seed_user, controller_user = assert_render(compose, manifest)
        seed_behavior(image, seed_script, seed_user, root)
        controller_smoke(image, controller_user, root)
        canonical = json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()
        return {
            "result": "PASS",
            "candidate": "garm-controller-app",
            "appliance": image,
            "materializer": manifest["source_materializer"],
            "compose_sha256": hashlib.sha256(canonical).hexdigest(),
            "services": sorted((compose.get("services") or {}).keys()),
            "runtime_users": {
                "garm": controller_user,
                "garm-config-seed": seed_user,
            },
            "security": {
                "cap_drop_all": True,
                "no_new_privileges": True,
                "privileged": False,
                "host_paths_allowed_by_source_schema": False,
                "runtime_socket_allowed": False,
                "qualified_root_runtime": True,
            },
            "logging": "PASS:container-native/no persistent log file",
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
