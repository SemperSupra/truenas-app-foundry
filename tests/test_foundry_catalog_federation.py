"""Offline identity and collision tests."""
import importlib.util
import pathlib
import unittest

path = pathlib.Path(__file__).resolve().parents[1] / "tools" / "foundry_catalog_federation.py"
spec = importlib.util.spec_from_file_location("foundry_catalog_federation", path)
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)

def sample(publisher="foundry.example"):
    return {
        "schema": "truenas-foundry-catalog-source/v0",
        "publisher": publisher,
        "source": "main",
        "uri": "https://example.org/catalog.git",
        "revision": "a" * 40,
        "apps": [{
            "train": "community", "name": "sample",
            "version": "1.0.0", "path": "community/sample",
            "manifest_sha256": "sha256:" + "b" * 64,
        }],
    }

class CatalogTests(unittest.TestCase):
    def test_three_publishers_remain_distinct(self):
        rows = catalog.federate([
            sample("official.example"), sample("foundry.example"),
            sample("external.example"),
        ])
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(set(x["package_id"] for x in rows)), 3)
        self.assertTrue(all(x["admission"] == "DISCOVERED_ONLY" for x in rows))

    def test_exact_duplicate_is_idempotent(self):
        self.assertEqual(len(catalog.federate([sample(), sample()])), 1)

    def test_conflicting_revision_fails(self):
        other = sample()
        other["revision"] = "c" * 40
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.federate([sample(), other])

    def test_conflicting_manifest_fails(self):
        other = sample()
        other["apps"][0]["manifest_sha256"] = "sha256:" + "c" * 64
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.federate([sample(), other])

    def test_exact_resolve_required(self):
        rows = catalog.federate([sample()])
        key = "foundry.example/main/community/sample"
        self.assertEqual(catalog.resolve(
            rows, key, "1.0.0", "a" * 40, "sha256:" + "b" * 64
        )["package_id"], key)
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.resolve(rows, "community/sample", "1.0.0",
                            "a" * 40, "sha256:" + "b" * 64)

    def test_mutable_revision_fails(self):
        entry = sample()
        entry["revision"] = "main"
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.normalize(entry)

    def test_invalid_relative_path_fails(self):
        entry = sample()
        entry["apps"][0]["path"] = "community/../sample"
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.normalize(entry)

    def test_unknown_fields_fail(self):
        entry = sample()
        entry["apps"][0]["unexpected"] = "value"
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.normalize(entry)

if __name__ == "__main__":
    unittest.main()
