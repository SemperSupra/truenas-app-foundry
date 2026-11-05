#!/usr/bin/env python3
"""Public-safe, profile-driven TrueNAS Foundry lifecycle planner.

This module plans lifecycle intent only. It never contacts or mutates a TrueNAS host.
CREATE/UPDATE materialization remains owned by truenas_target_profile.py; this layer
adds desired-state lifecycle, native-catalog upgrade, idempotent redeploy/reinstall
tokens, and explicit reconciliation gates for ambiguous operations.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "truenas_target_profile", HERE / "truenas_target_profile.py"
)
target = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(target)

SCHEMA = "truenas-foundry-lifecycle-intent/v2"
ADAPTERS = {"foundry-custom", "official-catalog"}
OPERATIONS = {
    "ENSURE_RUNNING",
    "ENSURE_STOPPED",
    "ENSURE_ABSENT",
    "REDEPLOY",
    "UPGRADE",
    "REINSTALL",
}
METHODS = {
    "START": "app.start",
    "STOP": "app.stop",
    "DELETE": "app.delete",
    "REDEPLOY": "app.redeploy",
    "UPGRADE": "app.upgrade",
}


class LifecycleError(RuntimeError):
    pass


def load(path: Path) -> dict[str, Any]:
    value = target.load_json(path)
    if not isinstance(value, dict):
        raise LifecycleError(f"{path} must contain an object")
    return value


def require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise LifecycleError(f"{label} is required")
    return text


def parse_intent(intent: dict[str, Any]) -> dict[str, Any]:
    if intent.get("schema") != SCHEMA:
        raise LifecycleError("unsupported lifecycle intent schema")
    operation = require_text(intent.get("operation"), "operation").upper()
    adapter = require_text(intent.get("adapter"), "adapter")
    if operation not in OPERATIONS:
        raise LifecycleError(f"unsupported lifecycle operation: {operation!r}")
    if adapter not in ADAPTERS:
        raise LifecycleError(f"unsupported lifecycle adapter: {adapter!r}")

    parsed = {
        "operation": operation,
        "adapter": adapter,
        "app_name": require_text(intent.get("app_name"), "app_name"),
        "materialization_identity": require_text(
            intent.get("materialization_identity"), "materialization_identity"
        ),
        "delete_policy": intent.get("delete_policy"),
        "operation_token": intent.get("operation_token"),
        "desired_catalog_version": intent.get("desired_catalog_version"),
    }

    if operation in {"ENSURE_ABSENT", "REINSTALL"}:
        if parsed["delete_policy"] != "retain-data":
            raise LifecycleError(
                f"{operation} currently requires delete_policy='retain-data'"
            )
    elif parsed["delete_policy"] is not None:
        raise LifecycleError("delete_policy is valid only for ENSURE_ABSENT/REINSTALL")

    if operation in {"REDEPLOY", "REINSTALL"}:
        parsed["operation_token"] = require_text(
            parsed["operation_token"], "operation_token"
        )
    elif parsed["operation_token"] is not None:
        raise LifecycleError(
            "operation_token is valid only for REDEPLOY/REINSTALL"
        )

    if operation == "UPGRADE":
        if adapter != "official-catalog":
            raise LifecycleError(
                "Foundry Custom App upgrades are materialization UPDATEs, not app.upgrade"
            )
        parsed["desired_catalog_version"] = require_text(
            parsed["desired_catalog_version"], "desired_catalog_version"
        )
    elif parsed["desired_catalog_version"] is not None:
        raise LifecycleError("desired_catalog_version is valid only for UPGRADE")

    return parsed


def observed_methods(observation: dict[str, Any]) -> set[str]:
    caps = observation.get("capabilities")
    if not isinstance(caps, dict) or not isinstance(caps.get("methods"), list):
        raise LifecycleError("observation.capabilities.methods is required")
    if not all(isinstance(x, str) and x for x in caps["methods"]):
        raise LifecycleError("observation.capabilities.methods must contain strings")
    return set(caps["methods"])


def operation_state(observation: dict[str, Any]) -> tuple[str, set[str]]:
    operation = observation.get("operation", {})
    if operation is None:
        operation = {}
    if not isinstance(operation, dict):
        raise LifecycleError("observation.operation must be an object")
    state = str(operation.get("state", "stable")).strip().lower()
    if state not in {"stable", "in-flight", "ambiguous"}:
        raise LifecycleError(f"unsupported observation.operation.state: {state!r}")
    completed = operation.get("completed_tokens", [])
    if not isinstance(completed, list) or not all(
        isinstance(x, str) and x for x in completed
    ):
        raise LifecycleError(
            "observation.operation.completed_tokens must be an array of strings"
        )
    return state, set(completed)


def _adapter_matches(adapter: str, app: dict[str, Any]) -> bool:
    custom = app.get("custom_app")
    if adapter == "foundry-custom":
        return custom is True
    return custom is False


def _stable_owned(
    app: dict[str, Any],
    ownership: dict[str, Any],
    intent: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if ownership.get("state") != "owned":
        blockers.append("lifecycle mutation requires freshly observed owned state")
    if app.get("present") is not True:
        blockers.append("lifecycle mutation requires the exact App to be present")
    if app.get("name") not in {None, intent["app_name"]}:
        blockers.append("observed App name does not match lifecycle intent")
    if str(app.get("materialization_identity", "")) != intent["materialization_identity"]:
        blockers.append("materialization identity does not match lifecycle intent")
    if app.get("present") is True and not _adapter_matches(intent["adapter"], app):
        blockers.append("observed App origin does not match lifecycle adapter")
    return blockers


def plan(
    observation: dict[str, Any],
    raw_intent: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    intent = parse_intent(raw_intent)
    discovery = target.discover(observation, registry)
    app = observation.get("app") if isinstance(observation.get("app"), dict) else {}
    ownership = (
        observation.get("ownership")
        if isinstance(observation.get("ownership"), dict)
        else {}
    )
    op_state, completed_tokens = operation_state(observation)
    methods = observed_methods(observation)

    blockers: list[str] = []
    if not discovery["exact_version_match"]:
        blockers.append("exact target version/profile is not known")
    if not discovery.get("profile"):
        blockers.append("exact compatibility profile is not materialized")
    if not discovery.get("profile_contract_match", False):
        blockers.append(
            "observed target capabilities do not satisfy the exact profile"
        )
    if not discovery["apply_qualified"]:
        blockers.append("target profile is not apply-qualified")

    if op_state in {"in-flight", "ambiguous"}:
        blockers.append(
            f"prior lifecycle operation is {op_state}; fresh reconciliation is required before retry"
        )

    action = "BLOCKED"
    required_method: str | None = None
    handoff: str | None = None

    if not blockers:
        operation = intent["operation"]
        present = app.get("present") is True
        state = str(app.get("state", ""))
        workloads = int(app.get("active_workloads", 0) or 0)
        ownership_state = str(ownership.get("state", ""))

        if operation == "ENSURE_ABSENT":
            if not present and ownership_state == "absent":
                action = "NOOP"
            else:
                blockers.extend(_stable_owned(app, ownership, intent))
                action = "DELETE" if not blockers else "BLOCKED"
                required_method = METHODS["DELETE"]
        elif operation in {"ENSURE_RUNNING", "ENSURE_STOPPED"}:
            blockers.extend(_stable_owned(app, ownership, intent))
            if not blockers:
                if operation == "ENSURE_RUNNING":
                    if state == "RUNNING" and workloads >= 1:
                        action = "NOOP"
                    else:
                        action = "START"
                        required_method = METHODS["START"]
                else:
                    if state == "STOPPED":
                        action = "NOOP"
                    else:
                        action = "STOP"
                        required_method = METHODS["STOP"]
        elif operation == "REDEPLOY":
            token = intent["operation_token"]
            if token in completed_tokens:
                action = "NOOP"
            else:
                blockers.extend(_stable_owned(app, ownership, intent))
                action = "REDEPLOY" if not blockers else "BLOCKED"
                required_method = METHODS["REDEPLOY"]
        elif operation == "UPGRADE":
            blockers.extend(_stable_owned(app, ownership, intent))
            if not blockers:
                desired_version = intent["desired_catalog_version"]
                observed_version = str(app.get("catalog_version", ""))
                if observed_version == desired_version:
                    action = "NOOP"
                elif app.get("upgrade_available") is True:
                    action = "UPGRADE"
                    required_method = METHODS["UPGRADE"]
                else:
                    blockers.append(
                        "catalog version differs but no native upgrade is currently observed"
                    )
                    action = "BLOCKED"
        elif operation == "REINSTALL":
            token = intent["operation_token"]
            if token in completed_tokens and present and ownership_state == "owned":
                blockers.extend(_stable_owned(app, ownership, intent))
                if not blockers and state == "RUNNING" and workloads >= 1:
                    action = "NOOP"
            elif present:
                blockers.extend(_stable_owned(app, ownership, intent))
                action = "DELETE_FOR_REINSTALL" if not blockers else "BLOCKED"
                required_method = METHODS["DELETE"]
            elif ownership_state == "absent":
                action = "CREATE_HANDOFF"
                handoff = "truenas_target_profile.plan"
            else:
                blockers.append(
                    "reinstall requires either exact owned presence or exact absence"
                )
                action = "BLOCKED"

    required = {"app.query", "app.config"}
    if required_method:
        required.add(required_method)
    missing = sorted(required - methods)
    if missing:
        blockers.append("required methods are not observed: " + ", ".join(missing))
        action = "BLOCKED"

    result = {
        "schema_version": 2,
        "status": "READY" if not blockers else "BLOCKED",
        "action": action,
        "operation": intent["operation"],
        "adapter": intent["adapter"],
        "target": discovery,
        "app_name": intent["app_name"],
        "materialization_identity": intent["materialization_identity"],
        "delete_policy": intent["delete_policy"],
        "operation_token": intent["operation_token"],
        "desired_catalog_version": intent["desired_catalog_version"],
        "required_method": required_method,
        "handoff": handoff,
        "missing_methods": missing,
        "blockers": blockers,
        "observation_sha256": discovery.get("observation_sha256"),
        "profile_identity_sha256": discovery.get("profile_identity_sha256"),
        "preconditions": {
            "reobserve_exact_version_before_apply": True,
            "reobserve_profile_contract_before_apply": True,
            "require_observation_sha256_match_before_apply": True,
            "require_profile_identity_sha256_match_before_apply": True,
            "reobserve_ownership_before_apply": True,
            "reobserve_materialization_identity_before_apply": True,
            "reconcile_ambiguous_operation_before_retry": True,
            "foreign_state_adoption_allowed": False,
            "delete_owned_storage_allowed": False,
        },
    }
    result["plan_sha256"] = target.canonical_sha256(result)
    return result


def verify(
    observation: dict[str, Any],
    raw_intent: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    intent = parse_intent(raw_intent)
    discovery = target.discover(observation, registry)
    app = observation.get("app") if isinstance(observation.get("app"), dict) else {}
    ownership = (
        observation.get("ownership")
        if isinstance(observation.get("ownership"), dict)
        else {}
    )
    op_state, completed_tokens = operation_state(observation)
    failures: list[str] = []

    if not discovery["exact_version_match"]:
        failures.append("target version no longer matches an exact profile")
    if not discovery.get("profile_contract_match", False):
        failures.append("target capability fingerprint no longer satisfies exact profile")
    if op_state != "stable":
        failures.append("target operation state is not stable")

    operation = intent["operation"]
    present = app.get("present") is True
    state = str(app.get("state", ""))
    workloads = int(app.get("active_workloads", 0) or 0)

    if operation == "ENSURE_ABSENT":
        if ownership.get("state") != "absent" or present:
            failures.append("App is not independently observed absent")
    else:
        if ownership.get("state") != "owned":
            failures.append("target App is not observed owned")
        if not present:
            failures.append("target App is absent")
        if str(app.get("materialization_identity", "")) != intent["materialization_identity"]:
            failures.append("materialization identity changed")
        if present and not _adapter_matches(intent["adapter"], app):
            failures.append("App origin no longer matches lifecycle adapter")

        if operation == "ENSURE_STOPPED":
            if state != "STOPPED":
                failures.append("App is not STOPPED")
        elif operation in {"ENSURE_RUNNING", "REDEPLOY", "REINSTALL"}:
            if state != "RUNNING" or workloads < 1:
                failures.append("App is not RUNNING with an active workload")
        elif operation == "UPGRADE":
            if str(app.get("catalog_version", "")) != intent["desired_catalog_version"]:
                failures.append("catalog version does not match desired upgrade target")
        if operation in {"REDEPLOY", "REINSTALL"}:
            token = intent["operation_token"]
            if token not in completed_tokens:
                failures.append("operation token is not durably observed complete")

    result = {
        "schema_version": 2,
        "status": "VERIFIED" if not failures else "VERIFY_FAILED",
        "operation": operation,
        "adapter": intent["adapter"],
        "target": discovery,
        "app_name": intent["app_name"],
        "materialization_identity": intent["materialization_identity"],
        "operation_token": intent["operation_token"],
        "desired_catalog_version": intent["desired_catalog_version"],
        "observation_sha256": discovery.get("observation_sha256"),
        "profile_identity_sha256": discovery.get("profile_identity_sha256"),
        "failures": failures,
    }
    result["verification_sha256"] = target.canonical_sha256(result)
    return result


def lifecycle_recipe() -> dict[str, Any]:
    return {
        "schema": "truenas-foundry-lifecycle-recipe/v1",
        "stages": [
            {"stage": "F0", "oracle": "exact observed target/profile/capability fingerprint"},
            {"stage": "F1", "oracle": "inventory resolve + immutable materialization identity"},
            {"stage": "F2", "oracle": "clean create + independent RUNNING/health verify"},
            {
                "stage": "F3",
                "oracle": "stop/start + config update/read-back + applicable upgrade + redeploy/persistence",
            },
            {
                "stage": "F4",
                "oracle": "re-plan=>NOOP + ambiguous/interrupted-operation reconciliation",
            },
            {
                "stage": "F5",
                "oracle": "retain-data delete/absence + reinstall + owned-state verification",
            },
        ],
        "adapter_rule": {
            "foundry-custom": "CREATE/materialization UPDATE through materialization planner; no app.upgrade",
            "official-catalog": "native catalog lifecycle; app.upgrade only when observed and applicable",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan", "verify", "recipe"])
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--intent", type=Path)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(".foundry/truenas-target-tracks.json"),
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "recipe":
            result = lifecycle_recipe()
        else:
            if not args.observation or not args.intent:
                raise LifecycleError("--observation and --intent are required")
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
        return 0 if result.get("status") not in {"BLOCKED", "VERIFY_FAILED"} else 2
    except (LifecycleError, target.TargetProfileError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
