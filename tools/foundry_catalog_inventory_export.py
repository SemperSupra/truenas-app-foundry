#!/usr/bin/env python3
"""Export a pinned read-only Foundry inventory projection for Catalog federation.

Consumes the existing Git-backed Foundry inventory validator; never creates a
second inventory, app, ownership record or target-apply authority.
The result is a *discovery index*, not a deployment/artifact permission.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import foundry_app_inventory as inventory

SCHEMA = "truenas-foundry-catalog-source/v0"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_EXPORTED_APPS = 4096


class ExportError(ValueError):
    pass


def project(
    inventory_doc: dict[str, Any], *,
    repository: str, revision: str, publisher: str, source_id: str
) -> dict[str, Any]:
    """Select an exact source snapshot via canonical inventory, fail closed on drift."""
    if not isinstance(repository, str) or not repository.startswith("https://"):
        raise ExportError("repository must be an HTTPS source URI")
    if not isinstance(revision, str) or not SHA40.fullmatch(revision):
        raise ExportError("revision must be a full immutable lowercase Git SHA")
    # The canonical inventory tool is the sole validator and source of app records.
    records = inventory.validate_inventory(inventory_doc)
    selected: list[dict[str, Any]] = []
    for entry in records:
        origin = entry["source"]
        if origin["repository"] != repository or origin["ref"] != revision:
            continue
        if origin["kind"] != "foundry-repository":
            raise ExportError("selected source kind is not Foundry-owned")
        contract = entry.get("source_contract")
        if not isinstance(contract, dict) or contract.get("structural_preflight") != "PASS":
            raise ExportError(f"{entry['id']} lacks accepted structural source identity")
        source_tree = contract.get("source_tree_sha256")
        if not isinstance(source_tree, str) or not SHA256.fullmatch(source_tree):
            raise ExportError(f"{entry['id']} lacks exact source-tree SHA-256")
        if entry.get("catalog_train") not in {"test", "community", "stable", "enterprise"}:
            raise ExportError(f"{entry['id']} lacks a supported catalog train")
        selected.append({
            "train": entry["catalog_train"],
            "name": entry["id"],
            "version": entry["version"],
            "path": origin["path"],
            "source_tree_sha256": source_tree,
        })
    if not selected:
        raise ExportError("no pinned Foundry entries matched the selected source/revision")
    if len(selected) > MAX_EXPORTED_APPS:
        raise ExportError("too many selected Foundry entries")
    return {
        "schema": SCHEMA,
        "publisher": publisher,
        "source": source_id,
        "uri": repository,
        "revision": revision,
        "apps": sorted(selected, key=lambda row: (row["train"], row["name"], row["version"])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args(argv)
    try:
        with args.inventory.open("rb") as handle:
            raw = handle.read(MAX_INDEX_BYTES + 1)
        if len(raw) > MAX_INDEX_BYTES:
            raise ExportError("inventory exceeds size limit")
        record = json.loads(raw.decode("utf-8"))
        projected = project(record, repository=args.repository, revision=args.revision,
                            publisher=args.publisher, source_id=args.source_id)
        print(json.dumps(projected, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError,
            inventory.InventoryError, ExportError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
