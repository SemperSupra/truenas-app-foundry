"""Adversarial test for external catalog origin and pinned source verification."""
import importlib.util
import pathlib
import tempfile
import unittest

from test_foundry_catalog_official_adapter import setup_repo, cmd

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "foundry_catalog_external_adapter", ROOT / "tools/foundry_catalog_external_adapter.py"
)
external = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(external)

URI = "https://github.com/codefuturist/truenas-apps.git"


def registration(ref):
    return {
        "schema": external.SCHEMA, "uri": URI, "revision": ref,
        "train": "community", "apps": ["ntfy"],
    }


class ExternalAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.ref, self.source = setup_repo(self.root)
        cmd(self.root, "remote", "add", "origin", URI)

    def tearDown(self):
        self.temp.cleanup()

    def test_registered_external_source_is_discovery_only(self):
        index = external.project(registration(self.ref), self.root)
        self.assertEqual(index["publisher"], "github.com")
        self.assertEqual(index["source"], "codefuturist.truenas-apps")
        self.assertEqual(index["apps"][0]["version"], "1.1.19")
        record = external.federation.normalize(index)[0]
        self.assertEqual(record["admission"], "DISCOVERED_ONLY")

    def test_registry_cannot_mislabel_checkout_remote(self):
        other = registration(self.ref)
        other["uri"] = "https://github.com/another/repository.git"
        with self.assertRaises(external.ExternalSourceError):
            external.project(other, self.root)

    def test_registry_ref_must_be_exact(self):
        other = registration("main")
        with self.assertRaises(external.ExternalSourceError):
            external.project(other, self.root)

    def test_unknown_or_duplicate_apps_denied(self):
        for names in (["ntfy", "ntfy"], ["../ntfy"], ["not-real"]):
            record = registration(self.ref)
            record["apps"] = names
            with self.subTest(names=names):
                with self.assertRaises((external.ExternalSourceError,
                                        external.official.OfficialCatalogError)):
                    external.project(record, self.root)

    def test_dirty_tree_rejected(self):
        (self.source / "surprise").write_text("untracked")
        with self.assertRaises(external.official.OfficialCatalogError):
            external.project(registration(self.ref), self.root)

    def test_extra_registration_fields_fail_closed(self):
        record = registration(self.ref)
        record["allow_apply"] = True
        with self.assertRaises(external.ExternalSourceError):
            external.project(record, self.root)

    def test_unsupported_official_source_registration_denied(self):
        record = registration(self.ref)
        record["uri"] = "https://github.com/truenas/apps.git"
        with self.assertRaises(external.ExternalSourceError):
            external.project(record, self.root)


if __name__ == "__main__":
    unittest.main()
