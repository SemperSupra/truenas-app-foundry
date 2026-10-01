#!/usr/bin/env python3
"""Public-safe TrueNAS Foundry lifecycle planning and verification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import truenas_target_profile as target


SCHEMA = "truenas-foundry-lifecycle-intent/v1"
METHODS = {
    "START": "app.start",
    "STOP": "app.stop",
    "REDEPLOY": "app.redeploy",
    "DELETE": "app.delete",
}


class LifecycleError(RuntimeError):
    pass


def load(path: Path) -> dict[str, Any]:
    value = target.load_json(path)
    if not isinstance(value, dict):
        raise LifecycleError(f"{path} must contain an object")
    return value


def parse_intent(intent: dict[str, Any]) -> tuple[str, str, str, str | None]:
    if intent.get("schema") != SCHEMA:
        raise LifecycleError("unsupported lifecycle intent schema")
    operation = str(intent.get("operation", "")).strip().upper()
    app_name = str(intent.get("app_name", "")).strip()
    identity = str(intent.get("materialization_identity", "")).strip()
    policy = intent.get("delete_policy")
    if operation not in METHODS:
        raise LifecycleError(f"unsupported lifecycle operation: {operation!r}")
    if not app_name or not identity:
        raise LifecycleError("app_name and materialization_identity are required")
    if operation == "DELETE":
        if policy != "retain-data":
            raise LifecycleError(
                "generic DELETE currently requires delete_policy='retain-data'"
            )
    elif policy is not None:
        raise LifecycleError("delete_policy is valid only for DELETE")
    return operation, app_name, identity, policy


def observed_methods(observation: dict[str, Any]) -> set[str]:
    caps = observation.get("capabilities")
    if not isinstance(caps, dict) or not isinstance(caps.get("methods"), list):
        raise LifecycleError("observation.capabilities.methods is required")
    return {str(x) for x in caps["methods"]}


def plan(
    observation: dict[str, Any],
    intent: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    operation, app_name, identity, policy = parse_intent(intent)
    discovery = target.discover(observation, registry)
    app = observation.get("app") if isinstance(observation.get("app"), dict) else {}
    ownership = (
        observation.get("ownership")
        if isinstance(observation.get("ownership"), dict)
        else {}
    )
    required = {METHODS[operation], "app.query", "app.config"}
    missing = sorted(required - observed_methods(observation))

    blockers: list[str] = []
    if not discovery["exact_version_match"]:
        blockers.append("exact target version/profile is not known")
    if not discovery.get("profile"):
        blockers.append("exact compatibility profile is not materialized")
    if not discovery["apply_qualified"]:
        blockers.append("target profile is not apply-qualified")
    if missing:
        blockers.append("required methods are not observed: " + ", ".join(missing))
    if ownership.get("state") != "owned":
        blockers.append("lifecycle mutation requires freshly observed owned state")
    if app.get("present") is not True:
        blockers.append("lifecycle mutation requires the exact App to be present")
    if app.get("name") not in {None, app_name}:
        blockers.append("observed App name does not match lifecycle intent")
    if str(app.get("materialization_identity", "")) != identity:
        blockers.append("materialization identity does not match lifecycle intent")

    action = "BLOCKED"
    if not blockers:
        state = str(app.get("state", ""))
        workloads = int(app.get("active_workloads", 0) or 0)
        if operation == "STOP" and state == "STOPPED":
            action = "NOOP"
        elif operation == "START" and state == "RUNNING" and workloads >= 1:
            action = "NOOP"
        else:
            action = operation

    result = {
        "schema_version": 1,
        "status": "READY" if not blockers else "BLOCKED",
        "action": action,
        "operation": operation,
        "target": discovery,
        "app_name": app_name,
        "materialization_identity": identity,
        "delete_policy": policy,
        "required_method": METHODS[operation],
        "missing_methods": missing,
        "blockers": blockers,
        "preconditions": {
            "reobserve_exact_version_before_apply": True,
            "reobserve_ownership_before_apply": True,
            "reobserve_materialization_identity_before_apply": True,
            "reobserve_required_methods_before_apply": True,
            "foreign_state_adoption_allowed": False,
            "delete_owned_storage_allowed": False,
        },
    }
    result["plan_sha256"] = target.canonical_sha256(result)
    return result


def verify(
    observation: dict[str, Any],
    intent: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    operation, app_name, identity, policy = parse_intent(intent)
    discovery = target.discover(observation, registry)
    app = observation.get("app") if isinstance(observation.get("app"), dict) else {}
    ownership = (
        observation.get("ownership")
        if isinstance(observation.get("ownership"), dict)
        else {}
    )

    failures: list[str] = []
    if not discovery["exact_version_match"]:
        failures.append("target version no longer matches an exact profile")

    if operation == "DELETE":
        if ownership.get("state") != "absent":
            failures.append("deleted App is not observed absent")
        if app.get("present") is True:
            failures.append("deleted App is still present")
    else:
        if ownership.get("state") != "owned":
            failures.append("target App is not observed owned")
        if app.get("present") is not True:
            failures.append("target App is absent")
        if str(app.get("materialization_identity", "")) != identity:
            failures.append("materialization identity changed")
        state = str(app.get("state", ""))
        workloads = int(app.get("active_workloads", 0) or 0)
        if operation == "STOP":
            if state != "STOPPED":
                failures.append("App is not STOPPED")
        else:
            if state != "RUNNING":
                failures.append("App is not RUNNING")
            if workloads < 1:
                failures.append("active workload count below lifecycle minimum")

    result = {
        "schema_version": 1,
        "status": "VERIFIED" if not failures else "VERIFY_FAILED",
        "operation": operation,
        "target": discovery,
        "app_name": app_name,
        "materialization_identity": identity,
        "delete_policy": policy,
        "failures": failures,
    }
    result["verification_sha256"] = target.canonical_sha256(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan", "verify"])
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(".foundry/truenas-target-tracks.json"),
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        observation = load(args.observation)
        intent = load(args.intent)
        registry = target.load_registry(args.registry)
        result = (
            plan(observation, intent, registry)
            if args.command == "plan"
            else verify(observation, intent, registry)
        )
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0 if result["status"] not in {"BLOCKED", "VERIFY_FAILED"} else 2
    except (LifecycleError, target.TargetProfileError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
