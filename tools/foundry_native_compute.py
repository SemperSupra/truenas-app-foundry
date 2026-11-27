"""Offline exact-family source contract inspection. No native calls or plans."""
from __future__ import annotations

from typing import Any

from tools.foundry_workload_artifact import WorkloadContractError, canonical_digest

VERSION = "25.10.7"
FAMILIES = {
    "truenas-native-vm": ("vm", {"vm.query", "vm.device.nic_attach_choices"}),
    "truenas-legacy-container": ("system-container", {"virt.instance.query", "virt.global.bridge_choices"}),
}
OPS = {"ENSURE_RUNNING", "ENSURE_STOPPED", "RESTART", "ENSURE_ABSENT"}


def inspect_native(profile: dict[str, Any], *, adapter: str, version: str,
                   observed_methods: list[str], operation: str) -> dict[str, Any]:
    """Report only source-contract compatibility, never permission or a call payload."""
    if type(profile) is not dict or profile.get("schema") != "foundry-native-compute-source-contract/v1":
        raise WorkloadContractError("invalid native source contract")
    if not isinstance(adapter, str) or not isinstance(operation, str):
        raise WorkloadContractError("invalid adapter or operation")
    if not isinstance(observed_methods, list) or not all(isinstance(x, str) and x for x in observed_methods):
        raise WorkloadContractError("explicit observed methods required")
    blockers = []
    if version != VERSION or profile.get("version") != VERSION:
        blockers.append("EXACT_VERSION_UNSUPPORTED")
    if adapter not in FAMILIES:
        blockers.append("ADAPTER_UNSUPPORTED")
    if operation not in OPS:
        blockers.append("OPERATION_UNSUPPORTED")
    family = profile.get("profiles", {}).get(adapter, {})
    if adapter in FAMILIES:
        kind, expected_discovery = FAMILIES[adapter]
        if family.get("kind") != kind or set(family.get("discovery", [])) != expected_discovery:
            blockers.append("SOURCE_FAMILY_MISMATCH")
        if not expected_discovery.issubset(observed_methods):
            blockers.append("DISCOVERY_METHOD_MISSING")
    method = family.get("operations", {}).get(operation)
    expected_prefix = ("vm." if adapter == "truenas-native-vm"
                       else "virt.instance." if adapter == "truenas-legacy-container" else "")
    verb = {"ENSURE_RUNNING":"start", "ENSURE_STOPPED":"stop",
            "RESTART":"restart", "ENSURE_ABSENT":"delete"}.get(operation)
    if adapter == "truenas-legacy-container" and operation == "ENSURE_ABSENT":
        blockers.append("RETAIN_DATA_DELETE_NOT_QUALIFIED")
    elif not expected_prefix or not verb or method != expected_prefix + verb:
        blockers.append("OPERATION_SOURCE_MAPPING_UNSUPPORTED")
    elif method not in observed_methods:
        blockers.append("OPERATION_METHOD_MISSING")
    if profile.get("qualification") != "SOURCE_ONLY" or profile.get("apply_authorized") is not False or profile.get("runtime_qualified") is not False:
        blockers.append("SOURCE_CONTRACT_AUTHORITY_INVALID")
    return {"schema":"foundry-native-compute-inspection/v1",
            "status":"BLOCKED" if blockers else "SOURCE_COMPATIBLE_ONLY",
            "blockers":blockers, "profile_sha256":canonical_digest(profile),
            "apply_authorized":False, "runtime_qualified":False,
            "ownership_verified":False, "storage_delete_authorized":False}
