#!/usr/bin/env python3
"""Closed workload identity envelope for Foundry's future native adapters.

Offline validation and identity only. No host API, native payload generation,
credentials, paths, execution admission, or new lifecycle planner. The current
Apps v2 planner remains the authority for App operations.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "foundry-workload-artifact/v1"
ADAPTERS = {
    "foundry-custom": ("app", "truenas", {"compose-oci"}),
    "official-catalog": ("app", "truenas", {"catalog-oci"}),
    "truenas-legacy-container": ("system-container", "truenas", {"system-image"}),
    "truenas-native-container": ("system-container", "truenas", {"system-image"}),
    "truenas-native-vm": ("vm", "truenas", {"raw", "qcow2"}),
    "hyperv-vm": ("vm", "hyperv", {"vhdx"}),
}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
IDENTITY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}")


class WorkloadContractError(ValueError):
    pass


def closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise WorkloadContractError(f"{label} must contain exactly its required fields")
    return value


def identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise WorkloadContractError(f"{label} must be an opaque bounded identifier")
    return value


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise WorkloadContractError(f"{label} must be a lowercase SHA-256 identity")
    return value


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def inspect_artifact(value: Any) -> dict[str, Any]:
    doc = closed(value, {"schema", "product_id", "kind", "build_sha256",
                         "target", "artifact", "data"}, "artifact envelope")
    if doc["schema"] != SCHEMA:
        raise WorkloadContractError("unsupported artifact envelope schema")
    product = identifier(doc["product_id"], "product")
    kind = identifier(doc["kind"], "kind")
    build = digest(doc["build_sha256"], "common build")
    target = closed(doc["target"], {"adapter", "platform", "version",
                                     "profile_sha256"}, "target")
    adapter = identifier(target["adapter"], "adapter")
    spec = ADAPTERS.get(adapter)
    if spec is None:
        raise WorkloadContractError("unsupported adapter family")
    expected_kind, expected_platform, formats = spec
    if kind != expected_kind or target["platform"] != expected_platform:
        raise WorkloadContractError("adapter, resource kind and platform disagree")
    version = identifier(target["version"], "target version")
    if version.lower() in {"latest", "current", "stable", "unknown", "unobserved"}:
        raise WorkloadContractError("exact target version is required")
    digest(target["profile_sha256"], "target profile")
    artifact = closed(doc["artifact"], {"format", "sha256"}, "target artifact")
    fmt = identifier(artifact["format"], "artifact format")
    if fmt not in formats:
        raise WorkloadContractError("artifact format incompatible with adapter")
    digest(artifact["sha256"], "target artifact")
    data = closed(doc["data"], {"policy", "contract_sha256"}, "data")
    if data["policy"] != "retain-data":
        raise WorkloadContractError("workload ownership cannot authorize data deletion")
    digest(data["contract_sha256"], "retained-data contract")
    # Product identity survives platform-specific materialization. It is not a
    # resource ownership assertion and does not identify a live machine.
    build_identity = canonical_digest({
        "product_id": product, "kind": kind, "build_sha256": build,
        "data_contract_sha256": data["contract_sha256"],
    })
    return {
        "schema": "foundry-workload-artifact-inspection/v1",
        "status": "IDENTITY_ONLY",
        "kind": kind,
        "adapter": adapter,
        "build_identity": build_identity,
        "materialization_identity": canonical_digest(doc),
        "lifecycle_handoff": (
            "existing-app-v2-contract" if kind == "app"
            else "native-adapter-qualification-required"
        ),
        "apply_authorized": False,
        "runtime_qualified": False,
        "ownership_verified": False,
        "storage_delete_authorized": False,
    }


def load_artifact(raw: bytes) -> dict[str, Any]:
    if not isinstance(raw, bytes) or len(raw) > 65536:
        raise WorkloadContractError("artifact envelope exceeds bounded byte budget")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise WorkloadContractError("duplicate artifact field")
            out[key] = value
        return out

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise WorkloadContractError("invalid artifact JSON") from exc
    return inspect_artifact(value)
