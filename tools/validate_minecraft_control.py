#!/usr/bin/env python3
"""Public-safe source-render control for COLLAGE EXP-001."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / ".foundry" / "truenas-apps-upstream.json"
VALUES = ROOT / ".foundry" / "controls" / "minecraft-paper-hostpath-values.yaml"

class ValidationError(RuntimeError):
    pass


def run(cmd, cwd):
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if cp.returncode:
        raise ValidationError((cp.stderr or cp.stdout or "")[-4000:])
    return cp


def mounts(service):
    out = []
    for item in service.get("volumes") or []:
        if isinstance(item, dict):
            out.append({
                "source": str(item.get("source") or ""),
                "target": str(item.get("target") or ""),
                "read_only": bool(item.get("read_only", False)),
            })
        elif isinstance(item, str):
            parts = item.split(":")
            if len(parts) >= 2:
                out.append({
                    "source": parts[0],
                    "target": parts[1],
                    "read_only": len(parts) > 2 and "ro" in parts[2].split(","),
                })
    return out


def envmap(service):
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    result = {}
    for item in env:
        key, sep, value = str(item).partition("=")
        if sep:
            result[key] = value
    return result


def validate():
    for tool in ("git", "docker", "python3"):
        if not shutil.which(tool):
            raise ValidationError("missing tool: " + tool)

    pin = json.loads(PIN.read_text())
    ref = str(pin["ref"])
    if len(ref) != 40:
        raise ValidationError("invalid upstream pin")

    tmp = Path(tempfile.mkdtemp(prefix="collage-minecraft-control-"))
    try:
        checkout = tmp / "apps"
        run(["git", "init", "--quiet", str(checkout)], tmp)
        run(["git", "-C", str(checkout), "remote", "add", "origin", pin["repository"]], tmp)
        run(["git", "-C", str(checkout), "fetch", "--quiet", "--depth", "1", "origin", ref], tmp)
        run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"], tmp)
        actual = run(["git", "-C", str(checkout), "rev-parse", "HEAD"], tmp).stdout.strip()
        if actual != ref:
            raise ValidationError("upstream checkout mismatch")

        app = checkout / "ix-dev" / pin["train"] / "minecraft"
        app_yaml = (app / "app.yaml").read_text()
        if f"lib_version: {pin['library_version']}" not in app_yaml:
            raise ValidationError("library version drift")
        if f"lib_version_hash: {pin['library_hash']}" not in app_yaml:
            raise ValidationError("library hash drift")

        test_name = "collage-paper-hostpath-values.yaml"
        target = app / "templates" / "test_values" / test_name
        shutil.copyfile(VALUES, target)
        run([
            "python3", ".github/scripts/ci.py",
            "--app", "minecraft", "--train", pin["train"],
            "--test-file", test_name, "--render-only=true",
        ], checkout)

        rendered = app / "templates" / "rendered" / "docker-compose.yaml"
        cp = run([
            "docker", "compose", "-p", "foundry-collage-minecraft",
            "-f", str(rendered), "config", "--format", "json",
        ], checkout)
        compose = json.loads(cp.stdout)
        compose.pop("name", None)
        service = (compose.get("services") or {}).get("minecraft")
        if not isinstance(service, dict):
            raise ValidationError("minecraft service missing")

        env = envmap(service)
        if env.get("TYPE") != "PAPER":
            raise ValidationError("TYPE=PAPER not preserved")

        data = [m for m in mounts(service) if m["target"] == "/data"]
        if len(data) != 1:
            raise ValidationError("expected one /data mount")
        if data[0]["source"] != "/opt/tests/collage-world":
            raise ValidationError("external host-path /data source not preserved")
        if data[0]["read_only"]:
            raise ValidationError("/data unexpectedly read-only")

        if service.get("privileged"):
            raise ValidationError("privileged=true")
        if not service.get("healthcheck"):
            raise ValidationError("healthcheck missing")
        if not service.get("ports"):
            raise ValidationError("published Minecraft port missing")
        for m in mounts(service):
            if "/var/run/docker.sock" in m["source"] or "/var/run/docker.sock" in m["target"]:
                raise ValidationError("unexpected Docker socket")

        canonical = json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()
        return {
            "result": "PASS",
            "experiment": "COLLAGE EXP-001 pre-HIL source-render control",
            "trust_claim": "Pinned upstream TrueNAS Minecraft app expresses Paper with writable external host-path /data",
            "non_claims": [
                "no live TrueNAS qualification",
                "no world-delete/rebind behavior claim",
                "no COLLAGE controller claim",
            ],
            "upstream": {
                "repository": pin["repository"],
                "ref": ref,
                "app": "community/minecraft",
                "library_version": pin["library_version"],
                "library_hash": pin["library_hash"],
            },
            "server": {
                "type": env.get("TYPE"),
                "image": str(service.get("image") or ""),
                "data_mount": data[0],
                "healthcheck": bool(service.get("healthcheck")),
                "published_port": bool(service.get("ports")),
            },
            "compose_sha256": hashlib.sha256(canonical).hexdigest(),
        }
    finally:
        try:
            shutil.rmtree(tmp)
        except OSError as exc:
            print("WARNING: cleanup failed: " + str(exc), file=sys.stderr)


def main():
    try:
        evidence = validate()
        payload = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        (ROOT / "minecraft-control-evidence.json").write_text(payload)
        print(payload, end="")
        return 0
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
