#!/usr/bin/env python3
"""Deterministic TrueNAS target discovery, planning, and verification contracts.

This public-safe tool never contacts a TrueNAS host and never mutates one. A site
adapter supplies an observation envelope. The tool selects only exact qualified
profiles for mutation planning and fails closed for unknown/future builds.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any


class TargetProfileError(RuntimeError):
    pass


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetProfileError(f"cannot read JSON {path}: {exc}") from exc


def normalized_version(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("TrueNAS-"):
        text = text[len("TrueNAS-") :]
    return text


def required_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TargetProfileError(f"{label} must be an object")
    return value


def load_registry(path: Path) -> dict[str, Any]:
    registry = required_mapping(load_json(path), "registry")
    if registry.get("schema_version") != 1:
        raise TargetProfileError("unsupported target registry schema")
    if not isinstance(registry.get("targets"), list):
        raise TargetProfileError("registry.targets must be an array")
    return registry


def discover(observation: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    system = required_mapping(observation.get("system"), "observation.system")
    version = normalized_version(system.get("version", ""))
    if not version:
        raise TargetProfileError("observation.system.version is required")

    exact = next((t for t in registry["targets"] if t.get("version") == version), None)
    if exact is not None:
        contract = required_mapping(exact.get("profile_contract"), f"target {version}.profile_contract")
        required_methods = contract.get("required_public_methods")
        if not isinstance(required_methods, list) or not required_methods or not all(
            isinstance(x, str) and x for x in required_methods
        ):
            raise TargetProfileError(f"target {version}.profile_contract.required_public_methods must be non-empty strings")
        missing_profile_methods = sorted(set(required_methods) - _methods(observation))
        bootstrap_probe = contract.get("bootstrap_capability_probe")
        if not isinstance(bootstrap_probe, str) or not bootstrap_probe:
            raise TargetProfileError(
                f"target {version}.profile_contract.bootstrap_capability_probe must be a non-empty string"
            )
        bootstrap_probe_satisfied = _bootstrap_probes(observation).get(bootstrap_probe) is True
        missing_bootstrap_probes = [] if bootstrap_probe_satisfied else [bootstrap_probe]
        profile_identity = {
            "profile": exact.get("profile"),
            "profile_blob_sha": contract.get("profile_blob_sha"),
            "middleware_ref": exact.get("middleware_ref"),
            "middleware_commit": contract.get("middleware_commit"),
            "source_api_family": contract.get("source_api_family"),
            "storage_semantics": contract.get("storage_semantics"),
            "apps_gate_semantics": contract.get("apps_gate_semantics"),
            "bootstrap_capability_probe": bootstrap_probe,
        }
        if not all(isinstance(v, str) and v for v in profile_identity.values()):
            raise TargetProfileError(f"target {version} profile identity is incomplete")
        profile_identity_sha256 = canonical_sha256(profile_identity)
        profile_contract_match = not missing_profile_methods and bootstrap_probe_satisfied
        registry_apply_qualified = bool(exact.get("apply_qualified", False))
        effective_apply_qualified = registry_apply_qualified and profile_contract_match
        result = {
            "schema_version": 1,
            "status": (
                "EXACT_PROFILE"
                if exact.get("profile") and profile_contract_match
                else "EXACT_PROFILE_CAPABILITY_MISMATCH"
                if exact.get("profile")
                else "EXACT_TARGET_PROFILE_PENDING"
            ),
            "observed_version": version,
            "channel": exact.get("channel"),
            "profile": exact.get("profile"),
            "middleware_ref": exact.get("middleware_ref"),
            "middleware_commit": exact.get("middleware_commit"),
            "source_qualification": exact.get("source_qualification"),
            "runtime_qualification": exact.get("runtime_qualification"),
            "accepted_runtime_rung": exact.get("accepted_runtime_rung"),
            "registry_apply_qualified": registry_apply_qualified,
            "apply_qualified": effective_apply_qualified,
            "exact_version_match": True,
            "profile_contract_match": profile_contract_match,
            "missing_profile_methods": missing_profile_methods,
            "bootstrap_capability_probe": bootstrap_probe,
            "bootstrap_probe_satisfied": bootstrap_probe_satisfied,
            "missing_bootstrap_probes": missing_bootstrap_probes,
            "profile_identity": profile_identity,
            "profile_identity_sha256": profile_identity_sha256,
            "observation_sha256": canonical_sha256(observation),
            "qualification_only": not effective_apply_qualified,
        }
        result["discovery_sha256"] = canonical_sha256(result)
        return result

    for track in registry.get("future_tracks", []):
        if fnmatch.fnmatchcase(version, str(track.get("selector", ""))):
            result = {
                "schema_version": 1,
                "status": "FUTURE_TRACK_UNQUALIFIED",
                "observed_version": version,
                "channel": track.get("channel"),
                "profile": None,
                "middleware_ref": None,
                "middleware_commit": None,
                "source_qualification": "pending-exact-profile",
                "runtime_qualification": "pending-exact-profile",
                "accepted_runtime_rung": None,
                "apply_qualified": False,
                "exact_version_match": False,
                "qualification_only": True,
                "track_selector": track.get("selector"),
            }
            result["discovery_sha256"] = canonical_sha256(result)
            return result

    result = {
        "schema_version": 1,
        "status": "UNKNOWN_TARGET",
        "observed_version": version,
        "channel": None,
        "profile": None,
        "middleware_ref": None,
        "middleware_commit": None,
        "source_qualification": "unknown",
        "runtime_qualification": "unknown",
        "accepted_runtime_rung": None,
        "apply_qualified": False,
        "exact_version_match": False,
        "qualification_only": True,
    }
    result["discovery_sha256"] = canonical_sha256(result)
    return result


def _bootstrap_probes(observation: dict[str, Any]) -> dict[str, bool]:
    caps = required_mapping(observation.get("capabilities", {}), "observation.capabilities")
    probes = caps.get("bootstrap_probes", {})
    if not isinstance(probes, dict) or not all(
        isinstance(k, str) and k and isinstance(v, bool) for k, v in probes.items()
    ):
        raise TargetProfileError(
            "observation.capabilities.bootstrap_probes must be an object of boolean results"
        )
    return probes


def _methods(observation: dict[str, Any]) -> set[str]:
    caps = required_mapping(observation.get("capabilities", {}), "observation.capabilities")
    methods = caps.get("methods", [])
    if not isinstance(methods, list) or not all(isinstance(x, str) for x in methods):
        raise TargetProfileError("observation.capabilities.methods must be an array of strings")
    return set(methods)


def plan(observation: dict[str, Any], desired: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    d = discover(observation, registry)
    desired = required_mapping(desired, "desired")
    app = required_mapping(observation.get("app", {}), "observation.app")
    ownership = required_mapping(observation.get("ownership", {}), "observation.ownership")

    required_methods = desired.get(
        "required_methods", ["app.query", "app.create", "app.update", "app.redeploy"]
    )
    if not isinstance(required_methods, list) or not all(isinstance(x, str) for x in required_methods):
        raise TargetProfileError("desired.required_methods must be an array of strings")
    missing_methods = sorted(set(required_methods) - _methods(observation))

    blockers: list[str] = []
    if not d["exact_version_match"]:
        blockers.append("exact target version/profile is not known")
    if not d.get("profile"):
        blockers.append("exact source/runtime compatibility profile is not materialized")
    if not d.get("profile_contract_match", False):
        capability_gaps = []
        if d.get("missing_bootstrap_probes"):
            capability_gaps.append(
                "bootstrap probes=" + ", ".join(d["missing_bootstrap_probes"])
            )
        if d.get("missing_profile_methods"):
            capability_gaps.append(
                "public methods=" + ", ".join(d["missing_profile_methods"])
            )
        blockers.append(
            "observed target capabilities do not satisfy exact profile: "
            + "; ".join(capability_gaps)
        )
    if not d["apply_qualified"]:
        blockers.append("target profile is not apply-qualified")
    if missing_methods:
        blockers.append("required public methods are not observed: " + ", ".join(missing_methods))

    state = str(ownership.get("state", "unknown"))
    if state not in {"absent", "owned", "foreign"}:
        blockers.append(f"unsupported ownership state: {state}")
    if state == "foreign":
        blockers.append("foreign/unowned target state cannot be adopted implicitly")

    desired_identity = str(desired.get("materialization_identity", ""))
    if not desired_identity:
        blockers.append("desired.materialization_identity is required")

    action = "BLOCKED"
    if not blockers:
        present = bool(app.get("present", False))
        observed_identity = str(app.get("materialization_identity", ""))
        if not present and state == "absent":
            action = "CREATE"
        elif present and state == "owned" and observed_identity == desired_identity:
            action = "NOOP"
        elif present and state == "owned":
            action = "UPDATE"
        else:
            blockers.append("observed app presence and ownership state are inconsistent")

    result = {
        "schema_version": 1,
        "status": "READY" if not blockers else "BLOCKED",
        "action": action,
        "target": d,
        "app_name": desired.get("app_name"),
        "materialization_identity": desired_identity or None,
        "observation_sha256": d.get("observation_sha256"),
        "profile_identity_sha256": d.get("profile_identity_sha256"),
        "discovery_sha256": d.get("discovery_sha256"),
        "missing_methods": missing_methods,
        "blockers": blockers,
        "preconditions": {
            "reobserve_exact_version_before_apply": True,
            "reobserve_profile_contract_before_apply": True,
            "reobserve_bootstrap_capability_probe_before_apply": True,
            "require_observation_sha256_match_before_apply": True,
            "require_profile_identity_sha256_match_before_apply": True,
            "reobserve_ownership_before_apply": True,
            "reobserve_required_methods_before_apply": True,
            "foreign_state_adoption_allowed": False,
        },
    }
    result["plan_sha256"] = canonical_sha256(result)
    return result


def verify(observation: dict[str, Any], desired: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    d = discover(observation, registry)
    desired = required_mapping(desired, "desired")
    app = required_mapping(observation.get("app", {}), "observation.app")
    ownership = required_mapping(observation.get("ownership", {}), "observation.ownership")

    failures: list[str] = []
    if not d["exact_version_match"]:
        failures.append("target version no longer matches an exact profile")
    if not d.get("profile_contract_match", False):
        failures.append("target capability fingerprint no longer satisfies the exact profile")
    if str(ownership.get("state", "")) != "owned":
        failures.append("target app is not observed as Foundry-owned")
    if not bool(app.get("present", False)):
        failures.append("target app is absent")
    if str(app.get("materialization_identity", "")) != str(desired.get("materialization_identity", "")):
        failures.append("materialization identity mismatch")
    expected_state = str(desired.get("expected_state", "RUNNING"))
    if str(app.get("state", "")) != expected_state:
        failures.append(f"app state is not {expected_state}")
    min_workloads = int(desired.get("min_active_workloads", 1))
    if int(app.get("active_workloads", 0) or 0) < min_workloads:
        failures.append("active workload count below desired minimum")

    result = {
        "schema_version": 1,
        "status": "VERIFIED" if not failures else "VERIFY_FAILED",
        "target": d,
        "app_name": desired.get("app_name"),
        "observation_sha256": d.get("observation_sha256"),
        "profile_identity_sha256": d.get("profile_identity_sha256"),
        "discovery_sha256": d.get("discovery_sha256"),
        "failures": failures,
    }
    result["verification_sha256"] = canonical_sha256(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["discover", "plan", "verify"])
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(".foundry/truenas-target-tracks.json"),
    )
    parser.add_argument("--desired", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    try:
        observation = required_mapping(load_json(args.observation), "observation")
        registry = load_registry(args.registry)
        if args.command == "discover":
            result = discover(observation, registry)
        else:
            if not args.desired:
                raise TargetProfileError(f"--desired is required for {args.command}")
            desired = required_mapping(load_json(args.desired), "desired")
            result = plan(observation, desired, registry) if args.command == "plan" else verify(
                observation, desired, registry
            )
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0 if result.get("status") not in {"BLOCKED", "VERIFY_FAILED"} else 2
    except (TargetProfileError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
