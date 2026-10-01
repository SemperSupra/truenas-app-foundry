#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "foundry_inventory_materialize",
    HERE / "foundry_inventory_materialize.py",
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


def inventory():
    return {
        "schema": "truenas-foundry-app-inventory/v1",
        "apps": [
            {
                "id": "probe-app",
                "version": "1.0.0",
                "source": {
                    "kind": "foundry-repository",
                    "repository": "https://github.com/example/probe-app.git",
                    "ref": "a" * 40,
                    "path": "truenas",
                },
                "catalog_train": "community",
                "target_versions": ["25.10.7"],
                "catalog_export": {"status": "not-assessed"},
                "source_contract": {
                    "catalog_source_shape": "truenas-apps-ix-dev/v1",
                    "structural_preflight": "PASS",
                    "source_tree_sha256": "sha256:" + "b" * 64,
                    "official_validator": "PENDING",
                },
            }
        ],
    }


def targets():
    return {
        "schema_version": 1,
        "targets": [
            {
                "version": "25.10.7",
                "channel": "stable",
                "profile": ".foundry/truenas-compatibility/25.10.7-materialization.json",
                "source_qualification": "source-contract-qualified",
                "runtime_qualification": "public-gha-rdte-t5-accepted",
                "accepted_runtime_rung": "T5",
                "apply_qualified": False,
            }
        ],
    }


def compose():
    return {
        "services": {
            "probe": {
                "image": "example/probe@sha256:" + "c" * 64,
                "restart": "unless-stopped",
            }
        }
    }


class MaterializeTests(unittest.TestCase):
    def test_binds_inventory_source_and_exact_target_into_artifact(self):
        artifact, receipt = MOD.materialize(
            inventory(),
            targets(),
            compose(),
            app_id="probe-app",
            version="1.0.0",
            target_version="25.10.7",
        )
        self.assertEqual(artifact["app_name"], "probe-app")
        self.assertEqual(
            artifact["provenance"]["source_tree_sha256"],
            "sha256:" + "b" * 64,
        )
        self.assertEqual(
            artifact["provenance"]["target_profile"],
            ".foundry/truenas-compatibility/25.10.7-materialization.json",
        )
        self.assertEqual(receipt["catalog_validator"], "PENDING")
        self.assertFalse(receipt["mutation_eligible"])
        self.assertEqual(
            receipt["artifact_sha256"],
            artifact["artifact_sha256"],
        )

    def test_materialization_is_deterministic(self):
        args = dict(
            inventory_doc=inventory(),
            target_doc=targets(),
            compose=compose(),
            app_id="probe-app",
            version="1.0.0",
            target_version="25.10.7",
        )
        a1, r1 = MOD.materialize(**args)
        a2, r2 = MOD.materialize(**args)
        self.assertEqual(a1, a2)
        self.assertEqual(r1, r2)

    def test_rejects_missing_source_contract(self):
        inv = inventory()
        inv["apps"][0].pop("source_contract")
        with self.assertRaises(MOD.MaterializeError):
            MOD.materialize(
                inv,
                targets(),
                compose(),
                app_id="probe-app",
                version="1.0.0",
                target_version="25.10.7",
            )

    def test_rejects_unregistered_target(self):
        with self.assertRaises(MOD.inventory_mod.InventoryError):
            MOD.materialize(
                inventory(),
                targets(),
                compose(),
                app_id="probe-app",
                version="1.0.0",
                target_version="27.0.0",
            )

    def test_runtime_name_can_be_bound_separately(self):
        inv = inventory()
        inv["apps"][0]["runtime_app_name"] = "probe-runtime"
        artifact, _ = MOD.materialize(
            inv,
            targets(),
            compose(),
            app_id="probe-app",
            version="1.0.0",
            target_version="25.10.7",
        )
        self.assertEqual(artifact["app_name"], "probe-runtime")


if __name__ == "__main__":
    unittest.main()
