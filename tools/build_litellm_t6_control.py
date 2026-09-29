#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

SCHEMA = "semper-supra.litellm-truenas-t6-control/1"
APP_NAME = "rdte-t6-litellm"
GUEST_PORT = 30401
CONFIG_DIR = "/mnt/rdtepool/litellm-t6/config"
SECRET_DIR = "/mnt/rdtepool/litellm-t6/secrets"
CONFIG_FILE = "proxy_server_config.yaml"
FIXTURE_SECRET_NAMES = ["TEST_PROVIDER_KEY"]


class ControlError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ControlError(f"{path} must contain an object")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _service(compose: dict) -> tuple[str, dict]:
    services = compose.get("services")
    if not isinstance(services, dict) or len(services) != 1:
        raise ControlError("expected exactly one rendered service")
    name, service = next(iter(services.items()))
    if not isinstance(service, dict):
        raise ControlError("rendered service must be an object")
    return str(name), service


def _mount(service: dict, target: str) -> dict:
    matches = [
        v for v in service.get("volumes", [])
        if isinstance(v, dict) and v.get("target") == target
    ]
    if len(matches) != 1:
        raise ControlError(f"expected exactly one mount for {target}")
    return matches[0]


def validate(candidate: dict, compose: dict) -> dict:
    appliance = candidate.get("appliance") or {}
    source = candidate.get("source_materializer") or {}
    invariants = candidate.get("invariants") or {}
    image = appliance.get("reference")
    digest = appliance.get("digest")

    if not isinstance(image, str) or not image.startswith("ghcr.io/sempersupra/litellm-appliance@sha256:"):
        raise ControlError("candidate appliance reference is not digest pinned")
    if image != f"ghcr.io/sempersupra/litellm-appliance@{digest}":
        raise ControlError("candidate appliance reference/digest mismatch")
    if invariants.get("minimum_secret_tier") != "S1":
        raise ControlError("candidate secret tier is not S1")
    if invariants.get("management_credentials_allowed") is not False:
        raise ControlError("management credentials are not forbidden")
    if invariants.get("moving_tags_allowed") is not False:
        raise ControlError("moving tags are not forbidden")

    service_name, service = _service(compose)
    if service.get("image") != image:
        raise ControlError("rendered image does not match admitted appliance identity")

    cfg = _mount(service, "/config")
    sec = _mount(service, "/run/secrets/semper-env")
    for label, mount, source_path in (
        ("config", cfg, CONFIG_DIR),
        ("provider secrets", sec, SECRET_DIR),
    ):
        if mount.get("source") != source_path:
            raise ControlError(f"{label} source path drifted")
        if mount.get("read_only") is not True:
            raise ControlError(f"{label} mount is not read-only")

    ports = service.get("ports") or []
    if not any(
        isinstance(p, dict)
        and int(p.get("target", -1)) == 4000
        and str(p.get("published")) == str(GUEST_PORT)
        for p in ports
    ):
        raise ControlError("rendered guest port mapping drifted")

    env = service.get("environment") or {}
    if not isinstance(env, dict) or env.get("SEMPER_SECRET_DIR") != "/run/secrets/semper-env":
        raise ControlError("SEMPER_SECRET_DIR render drifted")

    rendered = json.dumps(compose, sort_keys=True)
    for forbidden in ("OPENROUTER_MANAGEMENT_KEY", "sk-or-mgmt-", ":latest", ":main-latest"):
        if forbidden in rendered:
            raise ControlError(f"forbidden rendered content: {forbidden}")

    return {
        "service_name": service_name,
        "appliance_reference": image,
        "appliance_digest": digest,
        "truenas_apps_commit": source.get("commit"),
        "truenas_lib_version": source.get("lib_version"),
        "truenas_lib_hash": source.get("lib_hash"),
    }


def build(candidate_path: Path, compose_path: Path, config_path: Path, values_path: Path,
          output: Path, foundry_ref: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", foundry_ref):
        raise ControlError("foundry_ref must be an exact 40-character commit SHA")

    candidate = load_json(candidate_path)
    compose = load_json(compose_path)
    facts = validate(candidate, compose)

    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(compose_path, output / "compose.json")
    shutil.copy2(config_path, output / CONFIG_FILE)
    shutil.copy2(values_path, output / "values.yaml")

    control = {
        "schema": SCHEMA,
        "foundry_ref": foundry_ref,
        "candidate": {
            "name": candidate.get("candidate"),
            "state": candidate.get("state"),
            "manifest_sha256": sha256_file(candidate_path),
            **facts,
        },
        "runtime": {
            "app_name": APP_NAME,
            "guest_port": GUEST_PORT,
            "config_dir": CONFIG_DIR,
            "secret_dir": SECRET_DIR,
            "config_file": CONFIG_FILE,
            "fixture_secret_names": FIXTURE_SECRET_NAMES,
        },
        "artifacts": {
            "compose_canonical_sha256": canonical_sha256(compose),
            "config_sha256": sha256_file(config_path),
            "values_sha256": sha256_file(values_path),
        },
        "secrets_captured": False,
    }
    (output / "control.json").write_text(
        json.dumps(control, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return control


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--compose", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--values", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--foundry-ref", required=True)
    a = p.parse_args()
    try:
        control = build(a.candidate, a.compose, a.config, a.values, a.output, a.foundry_ref)
        print(json.dumps({
            "status": "PASS",
            "schema": control["schema"],
            "foundry_ref": control["foundry_ref"],
            "compose_canonical_sha256": control["artifacts"]["compose_canonical_sha256"],
            "secrets_captured": False,
        }, sort_keys=True))
        return 0
    except (ControlError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
