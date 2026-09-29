#!/usr/bin/env python3
"""Public-safe qualification for the native TrueNAS Drasl App candidate."""
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
CANDIDATE = REPO_ROOT / "candidates" / "drasl-app" / "candidate.json"
SOURCE = REPO_ROOT / "candidates" / "drasl-app" / "ix-dev" / "community" / "drasl"


class ValidationError(RuntimeError):
    pass


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if check and cp.returncode:
        detail = (cp.stderr or cp.stdout or "")[-5000:]
        raise ValidationError(
            f"command failed ({cp.returncode}): {' '.join(cmd)}\n{detail}"
        )
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
    run(
        ["git", "-C", str(checkout), "remote", "add", "origin", materializer["repository"]],
        cwd=root,
    )
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
    run(
        ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
        cwd=root,
    )
    actual = run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=root
    ).stdout.strip()
    if actual != materializer["commit"]:
        raise ValidationError(
            f"materializer checkout drift: expected {materializer['commit']}, got {actual}"
        )
    return checkout


def install_candidate(checkout: Path) -> Path:
    app_dir = checkout / "ix-dev" / "community" / "drasl"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    shutil.copytree(SOURCE, app_dir)
    return app_dir


def render_candidate(checkout: Path, app_dir: Path) -> dict[str, Any]:
    run(
        [
            "python3",
            ".github/scripts/ci.py",
            "--app",
            "drasl",
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
            "foundry-drasl",
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
                result.append(
                    {"type": "string", "source": parts[0], "target": parts[1]}
                )
    return result


def assert_render(compose: dict[str, Any], manifest: dict[str, Any]) -> str:
    services = compose.get("services") or {}
    if set(services) != {"drasl", "permissions"}:
        raise ValidationError(
            f"service inventory drift: expected ['drasl', 'permissions'], got {sorted(services)}"
        )

    drasl = services["drasl"]
    image = str(drasl.get("image") or "")
    if image != manifest["upstream"]["image"]:
        raise ValidationError(
            f"image drift: expected {manifest['upstream']['image']!r}, got {image!r}"
        )

    if str(drasl.get("user") or "") != "568:568":
        raise ValidationError(
            f"drasl: expected non-root 568:568, got {drasl.get('user')!r}"
        )
    if drasl.get("privileged"):
        raise ValidationError("drasl: privileged mode materialized")
    cap_drop = {str(value).upper() for value in drasl.get("cap_drop") or []}
    if "ALL" not in cap_drop:
        raise ValidationError("drasl: cap_drop ALL missing")
    security_opts = {
        str(value).lower().replace(":", "=")
        for value in drasl.get("security_opt") or []
    }
    if not any(
        value.startswith("no-new-privileges=true") for value in security_opts
    ):
        raise ValidationError("drasl: no-new-privileges missing")
    if drasl.get("restart") != "unless-stopped":
        raise ValidationError(
            f"drasl: unexpected restart policy {drasl.get('restart')!r}"
        )

    targets = {mount["target"] for mount in mounts(drasl)}
    if targets != {"/var/lib/drasl"}:
        raise ValidationError(
            f"drasl: unexpected persistent mount targets: {sorted(targets)}"
        )
    if any(
        "docker.sock" in (mount["source"] + mount["target"])
        for mount in mounts(drasl)
    ):
        raise ValidationError("drasl: container runtime socket materialized")

    ports = drasl.get("ports") or []
    if not any(
        isinstance(port, dict) and int(port.get("target", 0)) == 25585
        for port in ports
    ):
        raise ValidationError("drasl: internal port 25585 not materialized")

    health = drasl.get("healthcheck") or {}
    if health and health.get("disable") is not True and health.get("test") != ["NONE"]:
        raise ValidationError(
            f"drasl: expected disabled in-container healthcheck, got {health!r}"
        )

    configs = compose.get("configs") or {}
    config = configs.get("drasl-config") or {}
    content = str(config.get("content") or "")
    for required in (
        'Domain = "drasl.example.test"',
        'BaseURL = "http://drasl.example.test:30085"',
        'ListenAddress = "0.0.0.0:25585"',
        'StateDirectory = "/var/lib/drasl"',
        'PlayerUUIDGeneration = "random"',
        "SignPublicKeys = true",
        "[RegistrationUsernamePassword.CreateNewPlayer]",
        "RequireInvite = true",
    ):
        if required not in content:
            raise ValidationError(
                f"Drasl config did not materialize {required!r}"
            )

    # The upstream test harness lowers an ixVolume fixture to a concrete host-side
    # bind path. The source-schema workflow, not normalized Compose, is the
    # authoritative check that users cannot select arbitrary host paths.
    return image


def resolved_digest(image: str) -> str:
    raw = run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image]
    ).stdout.strip()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"could not decode RepoDigests for {image}: {raw!r}"
        ) from exc
    for value in values or []:
        value = str(value)
        if "@sha256:" in value:
            return value
    raise ValidationError(f"image {image} has no resolved RepoDigest")


