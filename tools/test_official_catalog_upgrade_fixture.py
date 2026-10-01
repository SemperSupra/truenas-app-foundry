#!/usr/bin/env python3
import copy
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "official_catalog_upgrade_fixture",
    HERE / "official_catalog_upgrade_fixture.py",
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)

FIXTURE = MOD.load(
    HERE.parent / ".foundry" / "official-catalog-upgrade-fixture.json",
    "fixture",
)
REGISTRY = MOD.load(
    HERE.parent / ".foundry" / "truenas-target-tracks.json",
    "target registry",
)


class OfficialCatalogUpgradeFixtureTests(unittest.TestCase):
    def test_current_fixture_is_source_valid_but_runtime_pending(self):
        result = MOD.validate(copy.deepcopy(FIXTURE), copy.deepcopy(REGISTRY))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["from_catalog_version"], "1.1.20")
        self.assertEqual(result["to_catalog_version"], "1.1.21")
        self.assertEqual(result["runtime_qualified_targets"], [])
        self.assertEqual(
            result["source_bound_targets"],
            ["25.04.1", "25.04.2.6", "25.10.7"],
        )
        self.assertIn("26.0.0-BETA.3", result["adapter_gaps"])
        self.assertFalse(result["executed_upgrade_qualified"])

    def test_catalog_version_must_strictly_increase(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["to"]["catalog_version"] = fixture["from"]["catalog_version"]
        with self.assertRaisesRegex(MOD.FixtureError, "strictly increase"):
            MOD.validate(fixture, copy.deepcopy(REGISTRY))

    def test_same_lineage_identity_is_required(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["to"]["app_version"] = "v9.9.9"
        with self.assertRaisesRegex(MOD.FixtureError, "app_version differs"):
            MOD.validate(fixture, copy.deepcopy(REGISTRY))

    def test_matrix_growth_invalidates_stale_upgrade_fixture(self):
        registry = copy.deepcopy(REGISTRY)
        registry["targets"].append({"version": "26.0.0-RC.1"})
        with self.assertRaisesRegex(MOD.FixtureError, "exactly match target registry"):
            MOD.validate(copy.deepcopy(FIXTURE), registry)

    def test_universal_upgrade_claim_requires_all_runtime_rows(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["executed_upgrade_qualified"] = True
        with self.assertRaisesRegex(MOD.FixtureError, "exactly reflect"):
            MOD.validate(fixture, copy.deepcopy(REGISTRY))

    def test_gap_adapter_cannot_receive_runtime_qualification(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["runtime_qualified_targets"] = ["26.0.0-BETA.3"]
        with self.assertRaisesRegex(MOD.FixtureError, "GAP adapters"):
            MOD.validate(fixture, copy.deepcopy(REGISTRY))

    def test_runtime_adapters_must_cover_matrix(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["runtime_adapters"].pop("25.10.7")
        with self.assertRaisesRegex(MOD.FixtureError, "exactly cover"):
            MOD.validate(fixture, copy.deepcopy(REGISTRY))

    def test_custom_app_fallback_remains_forbidden(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["policy"]["custom_app_fallback_allowed"] = True
        with self.assertRaisesRegex(MOD.FixtureError, "Custom App fallback"):
            MOD.validate(fixture, copy.deepcopy(REGISTRY))


if __name__ == "__main__":
    unittest.main()
