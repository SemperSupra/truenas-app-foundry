"""Offline Foundry runtime/state separation and replacement-evidence contract.

This module does not apply a lifecycle action, grant ownership or validate live
storage. Its output is a bounded consistency check for the existing lifecycle
engine. Physical independence, backup and restore are independent oracles.
"""
from __future__ import annotations

import re
from typing import Any

from tools.foundry_workload_artifact import (
    WorkloadContractError, canonical_digest, closed, digest, inspect_artifact,
)

SCHEMA = "foundry-retained-state-contract/v1"
SLOT = re.compile(r"[a-z][a-z0-9_-]{0,63}")
ROLES = {"user-files", "user-config", "application-state", "service-identity"}
PHASES = ("OBSERVE_DISCOVER", "PLAN", "APPLY", "VERIFY")


def slot_name(value: Any) -> str:
    if not isinstance(value, str) or not SLOT.fullmatch(value):
        raise WorkloadContractError("invalid logical retained-state slot")
    return value


def state_contract(value: Any) -> dict[str, Any]:
    doc = closed(value, {"schema", "runtime", "scratch_policy", "secret_policy",
                         "configuration_recipe_sha256", "retained"}, "state contract")
    if doc["schema"] != SCHEMA:
        raise WorkloadContractError("unsupported state contract")
    rt = closed(doc["runtime"], {"policy", "rebuild_recipe_sha256"}, "runtime")
    if rt["policy"] != "disposable":
        raise WorkloadContractError("runtime must be replaceable")
    digest(rt["rebuild_recipe_sha256"], "rebuild recipe")
    digest(doc["configuration_recipe_sha256"], "configuration recipe")
    if doc["scratch_policy"] != "disposable":
        raise WorkloadContractError("scratch must not be durable user state")
    if doc["secret_policy"] != "external-references-only":
        raise WorkloadContractError("secret contents cannot enter the runtime artifact")
    slots = doc["retained"]
    if not isinstance(slots, list) or len(slots) > 64:
        raise WorkloadContractError("explicit bounded retained-state slots required")
    seen = set()
    for entry in slots:
        row = closed(entry, {"slot", "role", "ownership", "retention", "schema_sha256"},
                     "retained-state slot")
        name = slot_name(row["slot"])
        if name in seen:
            raise WorkloadContractError("duplicate retained-state slot")
        seen.add(name)
        if not isinstance(row["role"], str) or row["role"] not in ROLES:
            raise WorkloadContractError("unsupported retained-state role")
        if row["ownership"] != "independent" or row["retention"] != "retain-data":
            raise WorkloadContractError("retained state must outlive runtime")
        digest(row["schema_sha256"], "state schema")
    # Logical slots are a set; input order is not materialization identity.
    return {**doc, "retained": sorted(slots, key=lambda x: x["slot"])}


def inspect_layout(artifact: Any, layout: Any) -> dict[str, Any]:
    info = inspect_artifact(artifact)
    normalized = state_contract(layout)
    identity = canonical_digest(normalized)
    if artifact["data"]["contract_sha256"] != identity:
        raise WorkloadContractError("artifact is not bound to this retained-state contract")
    return {"schema": "foundry-runtime-layout-inspection/v1",
            "status": "SOURCE_CONSISTENT_ONLY", "contract_sha256": identity,
            "materialization_identity": info["materialization_identity"],
            "required_phases": list(PHASES),
            "declared_retained_slots": len(normalized["retained"]),
            "reproducibility_verified": False, "reversibility_verified": False,
            "physical_separation_verified": False, "apply_authorized": False,
            "storage_delete_authorized": False}


def observation(value: Any, slots: set[str]) -> dict[str, Any]:
    obj = closed(value, {"materialization_identity", "runtime_storage_sha256",
                         "state", "bindings"}, "replacement observation")
    digest(obj["materialization_identity"], "observed materialization")
    runtime = digest(obj["runtime_storage_sha256"], "runtime storage identity")
    if obj["state"] != "stable":
        raise WorkloadContractError("ambiguous or nonterminal observation must reconcile")
    bindings = obj["bindings"]
    if not isinstance(bindings, list) or len(bindings) != len(slots):
        raise WorkloadContractError("retained binding count mismatch")
    found = {}
    used = {runtime}
    for item in bindings:
        row = closed(item, {"slot", "storage_sha256", "checkpoint_sha256"},
                     "retained binding")
        name = slot_name(row["slot"])
        key = digest(row["storage_sha256"], "retained storage identity")
        digest(row["checkpoint_sha256"], "controlled state sentinel")
        if name in found or key in used:
            raise WorkloadContractError("duplicate or runtime-aliased retained binding")
        used.add(key)
        found[name] = row
    if set(found) != slots:
        raise WorkloadContractError("retained slot coverage mismatch")
    return {**obj, "bindings": [found[k] for k in sorted(found)]}


def inspect_replacement(previous_artifact: Any, desired_artifact: Any, layout: Any,
                        before: Any, after: Any, recovery: Any) -> dict[str, Any]:
    """Compare *supplied* synthetic/controlled observations, not live attestations.

    Same-layout replacement only. A schema migration is a separate qualified
    operation. No real backup, state ownership or runtime identity is established
    by caller-provided hashes. Checkpoints refer to quiesced controlled sentinels,
    not arbitrary whole-dataset hashes during normal operation.
    """
    prev = inspect_layout(previous_artifact, layout)
    desired = inspect_layout(desired_artifact, layout)
    if previous_artifact["product_id"] != desired_artifact["product_id"]:
        raise WorkloadContractError("replacement cannot change product identity")
    if previous_artifact["kind"] != desired_artifact["kind"]:
        raise WorkloadContractError("replacement cannot change resource kind")
    if previous_artifact["target"] != desired_artifact["target"]:
        raise WorkloadContractError("cross-target migration needs separate qualification")
    slots = {x["slot"] for x in state_contract(layout)["retained"]}
    pre = observation(before, slots)
    post = observation(after, slots)
    if pre["materialization_identity"] != prev["materialization_identity"]:
        raise WorkloadContractError("previous artifact identity mismatch")
    if post["materialization_identity"] != desired["materialization_identity"]:
        raise WorkloadContractError("desired artifact identity mismatch")
    if pre["bindings"] != post["bindings"]:
        raise WorkloadContractError("retained binding or checkpoint drift")
    runtime_changed = pre["runtime_storage_sha256"] != post["runtime_storage_sha256"]
    if not runtime_changed and prev["materialization_identity"] != desired["materialization_identity"]:
        raise WorkloadContractError("new artifact cannot be claimed without runtime replacement evidence")
    rec = closed(recovery, {"previous_artifact_sha256", "backup_receipt_sha256",
                            "restore_receipt_sha256", "state_contract_sha256"},
                 "recovery evidence references")
    for key, value in rec.items():
        digest(value, key)
    if rec["previous_artifact_sha256"] != prev["materialization_identity"]:
        raise WorkloadContractError("recovery reference does not identify previous artifact")
    if rec["state_contract_sha256"] != desired["contract_sha256"]:
        raise WorkloadContractError("recovery reference is for a different state contract")
    result = {"schema": "foundry-replacement-inspection/v1",
              "status": "CONSISTENT_REFERENCES_ONLY", "runtime_changed": runtime_changed,
              "retained_slots_unchanged": len(slots),
              "desired_materialization_identity": desired["materialization_identity"],
              "evidence_sha256": canonical_digest({"before": pre, "after": post, "recovery": rec}),
              "required_phases": list(PHASES), "live_state_verified": False,
              "recovery_verified": False, "apply_authorized": False,
              "storage_delete_authorized": False}
    return result
