#!/usr/bin/env python3
"""Bind a Foundry inventory identity to an immutable TrueNAS deployment artifact."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_sibling(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


inventory_mod = load_sibling("foundry_app_inventory", "foundry_app_inventory.py")
artifact_mod = load_sibling(
    "package_truenas_deployment_artifact",
    "package_truenas_deployment_artifact.py",
)


class MaterializeError(RuntimeError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializeError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise MaterializeError(f"{label} must be an object")
    return value


def canonical_sha256(value: Any) -> str:
    return artifact_mod.canonical_sha256(value)


def materialize(
    inventory_doc: dict[str, Any],
    target_doc: dict[str, Any],
    compose: dict[str, Any],
    *,
    app_id: str,
    version: str,
    target_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entries = inventory_mod.validate_inventory(inventory_doc)
    targets = inventory_mod.load_target_map(target_doc)
    entry = inventory_mod.find_entry(entries, app_id, version)
    resolution = inventory_mod.resolve_entry(
        entries, targets, app_id, version, target_version
    )

    source_contract = entry.get("source_contract")
    if not isinstance(source_contract, dict):
        raise MaterializeError("inventory entry has no bootstrap source contract")
    if source_contract.get("structural_preflight") != "PASS":
        raise MaterializeError("inventory source structural preflight is not PASS")
    source_tree_sha = source_contract.get("source_tree_sha256")
    if not isinstance(source_tree_sha, str) or not source_tree_sha.startswith("sha256:"):
        raise MaterializeError("inventory source tree identity is missing")

    runtime_app_name = str(entry.get("runtime_app_name") or entry["id"])
    if len(runtime_app_name) > 40:
        raise MaterializeError(
            "runtime app name exceeds the TrueNAS App naming limit; "
            "set a shorter runtime_app_name in the inventory entry"
        )

    provenance = {
        "source": "foundry-inventory",
        "inventory_schema": inventory_doc.get("schema"),
        "inventory_entry_sha256": "sha256:" + canonical_sha256(entry),
        "app_id": entry["id"],
        "app_version": entry["version"],
        "runtime_app_name": runtime_app_name,
        "source_identity": entry["source"],
        "source_tree_sha256": source_tree_sha,
        "catalog_train": entry.get("catalog_train", "none"),
        "catalog_validator": source_contract.get("official_validator", "PENDING"),
        "target_version": target_version,
        "target_profile": resolution["target"].get("profile"),
        "target_apply_qualified": resolution["target"].get("apply_qualified", False),
    }

    try:
        artifact = artifact_mod.build_artifact(runtime_app_name, compose, provenance)
    except artifact_mod.ArtifactError as exc:
        raise MaterializeError(str(exc)) from exc

    receipt = {
        "schema": "truenas-foundry-inventory-materialization-receipt/v1",
        "status": "PASS",
        "app_id": entry["id"],
        "app_version": entry["version"],
        "runtime_app_name": runtime_app_name,
        "target_version": target_version,
        "source_tree_sha256": source_tree_sha,
        "inventory_entry_sha256": provenance["inventory_entry_sha256"],
        "materialization_identity": artifact["materialization_identity"],
        "artifact_sha256": artifact["artifact_sha256"],
        "catalog_validator": provenance["catalog_validator"],
        "mutation_eligible": bool(resolution["mutation_eligible"]),
        "non_claims": [
            "materialization does not authorize target mutation",
            "catalog readiness requires the separate native validation/render-install gates",
        ],
    }
    receipt["receipt_sha256"] = "sha256:" + canonical_sha256(receipt)
    return artifact, receipt


def write_json_0600(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--compose", type=Path, required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--artifact-out", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()

    try:
        inventory_doc = load_json(args.inventory, "inventory")
        target_doc = load_json(args.targets, "target registry")
        compose = load_json(args.compose, "normalized Compose")
        artifact, receipt = materialize(
            inventory_doc,
            target_doc,
            compose,
            app_id=args.app,
            version=args.version,
            target_version=args.target_version,
        )
        write_json_0600(args.artifact_out, artifact)
        write_json_0600(args.receipt_out, receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (MaterializeError, inventory_mod.InventoryError, OSError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
