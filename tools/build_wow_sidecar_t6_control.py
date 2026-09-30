#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

SCHEMA = "semper-supra.wow-sidecar-truenas-t6-control/1"
APP_NAME = "rdte-t6-wow-sidecar"
EXPECTED_IMAGE = "ghcr.io/sempersupra/wow-sidecar@sha256:6b700ce7ba5ae44116b240ccbb54fb3b60dc952a9b4072ca1314b6f311bc5376"
EXPECTED_HELPER = "ixsystems/container-utils@sha256:46eba20714c1cc6784f60e245c32c33a2d9f616e47d804694a9854248c89a992"
FIXTURE_MARKER = "PUBLIC-QUALIFICATION-FIXTURE"
CONFIG_DIR = "/mnt/rdtepool/wow-sidecar-t6/config"
STATE_DIR = "/mnt/rdtepool/wow-sidecar-t6/state"
PRIVATE_REPO_RE = re.compile(r"(?:https://github\.com/)?(?:SemperSupra/)?[A-Za-z0-9_.-]+-private(?![A-Za-z0-9_.-])", re.IGNORECASE)


class ControlError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ControlError(f"{path} must contain an object")
    return value


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _service(compose: dict, name: str) -> dict:
    services = compose.get("services")
    if not isinstance(services, dict) or name not in services or not isinstance(services[name], dict):
        raise ControlError(f"missing rendered service {name}")
    return services[name]


def validate(candidate: dict, compose: dict) -> dict:
    container = candidate.get("container") or {}
    helper = candidate.get("permissions_helper") or {}
    source = candidate.get("truenas_source") or {}
    gates = candidate.get("gates") or {}

    if container.get("registry_reference") != EXPECTED_IMAGE:
        raise ControlError("WOW image identity drifted")
    if helper.get("reference") != EXPECTED_HELPER:
        raise ControlError("permissions helper identity drifted")
    if gates.get("public_app_render_qualified") is not True:
        raise ControlError("candidate is not public-render qualified")
    if gates.get("hil_eligible") is not True:
        raise ControlError("candidate is not HIL eligible")

    services = compose.get("services")
    if not isinstance(services, dict) or set(services) != {"wow-sidecar", "wow-sidecar-config-seed", "permissions"}:
        raise ControlError("unexpected rendered service inventory")

    worker = _service(compose, "wow-sidecar")
    seed = _service(compose, "wow-sidecar-config-seed")
    perms = _service(compose, "permissions")
    if worker.get("image") != EXPECTED_IMAGE or seed.get("image") != EXPECTED_IMAGE:
        raise ControlError("WOW service image drifted")
    if perms.get("image") != EXPECTED_HELPER:
        raise ControlError("permissions helper image drifted")

    for name, service in (("wow-sidecar", worker), ("wow-sidecar-config-seed", seed)):
        if str(service.get("user") or "") != "10001:10001":
            raise ControlError(f"{name} user drifted")
        if service.get("privileged"):
            raise ControlError(f"{name} became privileged")
        caps = {str(x).upper() for x in service.get("cap_drop") or []}
        if "ALL" not in caps:
            raise ControlError(f"{name} cap_drop ALL missing")
    if worker.get("read_only") is not True:
        raise ControlError("worker rootfs is not read-only")
    if seed.get("read_only") is not False:
        raise ControlError("seed bounded writable-rootfs exception drifted")

    if seed.get("network_mode") != "none":
        raise ControlError("seed helper network is not disabled")

    def mount(service: dict, target: str) -> dict:
        matches = [v for v in service.get("volumes", []) if isinstance(v, dict) and v.get("target") == target]
        if len(matches) != 1:
            raise ControlError(f"expected exactly one mount at {target}")
        return matches[0]

    worker_config = mount(worker, "/etc/wow-sidecar")
    worker_state = mount(worker, "/var/lib/wow-sidecar")
    seed_config = mount(seed, "/etc/wow-sidecar")
    if worker_config.get("source") != CONFIG_DIR or worker_config.get("read_only") is not True:
        raise ControlError("worker config fixture mount drifted")
    if worker_state.get("source") != STATE_DIR or worker_state.get("read_only") is True:
        raise ControlError("worker state fixture mount drifted")
    if seed_config.get("source") != CONFIG_DIR or seed_config.get("read_only") is True:
        raise ControlError("seed config fixture mount drifted")
    if perms.get("network_mode") != "none":
        raise ControlError("permissions helper network is not disabled")

    serialized = json.dumps(compose, sort_keys=True)
    if FIXTURE_MARKER not in serialized:
        raise ControlError("public fixture key marker is absent")
    if "ExampleOrg/control" not in serialized or "ExampleOrg/operator" not in serialized:
        raise ControlError("public fixture repository identities are absent")
    if PRIVATE_REPO_RE.search(serialized):
        raise ControlError("private repository identity leaked into public control")
    for forbidden in ("docker.sock", "/var/run/docker", "BEGIN OPENSSH PRIVATE KEY", "sk-", "ghp_"):
        if forbidden in serialized:
            raise ControlError(f"forbidden rendered content: {forbidden}")

    return {
        "wow_image": EXPECTED_IMAGE,
        "permissions_helper": EXPECTED_HELPER,
        "truenas_apps_commit": source.get("commit"),
        "truenas_lib_version": source.get("lib_version"),
        "truenas_lib_hash": source.get("lib_hash"),
        "runtime_user": container.get("runtime_user"),
    }


def build(candidate_path: Path, compose_path: Path, output: Path, foundry_ref: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", foundry_ref):
        raise ControlError("foundry_ref must be an exact 40-character commit SHA")
    candidate = load_json(candidate_path)
    compose = load_json(compose_path)
    facts = validate(candidate, compose)

    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(compose_path, output / "compose.json")
    shutil.copy2(candidate_path, output / "candidate.json")
    control = {
        "schema": SCHEMA,
        "foundry_ref": foundry_ref,
        "candidate": {
            "name": candidate.get("candidate"),
            "phase": candidate.get("phase"),
            "manifest_sha256": file_sha256(candidate_path),
            **facts,
        },
        "runtime": {
            "app_name": APP_NAME,
            "expected_fixture_failure_boundary": "github-app-authentication",
            "production_credentials_present": False,
            "fixture_key_marker": FIXTURE_MARKER,
            "fixture_config_dir": CONFIG_DIR,
            "fixture_state_dir": STATE_DIR,
        },
        "artifacts": {
            "compose_canonical_sha256": canonical_sha256(compose),
        },
        "secrets_captured": False,
        "claim_boundary": "Disposable TrueNAS software/runtime fixture only; not production GitHub-App positive-path or state-preserving cutover evidence.",
    }
    (output / "control.json").write_text(json.dumps(control, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return control


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--compose", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--foundry-ref", required=True)
    a = p.parse_args()
    try:
        result = build(a.candidate, a.compose, a.output, a.foundry_ref)
        print(json.dumps({
            "status": "PASS",
            "schema": result["schema"],
            "foundry_ref": result["foundry_ref"],
            "compose_canonical_sha256": result["artifacts"]["compose_canonical_sha256"],
            "production_credentials_present": False,
        }, sort_keys=True))
        return 0
    except (ControlError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
