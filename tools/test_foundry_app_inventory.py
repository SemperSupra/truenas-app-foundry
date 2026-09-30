#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "foundry_app_inventory",
    HERE / "foundry_app_inventory.py",
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


def sample_entry(app_id="probe-app", version="1.0.0", targets=None):
    return {
        "id": app_id,
        "version": version,
        "source": {
            "kind": "foundry-repository",
            "repository": "https://github.com/example/probe-app.git",
            "ref": "0123456789abcdef",
            "path": "truenas",
        },
        "catalog_train": "test",
        "target_versions": targets or ["25.10.7", "26.0.0-BETA.3"],
        "catalog_export": {"status": "candidate"},
    }


class InventoryTests(unittest.TestCase):
    def test_empty_repository_inventory_is_valid(self):
        apps = MOD.validate_inventory(
            {"schema": "truenas-foundry-app-inventory/v1", "apps": []}
        )
        self.assertEqual(apps, [])

    def test_rejects_duplicate_app_version(self):
        entry = sample_entry()
        with self.assertRaises(MOD.InventoryError):
            MOD.validate_inventory(
                {
                    "schema": "truenas-foundry-app-inventory/v1",
                    "apps": [entry, dict(entry)],
                }
            )

    def test_list_is_deterministic(self):
        entries = MOD.validate_inventory(
            {
                "schema": "truenas-foundry-app-inventory/v1",
                "apps": [
                    sample_entry("zeta", "2"),
                    sample_entry("alpha", "1"),
                ],
            }
        )
        result = MOD.list_entries(entries)
        self.assertEqual([x["id"] for x in result["apps"]], ["alpha", "zeta"])

    def test_show_requires_exact_identity(self):
        entries = MOD.validate_inventory(
            {"schema": "truenas-foundry-app-inventory/v1", "apps": [sample_entry()]}
        )
        result = MOD.show_entry(entries, "probe-app", "1.0.0")
        self.assertEqual(result["entry"]["source"]["kind"], "foundry-repository")
        with self.assertRaises(MOD.InventoryError):
            MOD.show_entry(entries, "probe-app", "latest")

    def test_resolve_joins_exact_target_without_granting_apply(self):
        entries = MOD.validate_inventory(
            {"schema": "truenas-foundry-app-inventory/v1", "apps": [sample_entry()]}
        )
        targets = MOD.load_target_map(
            {
                "schema_version": 1,
                "targets": [
                    {
                        "version": "26.0.0-BETA.3",
                        "channel": "early-release",
                        "profile": ".foundry/truenas-compatibility/26.0.0-BETA.3-materialization.json",
                        "source_qualification": "source-contract-qualified",
                        "runtime_qualification": "public-gha-rdte-t5-accepted",
                        "accepted_runtime_rung": "T5",
                        "apply_qualified": False,
                    }
                ],
            }
        )
        result = MOD.resolve_entry(
            entries, targets, "probe-app", "1.0.0", "26.0.0-BETA.3"
        )
        self.assertEqual(result["target"]["accepted_runtime_rung"], "T5")
        self.assertFalse(result["mutation_eligible"])

    def test_resolve_rejects_unregistered_or_disallowed_target(self):
        entries = MOD.validate_inventory(
            {
                "schema": "truenas-foundry-app-inventory/v1",
                "apps": [sample_entry(targets=["25.10.7"])],
            }
        )
        targets = MOD.load_target_map(
            {
                "schema_version": 1,
                "targets": [
                    {"version": "25.10.7", "apply_qualified": False},
                    {"version": "26.0.0-BETA.3", "apply_qualified": False},
                ],
            }
        )
        with self.assertRaises(MOD.InventoryError):
            MOD.resolve_entry(
                entries, targets, "probe-app", "1.0.0", "26.0.0-BETA.3"
            )
        with self.assertRaises(MOD.InventoryError):
            MOD.resolve_entry(entries, targets, "probe-app", "1.0.0", "27.0.0")


if __name__ == "__main__":
    unittest.main()
