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
            "source_tree_sha256": "sha256:" + "b" * 64,
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
        other["apps"][0]["source_tree_sha256"] = "sha256:" + "c" * 64
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


    def test_large_catalog_rejected_before_row_normalization(self):
        entry = sample()
        entry["apps"] = entry["apps"] * (catalog.MAX_SOURCE_APPS + 1)
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.normalize(entry)

    def test_foundry_inventory_style_source_path_allowed(self):
        entry = sample()
        entry["apps"][0]["path"] = "fixtures/foundry-rdte-probe"
        rows = catalog.normalize(entry)
        self.assertEqual(rows[0]["path"], "fixtures/foundry-rdte-probe")

    def test_unsafe_source_path_refusal(self):
        for path in ["../etc", "fixtures/../secret", "/tmp/app", "community/app\\evil",
                     "fixtures/%2e%2e/secret", "fixtures//app"]:
            with self.subTest(path=path):
                entry = sample()
                entry["apps"][0]["path"] = path
                with self.assertRaises(catalog.CatalogIdentityError):
                    catalog.normalize(entry)

    def test_ambiguous_repository_path_denied(self):
        entry = sample()
        entry["uri"] = "https://example.org/../catalog.git"
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.normalize(entry)

    def test_oversized_index_rejected_before_parsing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "catalog.json"
            path.write_bytes(b"x" * (catalog.MAX_INDEX_BYTES + 1))
            self.assertEqual(catalog.main([str(path)]), 2)

    def test_query_list_preserves_sources_and_has_no_authority(self):
        rows = catalog.federate([sample("official.example"), sample("external.example")])
        result = catalog.query(rows, "list")
        self.assertEqual(result["count"], 2)
        self.assertTrue(all(row["admission"] == "DISCOVERED_ONLY" for row in result["apps"]))
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.query(rows, "list", package_id="official.example/main/community/sample")

    def test_query_show_does_not_silently_cross_publishers(self):
        rows = catalog.federate([sample("official.example"), sample("external.example")])
        show = catalog.query(rows, "show", package_id="official.example/main/community/sample")
        self.assertEqual(show["count"], 1)
        self.assertEqual(show["apps"][0]["provider_id"], "official.example/main")
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.query(rows, "show", package_id="community/sample")

    def test_query_resolve_requires_all_exact_identity_and_no_apply(self):
        rows = catalog.federate([sample()])
        kwargs = dict(package_id="foundry.example/main/community/sample",
                      version="1.0.0", revision="a" * 40, digest="sha256:" + "b" * 64)
        resolved = catalog.query(rows, "resolve", **kwargs)
        self.assertFalse(resolved["mutation_eligible"])
        self.assertEqual(resolved["app"]["source_tree_sha256"], kwargs["digest"])
        for missing in kwargs:
            args = dict(kwargs)
            args.pop(missing)
            with self.subTest(missing=missing):
                with self.assertRaises(catalog.CatalogIdentityError):
                    catalog.query(rows, "resolve", **args)
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.query(rows, "resolve", **dict(kwargs, digest="sha256:" + "c" * 64))

    def test_query_refuses_unrecognized_commands(self):
        with self.assertRaises(catalog.CatalogIdentityError):
            catalog.query(catalog.federate([sample()]), "apply")

if __name__ == "__main__":
    unittest.main()
