#!/usr/bin/env python3
"""Fail-closed, offline topology oracle for the PUBLIC-SYNTHETIC Agent Dispatch Foundry fixture.

This is NOT an official TrueNAS catalog render or deployable application.
No private image reference, host path, credential, or live mutation is admitted.
"""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "candidates/agent-dispatch-app/synthetic-contract.json"
SCHEMA = "truenas-foundry-agent-dispatch-synthetic-contract/v1"


def validate(value):
    errors = []
    if not isinstance(value, dict):
        return ["contract must be an object"]
    if value.get("schema") != SCHEMA:
        errors.append("unknown fixture schema")
    if value.get("classification") != "public-synthetic":
        errors.append("only public-synthetic is permitted")
    if value.get("release_or_deployment_authority") != "none":
        errors.append("synthetic fixture never grants deploy/release authority")
    if value.get("source_is_private_product") is not False:
        errors.append("private product code cannot be a public fixture")
    image = value.get("image")
    if not isinstance(image, str) or not re.fullmatch(
        r"registry\\.invalid/foundry-rdte/synthetic-go@sha256:[0-9a-f]{64}", image
    ):
        errors.append("fixture requires an intentionally nonpullable digest-form image")
    storage = value.get("storage")
    if not isinstance(storage, dict):
        errors.append("missing synthetic storage policy")
        storage = {}
    if storage.get("custody") != "/synthetic/custody" or storage.get("custody_mode") != "ro":
        errors.append("custody must remain synthetic and read-only")
    if storage.get("ledger") != "/synthetic/ledger" or storage.get("ledger_mode") != "rw":
        errors.append("ledger must remain synthetic and writable")
    if storage.get("retain_on_app_delete") is not True:
        errors.append("retained data requires explicit true")
    services = value.get("services")
    if not isinstance(services, dict) or set(services) != {"control", "worker"}:
        return errors + ["exactly one control and one worker required"]
    expected_mounts = {
        "/synthetic/custody:/custody:ro",
        "/synthetic/ledger:/ledger:rw",
    }
    for role in ("control", "worker"):
        service = services[role]
        if not isinstance(service, dict):
            errors.append(f"{role}: invalid service object")
            continue
        if service.get("role") != role:
            errors.append(f"{role}: role mismatch")
        if service.get("user") != "65532:65532":
            errors.append(f"{role}: expected unprivileged UID/GID")
        if service.get("read_only") is not True:
            errors.append(f"{role}: immutable root required")
        if service.get("privileged") is not False or service.get("host_network") is not False:
            errors.append(f"{role}: privileged/host networking forbidden")
        if service.get("cap_drop") != ["ALL"] or service.get("security_opt") != ["no-new-privileges:true"]:
            errors.append(f"{role}: capability boundary weakened")
        mounts = service.get("mounts")
        if not isinstance(mounts, list) or set(mounts) != expected_mounts or len(mounts) != 2:
            errors.append(f"{role}: protected custody/ledger mount contract mismatch")
        expected_ports = ["127.0.0.1:18081:8080"] if role == "control" else []
        if service.get("ports") != expected_ports:
            errors.append(f"{role}: public ingress or unintended worker port forbidden")
        if service.get("health_path") != ("/readyz" if role == "control" else None):
            errors.append(f"{role}: health contract mismatch")
        if set(service) != {"role", "user", "read_only", "privileged", "host_network",
                            "cap_drop", "security_opt", "ports", "mounts", "health_path"}:
            errors.append(f"{role}: undeclared service fields denied")
    if set(value) != {"schema", "classification", "release_or_deployment_authority",
                      "source_is_private_product", "image", "storage", "services"}:
        errors.append("unknown top-level fields denied")
    return errors


if __name__ == "__main__":
    try:
        contract = json.loads(FIXTURE.read_text(encoding="utf-8"))
        faults = validate(contract)
    except (OSError, json.JSONDecodeError) as exc:
        faults = [f"invalid source contract: {exc.__class__.__name__}"]
    print(json.dumps({"classification": "public-synthetic-source-only",
                      "result": "PASS" if not faults else "FAIL", "failures": faults},
                     sort_keys=True))
    sys.exit(0 if not faults else 1)
