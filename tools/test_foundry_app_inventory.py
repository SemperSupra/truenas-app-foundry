#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
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
        "catalog_train": "community",
        "target_versions": targets or ["25.10.7", "26.0.0-BETA.3"],
        "catalog_export": {"status": "not-assessed"},
    }


def target_doc():
    return {
        "schema_version": 1,
        "targets": [
            {"version": "25.10.7", "apply_qualified": False},
            {
                "version": "26.0.0-BETA.3",
                "channel": "early-release",
                "profile": ".foundry/truenas-compatibility/26.0.0-BETA.3-materialization.json",
                "source_qualification": "source-contract-qualified",
                "runtime_qualification": "public-gha-rdte-t6-accepted",
                "accepted_runtime_rung": "T6",
                "apply_qualified": False,
            },
        ],
    }


def write_source(root: pathlib.Path, *, app="probe-app", version="1.0.0", train="community"):
    files = {
        "README.md": "# Probe App\n",
        "app.yaml": (
            f"name: {app}\n"
            f"version: {version}\n"
            "app_version: 1.2.3\n"
            f"train: {train}\n"
            "lib_version: 2.3.11\n"
        ),
        "ix_values.yaml": "images:\n  image:\n    repository: example/probe\n    tag: 1.2.3\n",
        "questions.yaml": "groups: []\nquestions: []\n",
        "templates/docker-compose.yaml": "{{ {} | tojson }}\n",
        "templates/test_values/basic-values.yaml": "resources: {}\n",
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


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
        result = MOD.resolve_entry(
            entries,
            MOD.load_target_map(target_doc()),
            "probe-app",
            "1.0.0",
            "26.0.0-BETA.3",
        )
        self.assertEqual(result["target"]["accepted_runtime_rung"], "T6")
        self.assertFalse(result["mutation_eligible"])

    def test_resolve_rejects_unregistered_or_disallowed_target(self):
        entries = MOD.validate_inventory(
            {
                "schema": "truenas-foundry-app-inventory/v1",
                "apps": [sample_entry(targets=["25.10.7"])],
            }
        )
        targets = MOD.load_target_map(target_doc())
        with self.assertRaises(MOD.InventoryError):
            MOD.resolve_entry(
                entries, targets, "probe-app", "1.0.0", "26.0.0-BETA.3"
            )
        with self.assertRaises(MOD.InventoryError):
            MOD.resolve_entry(entries, targets, "probe-app", "1.0.0", "27.0.0")

    def test_bootstrap_builds_review_proposal_without_mutating_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            source = root / "source"
            write_source(source)
            inventory = {"schema": MOD.INVENTORY_SCHEMA, "apps": []}
            spec = {"schema": MOD.BOOTSTRAP_SCHEMA, "entry": sample_entry()}
            receipt, proposal = MOD.bootstrap_candidate(
                inventory, target_doc(), spec, source
            )
            self.assertEqual(receipt["status"], "READY_FOR_GIT_REVIEW")
            self.assertFalse(receipt["mutation_performed"])
            self.assertFalse(receipt["catalog_ready"])
            self.assertEqual(inventory["apps"], [])
            self.assertEqual(len(proposal["apps"]), 1)
            contract = proposal["apps"][0]["source_contract"]
            self.assertEqual(contract["structural_preflight"], "PASS")
            self.assertEqual(contract["official_validator"], "PENDING")
            self.assertTrue(contract["source_tree_sha256"].startswith("sha256:"))
            self.assertEqual(
                contract["test_values"],
                ["templates/test_values/basic-values.yaml"],
            )

    def test_bootstrap_rejects_identity_drift_and_missing_test_values(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            source = root / "source"
            write_source(source, app="wrong-name")
            inventory = {"schema": MOD.INVENTORY_SCHEMA, "apps": []}
            spec = {"schema": MOD.BOOTSTRAP_SCHEMA, "entry": sample_entry()}
            with self.assertRaises(MOD.InventoryError):
                MOD.bootstrap_candidate(inventory, target_doc(), spec, source)

            source2 = root / "source2"
            write_source(source2)
            (source2 / "templates/test_values/basic-values.yaml").unlink()
            with self.assertRaises(MOD.InventoryError):
                MOD.bootstrap_candidate(inventory, target_doc(), spec, source2)

    def test_bootstrap_rejects_unknown_target_or_duplicate_inventory_identity(self):
        with tempfile.TemporaryDirectory() as td:
            source = pathlib.Path(td) / "source"
            write_source(source)
            spec = {
                "schema": MOD.BOOTSTRAP_SCHEMA,
                "entry": sample_entry(targets=["27.0.0"]),
            }
            inventory = {"schema": MOD.INVENTORY_SCHEMA, "apps": []}
            with self.assertRaises(MOD.InventoryError):
                MOD.bootstrap_candidate(inventory, target_doc(), spec, source)

            existing = sample_entry()
            inventory = {"schema": MOD.INVENTORY_SCHEMA, "apps": [existing]}
            spec = {"schema": MOD.BOOTSTRAP_SCHEMA, "entry": sample_entry()}
            with self.assertRaises(MOD.InventoryError):
                MOD.bootstrap_candidate(inventory, target_doc(), spec, source)

    def test_bootstrap_cli_writes_proposal_and_receipt_not_canonical_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            source = td / "source"
            write_source(source)
            inventory_path = td / "inventory.json"
            targets_path = td / "targets.json"
            spec_path = td / "spec.json"
            proposal_path = td / "proposal.json"
            receipt_path = td / "receipt.json"
            inventory_doc = {"schema": MOD.INVENTORY_SCHEMA, "apps": []}
            inventory_path.write_text(json.dumps(inventory_doc), encoding="utf-8")
            targets_path.write_text(json.dumps(target_doc()), encoding="utf-8")
            spec_path.write_text(
                json.dumps({"schema": MOD.BOOTSTRAP_SCHEMA, "entry": sample_entry()}),
                encoding="utf-8",
            )

            import subprocess
            import sys

            cp = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "foundry_app_inventory.py"),
                    "--inventory",
                    str(inventory_path),
                    "--targets",
                    str(targets_path),
                    "bootstrap",
                    "--spec",
                    str(spec_path),
                    "--source-root",
                    str(source),
                    "--proposal-out",
                    str(proposal_path),
                    "--receipt-out",
                    str(receipt_path),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertEqual(json.loads(inventory_path.read_text()), inventory_doc)
            self.assertEqual(
                json.loads(receipt_path.read_text())["status"],
                "READY_FOR_GIT_REVIEW",
            )
            self.assertEqual(len(json.loads(proposal_path.read_text())["apps"]), 1)


if __name__ == "__main__":
    unittest.main()
