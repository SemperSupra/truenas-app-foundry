#!/usr/bin/env python3
"""One read-only, source-derived proof across official, Foundry, external catalogs.

No network fetches, app install, privileges, target mutations, or signatures.
Inputs must already be independently SHA-pinned and checked out. The Foundry
probe's local source preflight does NOT independently prove its historical Git
ref at this step; runtime/authority qualification is explicitly absent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import foundry_catalog_official_adapter as official
import foundry_catalog_external_adapter as external
import foundry_catalog_inventory_export as bridge
import foundry_catalog_federation as federation

ROOT = Path(__file__).resolve().parents[1]


def prove(official_checkout: Path, external_checkout: Path, registration: dict):
    pin = json.loads((ROOT / ".foundry/truenas-apps-upstream.json").read_text())
    native = official.project(pin, official_checkout, ["jellyfin"])
    outsider = external.project(registration, external_checkout)

    seed = json.loads((ROOT / ".foundry/bootstrap/foundry-rdte-probe.json").read_text())
    targets = json.loads((ROOT / ".foundry/truenas-target-tracks.json").read_text())
    empty = {"schema": bridge.inventory.INVENTORY_SCHEMA, "apps": []}
    receipt, proposed = bridge.inventory.bootstrap_candidate(
        empty, targets, seed, ROOT / "fixtures/foundry-rdte-probe"
    )
    source = seed["entry"]["source"]
    foundry = bridge.project(
        proposed, repository=source["repository"], revision=source["ref"],
        publisher="github.com", source_id="sempersupra-truenas-app-foundry"
    )
    indexes = [native, outsider, foundry]
    rows = federation.federate(indexes)
    assert len(rows) == 3, "expected 3 independently sourced app entries"
    assert len({x["provider_id"] for x in rows}) == 3
    assert len({x["package_id"] for x in rows}) == 3
    jellyfin = [row for row in rows if row["package_id"].endswith("/jellyfin")]
    assert len(jellyfin) == 2, "official and external same-name Jellyfin must remain separate"
    assert len({x["provider_id"] for x in jellyfin}) == 2
    assert len({x["source_tree_sha256"] for x in jellyfin}) == 2
    assert receipt["mutation_performed"] is False
    queried = federation.query(rows, "list")
    assert queried["count"] == len(rows)
    for row in rows:
        show = federation.query(rows, "show", package_id=row["package_id"])
        assert show["count"] == 1
        resolve = federation.query(
            rows, "resolve", package_id=row["package_id"],
            version=row["version"], revision=row["source_revision"],
            digest=row["source_tree_sha256"]
        )
        assert resolve["app"] == row
        assert resolve["mutation_eligible"] is False
        assert row["admission"] == "DISCOVERED_ONLY"
    return {
        "schema": "truenas-foundry-catalog-three-source-proof/v0",
        "status": "PASS", "target_mutation_performed": False,
        "official_catalog_real_source": True,
        "external_catalog_real_source": True,
        "foundry_probe_local_structural_preflight": True,
        "provider_count": len({r["provider_id"] for r in rows}),
        "source_count": len(rows), "same_name_jellyfin_variants": len(jellyfin),
        "apps": rows,
        "limitations": [
            "No TrueNAS middleware, native catalog, Docker or runtime tested",
            "No independent historical Git-ref re-verification for local Foundry probe fixture",
            "External source is a pinned archived community fork, discovery-only",
            "No signing or app install privilege; source validation is not trust admission",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-checkout", required=True, type=Path)
    parser.add_argument("--external-checkout", required=True, type=Path)
    parser.add_argument("--registration", required=True, type=Path)
    args = parser.parse_args()
    reg = json.loads(args.registration.read_text())
    print(json.dumps(prove(args.official_checkout, args.external_checkout, reg),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
