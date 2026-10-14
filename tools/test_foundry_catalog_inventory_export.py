"""Source-index projection uses canonical Foundry inventory validation."""
import importlib.util
import json
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "foundry_catalog_inventory_export", HERE / "foundry_catalog_inventory_export.py"
)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

REV = "a" * 40
REPO = "https://github.com/SemperSupra/truenas-app-foundry.git"
TREE = "sha256:" + "b" * 64


def entry(name="foundry-rdte-probe", rev=REV):
    return {
        "id": name,
        "version": "1.0.0",
        "source": {
            "kind": "foundry-repository", "repository": REPO,
            "ref": rev, "path": "fixtures/foundry-rdte-probe"
        },
        "catalog_train": "community",
        "target_versions": ["25.04.2.6"],
        "source_contract": {
            "catalog_source_shape": "truenas-apps-ix-dev/v1",
            "source_tree_sha256": TREE,
            "structural_preflight": "PASS",
            "official_validator": "PENDING",
        },
        "catalog_export": {"status": "not-assessed"},
    }


def doc(*items):
    return {"schema": "truenas-foundry-app-inventory/v1", "apps": list(items)}


def project(inventory_doc):
    return export.project(
        inventory_doc, publisher="github.com",
        source_id="sempersupra-truenas-app-foundry",
        repository=REPO, revision=REV
    )


class InventoryBridgeTests(unittest.TestCase):
    def test_exact_pinned_inventory_projection(self):
        result = project(doc(entry()))
        self.assertEqual(result["schema"], export.SCHEMA)
        self.assertEqual(result["revision"], REV)
        self.assertEqual(result["uri"], REPO)
        self.assertEqual(result["apps"][0]["path"], "fixtures/foundry-rdte-probe")
        self.assertEqual(result["apps"][0]["source_tree_sha256"], TREE)
        self.assertNotIn("mutation_eligible", result)

    def test_real_foundry_probe_bootstrap_to_discovery(self):
        root = HERE.parent
        seed = json.loads((root / ".foundry/bootstrap/foundry-rdte-probe.json").read_text())
        targets = json.loads((root / ".foundry/truenas-target-tracks.json").read_text())
        base = {"schema": export.inventory.INVENTORY_SCHEMA, "apps": []}
        receipt, proposed = export.inventory.bootstrap_candidate(
            base, targets, seed, root / "fixtures/foundry-rdte-probe"
        )
        self.assertEqual(receipt["status"], "READY_FOR_GIT_REVIEW")
        source = seed["entry"]["source"]
        projected = export.project(
            proposed, publisher="github.com",
            source_id="sempersupra-truenas-app-foundry",
            repository=source["repository"], revision=source["ref"]
        )
        self.assertEqual(len(projected["apps"]), 1)
        app = projected["apps"][0]
        self.assertEqual(app["name"], "foundry-rdte-probe")
        self.assertEqual(app["path"], source["path"])
        self.assertEqual(app["source_tree_sha256"], receipt["source_contract"]["source_tree_sha256"])
        self.assertEqual(base["apps"], [])

    def test_unrelated_revision_not_projected(self):
        result = project(doc(entry(), entry("other", "c" * 40)))
        self.assertEqual(len(result["apps"]), 1)

    def test_refuse_no_pinned_match(self):
        with self.assertRaises(export.ExportError):
            project(doc(entry(rev="c" * 40)))

    def test_refuse_missing_digest_contract(self):
        e = entry()
        e.pop("source_contract")
        with self.assertRaises(export.ExportError):
            project(doc(e))

    def test_refuse_malformed_tree_digest(self):
        e = entry()
        e["source_contract"]["source_tree_sha256"] = "sha256:latest"
        with self.assertRaises(export.ExportError):
            project(doc(e))

    def test_refuse_source_without_immutable_ref(self):
        with self.assertRaises(export.ExportError):
            export.project(doc(entry()), publisher="github.com",
                           source_id="foundry", repository=REPO, revision="main")

    def test_refuse_duplicate_canonical_inventory_identity(self):
        with self.assertRaises(export.inventory.InventoryError):
            project(doc(entry(), entry()))

    def test_refuse_catalog_train_none(self):
        e = entry()
        e["catalog_train"] = "none"
        with self.assertRaises(export.ExportError):
            project(doc(e))


if __name__ == "__main__":
    unittest.main()
