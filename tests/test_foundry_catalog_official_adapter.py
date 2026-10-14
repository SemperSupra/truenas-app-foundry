"""Official TrueNAS read adapter: pinned clean Git tree only, no fetch/install."""
from __future__ import annotations
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location(
    "foundry_catalog_official_adapter", TOOL / "foundry_catalog_official_adapter.py"
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def cmd(path, *args):
    result = subprocess.run(["git", "-C", str(path), *args],
                            text=True, capture_output=True, check=True, timeout=10)
    return result.stdout.strip()


def setup_repo(path):
    cmd(path, "init", "-q")
    cmd(path, "config", "user.name", "rdte-test")
    cmd(path, "config", "user.email", "rdte@example.invalid")
    root = path / "ix-dev/community/ntfy"
    files = {
        "README.md": "# ntfy\n",
        "app.yaml": "name: ntfy\nversion: 1.1.19\ntrain: community\n",
        "ix_values.yaml": "images: {}\n",
        "questions.yaml": "groups: []\nquestions: []\n",
        "templates/docker-compose.yaml": "services: {}\n",
        "templates/test_values/basic-values.yaml": "resources: {}\n",
    }
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    cmd(path, "add", ".")
    cmd(path, "commit", "-qm", "fixture exact source")
    return cmd(path, "rev-parse", "HEAD"), root


def pin(sha):
    return {"schema_version": 1, "repository": "https://github.com/truenas/apps.git",
            "ref": sha, "train": "community"}


class OfficialAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.ref, self.source = setup_repo(self.root)
        cmd(self.root, "remote", "add", "origin", "https://github.com/truenas/apps.git")
    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_sha_pinned_official_tree_exports_discovered_only(self):
        manifest = mod.project(pin(self.ref), self.root, ["ntfy"])
        self.assertEqual(manifest["revision"], self.ref)
        self.assertEqual(manifest["apps"][0]["path"], "ix-dev/community/ntfy")
        self.assertEqual(manifest["apps"][0]["version"], "1.1.19")
        self.assertTrue(manifest["apps"][0]["source_tree_sha256"].startswith("sha256:"))
        records = mod.federation.normalize(manifest)
        self.assertEqual(records[0]["admission"], "DISCOVERED_ONLY")

    def test_official_source_must_have_correct_git_remote(self):
        cmd(self.root, "remote", "set-url", "origin",
            "https://github.com/untrusted/mirror.git")
        with self.assertRaises(mod.OfficialCatalogError):
            mod.project(pin(self.ref), self.root, ["ntfy"])

    def test_ref_mismatch_denied(self):
        with self.assertRaises(mod.OfficialCatalogError):
            mod.project(pin("a"*40), self.root, ["ntfy"])

    def test_untracked_source_file_denied(self):
        (self.source / "surprise.txt").write_text("surprise")
        with self.assertRaises(mod.OfficialCatalogError):
            mod.project(pin(self.ref), self.root, ["ntfy"])

    def test_modified_source_denied(self):
        (self.source / "app.yaml").write_text("name: ntfy\nversion: 999\ntrain: community\n")
        with self.assertRaises(mod.OfficialCatalogError):
            mod.project(pin(self.ref), self.root, ["ntfy"])

    def test_metadata_name_mismatch_denied_even_when_pinned(self):
        (self.source / "app.yaml").write_text("name: other\nversion: 1.1.19\ntrain: community\n")
        cmd(self.root, "add", ".")
        cmd(self.root, "commit", "-qm", "renamed")
        latest = cmd(self.root, "rev-parse", "HEAD")
        with self.assertRaises(mod.OfficialCatalogError):
            mod.project(pin(latest), self.root, ["ntfy"])

    def test_duplicate_app_and_path_traversal_denied(self):
        for names in (["ntfy", "ntfy"], ["../ntfy"], ["ntfy/../../secret"]):
            with self.subTest(names=names):
                with self.assertRaises(mod.OfficialCatalogError):
                    mod.project(pin(self.ref), self.root, names)

    def test_wrong_provider_denied(self):
        info = pin(self.ref)
        info["repository"] = "https://github.com/attacker/apps.git"
        with self.assertRaises(mod.OfficialCatalogError):
            mod.project(info, self.root, ["ntfy"])

    def test_unspecified_app_denied(self):
        with self.assertRaises(mod.OfficialCatalogError):
            mod.project(pin(self.ref), self.root, ["missing"])


if __name__ == "__main__":
    unittest.main()
