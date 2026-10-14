"""Integrated offline read path: real Foundry bootstrap, other sources as adversarial fixtures.

The official and external entries in this test are intentionally synthetic
collisions, NOT verified catalogs or genuine source-tree artifacts. This test
proves only cross-provider query semantics and reuse of the canonical Foundry
inventory. No networking, image trust, installation, or target qualification.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


federation = load("foundry_catalog_federation", TOOL / "foundry_catalog_federation.py")
bridge = load("foundry_catalog_inventory_export", TOOL / "foundry_catalog_inventory_export.py")


def real_foundry_source():
    seed = json.loads((ROOT / ".foundry/bootstrap/foundry-rdte-probe.json").read_text())
    targets = json.loads((ROOT / ".foundry/truenas-target-tracks.json").read_text())
    empty = {"schema": bridge.inventory.INVENTORY_SCHEMA, "apps": []}
    receipt, inventory = bridge.inventory.bootstrap_candidate(
        empty, targets, seed, ROOT / "fixtures/foundry-rdte-probe"
    )
    assert receipt["mutation_performed"] is False
    source = seed["entry"]["source"]
    result = bridge.project(
        inventory,
        repository=source["repository"],
        revision=source["ref"],
        publisher="github.com",
        source_id="sempersupra-truenas-app-foundry",
    )
    return result, receipt


def fixture_source(source_id, uri, revision, source_digest):
    return {
        "schema": federation.SCHEMA,
        "publisher": "github.com",
        "source": source_id,
        "uri": uri,
        "revision": revision,
        "apps": [{
            # An intentionally adversarial same-name collision on all sources.
            "train": "community",
            "name": "foundry-rdte-probe",
            "version": "1.0.0",
            "path": "ix-dev/community/foundry-rdte-probe",
            "source_tree_sha256": source_digest,
        }],
    }


class ReadPathIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        foundry, receipt = real_foundry_source()
        official_pin = json.loads((ROOT / ".foundry/truenas-apps-upstream.json").read_text())
        cls.official_fixture = fixture_source(
            "truenas-apps", official_pin["repository"], official_pin["ref"],
            "sha256:" + "a" * 64
        )
        cls.external_fixture = fixture_source(
            "community-lab", "https://github.com/example/community-lab.git",
            "b" * 40, "sha256:" + "c" * 64
        )
        cls.foundry = foundry
        cls.receipt = receipt
        cls.rows = federation.federate([cls.official_fixture, foundry, cls.external_fixture])

    def test_real_foundry_bootstrap_is_read_only(self):
        self.assertEqual(self.receipt["status"], "READY_FOR_GIT_REVIEW")
        self.assertFalse(self.receipt["mutation_performed"])
        self.assertFalse(self.receipt["catalog_ready"])
        self.assertEqual(self.foundry["apps"][0]["name"], "foundry-rdte-probe")
        self.assertTrue(self.foundry["apps"][0]["source_tree_sha256"].startswith("sha256:"))

    def test_three_sources_stay_separate_despite_same_name_and_version(self):
        result = federation.query(self.rows, "list")
        self.assertEqual(result["count"], 3)
        self.assertEqual(len({r["provider_id"] for r in result["apps"]}), 3)
        self.assertEqual(len({r["package_id"] for r in result["apps"]}), 3)
        self.assertTrue(all(r["admission"] == "DISCOVERED_ONLY" for r in result["apps"]))

    def test_exact_source_retrieval_never_crosses_catalog_boundary(self):
        for row in self.rows:
            shown = federation.query(self.rows, "show", package_id=row["package_id"])
            self.assertEqual(shown["count"], 1)
            resolved = federation.query(
                self.rows, "resolve", package_id=row["package_id"],
                version=row["version"], revision=row["source_revision"],
                digest=row["source_tree_sha256"]
            )
            self.assertEqual(resolved["app"], row)
            self.assertFalse(resolved["mutation_eligible"])

    def test_source_withdrawal_removes_discovery_only(self):
        without_external = federation.federate([
            self.official_fixture, self.foundry
        ])
        self.assertEqual(len(without_external), 2)
        self.assertEqual(self.receipt["mutation_performed"], False)

    def test_provider_collision_never_overwrites_existing_origin(self):
        conflict = json.loads(json.dumps(self.external_fixture))
        conflict["uri"] = "https://github.com/example/attacker.git"
        with self.assertRaises(federation.CatalogIdentityError):
            federation.federate([
                self.official_fixture, self.foundry, self.external_fixture, conflict
            ])

    def test_does_not_imply_real_official_or_external_qualification(self):
        self.assertNotEqual(
            self.official_fixture["apps"][0]["source_tree_sha256"],
            self.foundry["apps"][0]["source_tree_sha256"]
        )
        self.assertEqual(federation.query(self.rows, "resolve",
            package_id="github.com/truenas-apps/community/foundry-rdte-probe",
            version="1.0.0",
            revision=self.official_fixture["revision"],
            digest=self.official_fixture["apps"][0]["source_tree_sha256"]
        )["mutation_eligible"], False)


if __name__ == "__main__":
    unittest.main()
