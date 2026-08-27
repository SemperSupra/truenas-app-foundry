#!/usr/bin/env python3
"""Validate the pinned TrueNAS Apps materializer against known-good controls.

This is a public-safe execution-plane check. It never contacts a TrueNAS host,
starts an application, or consumes private credentials. The goal is narrower:
prove that one exact upstream TrueNAS Apps revision can render known-good catalog
applications and that the normalized Compose retains stable structural/security
properties.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_FILE = REPO_ROOT / ".foundry" / "truenas-apps-upstream.json"


class ValidationError(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if cp.returncode:
        detail = (cp.stderr or cp.stdout or "")[-4000:]
        raise ValidationError(
            f"command failed ({cp.returncode}): {' '.join(cmd)}\n{detail}"
        )
    return cp


def load_pin() -> dict[str, Any]:
    try:
        pin = json.loads(PIN_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {PIN_FILE}: {exc}") from exc

    for key in (
        "repository",
        "ref",
        "train",
        "library_version",
        "library_hash",
        "controls",
    ):
        if not pin.get(key):
            raise ValidationError(f"pin manifest missing {key}")
    if not isinstance(pin["controls"], list) or len(pin["controls"]) < 2:
        raise ValidationError("pin manifest must define at least two controls")
    if len(str(pin["ref"])) != 40 or any(c not in "0123456789abcdef" for c in pin["ref"]):
        raise ValidationError("upstream ref must be a full lowercase Git commit SHA")
    return pin


def checkout_upstream(root: Path, pin: dict[str, Any]) -> Path:
    checkout = root / "truenas-apps"
    run(["git", "init", "--quiet", str(checkout)], cwd=root)
    run(["git", "-C", str(checkout), "remote", "add", "origin", pin["repository"]], cwd=root)
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
            pin["ref"],
        ],
        cwd=root,
    )
    run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=root)
    actual = run(["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if actual != pin["ref"]:
        raise ValidationError(f"upstream checkout mismatch: expected {pin['ref']}, got {actual}")
    return checkout


def require_library_identity(app_dir: Path, pin: dict[str, Any]) -> None:
    app_yaml = app_dir / "app.yaml"
    if not app_yaml.is_file():
        raise ValidationError(f"missing catalog metadata: {app_yaml}")
    text = app_yaml.read_text()
    if f"lib_version: {pin['library_version']}" not in text:
        raise ValidationError(f"{app_dir.name}: library version differs from pinned baseline")
    if f"lib_version_hash: {pin['library_hash']}" not in text:
        raise ValidationError(f"{app_dir.name}: library hash differs from pinned baseline")


def normalize_rendered(checkout: Path, pin: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    app = str(control["app"])
    test_file = str(control["test_file"])
    train = str(pin["train"])
    app_dir = checkout / "ix-dev" / train / app
    require_library_identity(app_dir, pin)

    run(
        [
            "python3",
            ".github/scripts/ci.py",
            "--app",
            app,
            "--train",
            train,
            "--test-file",
            test_file,
            "--render-only=true",
        ],
        cwd=checkout,
    )

    rendered = app_dir / "templates" / "rendered" / "docker-compose.yaml"
    if not rendered.is_file():
        raise ValidationError(f"{train}/{app}:{test_file} produced no rendered Compose")

    normalized = run(
        [
            "docker",
            "compose",
            "-p",
            f"foundry-{app}"[:63],
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
        raise ValidationError(f"{app}: Docker Compose normalization did not return JSON") from exc
    if not isinstance(compose.get("services"), dict) or not compose["services"]:
        raise ValidationError(f"{app}: normalized Compose has no services")
    compose.pop("name", None)
    return compose


def service(compose: dict[str, Any], name: str) -> dict[str, Any]:
    value = compose.get("services", {}).get(name)
    if not isinstance(value, dict):
        raise ValidationError(
            f"expected service {name!r}; got {sorted(compose.get('services', {}))}"
        )
    return value


def mounts(value: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for mount in value.get("volumes") or []:
        if isinstance(mount, dict):
            result.append(
                {
                    "type": str(mount.get("type") or ""),
                    "source": str(mount.get("source") or ""),
                    "target": str(mount.get("target") or ""),
                    "read_only": bool(mount.get("read_only", False)),
                }
            )
        elif isinstance(mount, str):
            parts = mount.split(":")
            if len(parts) >= 2:
                result.append(
                    {
                        "type": "string",
                        "source": parts[0],
                        "target": parts[1],
                        "read_only": len(parts) > 2 and "ro" in parts[2].split(","),
                    }
                )
    return result


def has_target(value: dict[str, Any], target: str) -> bool:
    return any(mount["target"] == target for mount in mounts(value))


def has_docker_socket(value: dict[str, Any]) -> bool:
    return any(
        "/var/run/docker.sock" in mount["source"]
        or "/var/run/docker.sock" in mount["target"]
        for mount in mounts(value)
    )


def security(value: dict[str, Any]) -> dict[str, Any]:
    security_opts = [
        str(item).lower().replace(":", "=")
        for item in (value.get("security_opt") or [])
    ]
    return {
        "user": str(value.get("user") or ""),
        "privileged": bool(value.get("privileged", False)),
        "cap_drop": sorted(str(item).upper() for item in (value.get("cap_drop") or [])),
        "no_new_privileges": any(
            item.startswith("no-new-privileges=true") for item in security_opts
        ),
        "restart": str(value.get("restart") or ""),
        "healthcheck": bool(value.get("healthcheck")),
    }


def assert_library_security(label: str, value: dict[str, Any]) -> None:
    sec = security(value)
    failures: list[str] = []
    if sec["privileged"]:
        failures.append("privileged=true")
    if not sec["user"] or sec["user"] in {"0", "0:0", "root"}:
        failures.append("root or unspecified user")
    if "ALL" not in sec["cap_drop"]:
        failures.append("cap_drop ALL missing")
    if not sec["no_new_privileges"]:
        failures.append("no-new-privileges missing")
    if sec["restart"] != "unless-stopped":
        failures.append(f"unexpected restart policy {sec['restart']!r}")
    if not sec["healthcheck"]:
        failures.append("healthcheck missing")
    if failures:
        raise ValidationError(f"{label}: " + "; ".join(failures))


def assert_control(app: str, compose: dict[str, Any], primary_name: str) -> None:
    primary = service(compose, primary_name)
    assert_library_security(app, primary)

    if app == "forgejo-runner":
        for helper in ("init", "permissions"):
            service(compose, helper)
        if not has_target(primary, "/data"):
            raise ValidationError("forgejo-runner: /data storage missing")
        if not has_docker_socket(primary):
            raise ValidationError("forgejo-runner: expected upstream Docker socket missing")
        return

    if app == "ntfy":
        service(compose, "permissions")
        if not primary.get("ports"):
            raise ValidationError("ntfy: expected published HTTP port missing")
        for target in ("/var/ntfy", "/etc/ntfy"):
            if not has_target(primary, target):
                raise ValidationError(f"ntfy: expected storage target {target} missing")
        if has_docker_socket(primary):
            raise ValidationError("ntfy: unexpected Docker socket materialized")
        return

    raise ValidationError(f"no stable control assertions defined for {app!r}")


def fingerprint(compose: dict[str, Any], primary_name: str) -> dict[str, Any]:
    primary = service(compose, primary_name)
    canonical = json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()
    return {
        "services": sorted(compose.get("services", {})),
        "primary_service": primary_name,
        "security": security(primary),
        "mount_targets": sorted(mount["target"] for mount in mounts(primary)),
        "has_ports": bool(primary.get("ports")),
        "has_docker_socket": has_docker_socket(primary),
        "compose_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def validate() -> dict[str, Any]:
    for tool in ("git", "docker", "python3"):
        if not shutil.which(tool):
            raise ValidationError(f"required tool not found: {tool}")

    pin = load_pin()
    with tempfile.TemporaryDirectory(prefix="foundry-truenas-materialization-") as tmp_name:
        root = Path(tmp_name)
        checkout = checkout_upstream(root, pin)
        evidence: dict[str, Any] = {}
        for control in pin["controls"]:
            app = str(control["app"])
            primary_name = str(control["primary_service"])
            compose = normalize_rendered(checkout, pin, control)
            assert_control(app, compose, primary_name)
            evidence[f"{pin['train']}/{app}:{control['test_file']}"] = fingerprint(
                compose, primary_name
            )

    return {
        "result": "PASS",
        "trust_claim": "pinned TrueNAS Apps materializer reproduced known-good control envelopes",
        "non_claims": [
            "no private promotion approval",
            "no provider correctness claim",
            "no live TrueNAS compatibility claim",
        ],
        "upstream": {
            "repository": pin["repository"],
            "ref": pin["ref"],
            "train": pin["train"],
            "library_version": pin["library_version"],
            "library_hash": pin["library_hash"],
        },
        "controls": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        type=Path,
        help="optional path for the sanitized JSON evidence record",
    )
    args = parser.parse_args()
    try:
        evidence = validate()
        payload = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        if args.evidence:
            args.evidence.write_text(payload)
        print(payload, end="")
        return 0
    except (ValidationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