def write_smoke_config(path: Path) -> None:
    path.write_text(
        """Domain = "drasl.example.test"
BaseURL = "http://127.0.0.1:25585"
InstanceName = "Foundry Drasl Runtime Smoke"
ApplicationOwner = "SemperSupra"
ListenAddress = "0.0.0.0:25585"
StateDirectory = "/var/lib/drasl"
PlayerUUIDGeneration = "random"
SignPublicKeys = true
PreMigrationBackups = true
DefaultAdmins = []

[RegistrationUsernamePassword.CreateNewPlayer]
Allow = true
RequireInvite = true
AllowChoosingUUID = false
""",
        encoding="utf-8",
    )
    path.chmod(0o444)


def start_runtime(image: str, config: Path, state: Path, name: str) -> int:
    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--user",
            "568:568",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "-p",
            "127.0.0.1::25585",
            "-v",
            f"{config}:/etc/drasl/config.toml:ro",
            "-v",
            f"{state}:/var/lib/drasl",
            image,
        ]
    )
    deadline = time.time() + 60
    last = ""
    while time.time() < deadline:
        status = run(
            ["docker", "inspect", "-f", "{{.State.Status}}", name], check=False
        ).stdout.strip()
        if status != "running":
            logs = run(["docker", "logs", "--tail", "120", name], check=False)
            raise ValidationError(
                f"Drasl exited during startup: {logs.stdout[-4000:]}"
            )
        port = run(
            ["docker", "port", name, "25585/tcp"], check=False
        ).stdout.strip()
        if port:
            endpoint = port.rsplit(":", 1)[-1]
            probe = run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "5",
                    f"http://127.0.0.1:{endpoint}/authlib-injector",
                ],
                check=False,
            )
            if probe.returncode == 0:
                return int(endpoint)
            last = (probe.stderr or probe.stdout or "")[-1000:]
        time.sleep(2)
    logs = run(["docker", "logs", "--tail", "120", name], check=False)
    raise ValidationError(
        f"Drasl HTTP service did not become ready: {last}\n{logs.stdout[-4000:]}"
    )


def runtime_smoke(image: str, root: Path) -> dict[str, Any]:
    config = root / "config.toml"
    state = root / "state"
    state.mkdir()
    os.chown(state, 568, 568)
    write_smoke_config(config)

    key = state / "key.pkcs8"
    first_name = f"foundry-drasl-smoke-a-{os.getpid()}"
    second_name = f"foundry-drasl-smoke-b-{os.getpid()}"
    try:
        first_port = start_runtime(image, config, state, first_name)
        deadline = time.time() + 20
        while time.time() < deadline and not key.is_file():
            time.sleep(1)
        if not key.is_file() or key.stat().st_size == 0:
            raise ValidationError("Drasl did not create persistent key.pkcs8")
        first_hash = hashlib.sha256(key.read_bytes()).hexdigest()
        run(["docker", "rm", "-f", first_name], check=False)

        second_port = start_runtime(image, config, state, second_name)
        if (
            not key.is_file()
            or hashlib.sha256(key.read_bytes()).hexdigest() != first_hash
        ):
            raise ValidationError(
                "Drasl signing key was not preserved across restart"
            )

        db_files = sorted(path.name for path in state.glob("*.db"))
        if not db_files:
            raise ValidationError("Drasl did not create a persistent database")
        return {
            "runtime_user": "568:568",
            "first_http_port": first_port,
            "second_http_port": second_port,
            "persistent_key_sha256": first_hash,
            "database_files": db_files,
            "result": "PASS",
        }
    finally:
        run(["docker", "rm", "-f", first_name], check=False)
        run(["docker", "rm", "-f", second_name], check=False)


def validate() -> dict[str, Any]:
    for tool in ("git", "docker", "python3", "curl"):
        if not shutil.which(tool):
            raise ValidationError(f"required tool missing: {tool}")

    manifest = load_json(CANDIDATE)
    root = Path(tempfile.mkdtemp(prefix="foundry-drasl-app-"))
    try:
        checkout = checkout_upstream(root, manifest)
        app_dir = install_candidate(checkout)
        compose = render_candidate(checkout, app_dir)
        image = assert_render(compose, manifest)
        run(["docker", "pull", image])
        digest = resolved_digest(image)
        runtime = runtime_smoke(image, root)

        canonical = json.dumps(
            compose, sort_keys=True, separators=(",", ":")
        ).encode()
        return {
            "result": "PASS",
            "candidate": "drasl-app",
            "upstream": manifest["upstream"],
            "resolved_image": digest,
            "materializer": manifest["source_materializer"],
            "compose_sha256": hashlib.sha256(canonical).hexdigest(),
            "services": sorted((compose.get("services") or {}).keys()),
            "security": {
                "runtime_user": "568:568",
                "cap_drop_all": True,
                "no_new_privileges": True,
                "privileged": False,
                "host_paths_allowed_by_source_schema": False,
                "runtime_socket_allowed": False,
                "in_container_healthcheck": "disabled",
            },
            "runtime_smoke": runtime,
            "non_claims": [
                "no live TrueNAS runtime realization",
                "no site DNS or TLS qualification",
                "no TrueNAS persistence/upgrade/rollback HIL",
                "no Velocity Identity integration claim",
                "no public catalog acceptance claim",
            ],
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        evidence = validate()
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
