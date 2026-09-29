from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "package_truenas_catalog_overlay",
    ROOT / "tools" / "package_truenas_catalog_overlay.py",
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class PackageCatalogOverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.published = self.root / "published" / "litellm"
        (self.published / "1.0.0").mkdir(parents=True)
        (self.published / "item.yaml").write_text("name: litellm\n", encoding="utf-8")
        (self.published / "app_versions.json").write_text(
            '{"1.0.0":{"healthy":true}}\n', encoding="utf-8"
        )
        (self.published / "1.0.0" / "app.yaml").write_text(
            "name: litellm\n", encoding="utf-8"
        )
        self.entry = self.root / "catalog-entry.json"
        self.entry.write_text(
            json.dumps(
                {
                    "name": "litellm",
                    "latest_version": "1.0.0",
                    "healthy": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_valid_overlay(self):
        desired = m.build_desired(
            self.published,
            self.entry,
            app="litellm",
            train="community",
            version="1.0.0",
            root=self.root / "work",
        )
        manifest = json.loads((desired / "overlay.json").read_text())
        self.assertEqual("semper-supra.truenas-catalog-overlay/1", manifest["schema"])
        self.assertEqual("litellm", manifest["app"])
        self.assertEqual("1.0.0", manifest["version"])
        self.assertTrue(manifest["tree_fingerprint"])
        self.assertTrue((desired / "trains" / "community" / "litellm" / "1.0.0").is_dir())

    def test_create_noop_drift(self):
        desired = m.build_desired(
            self.published,
            self.entry,
            app="litellm",
            train="community",
            version="1.0.0",
            root=self.root / "work",
        )
        fp = m.overlay_fingerprint(desired)
        out = self.root / "out"
        self.assertEqual("CREATE", m.determine_action(out, fp)[0])

        import shutil
        shutil.copytree(desired, out)
        self.assertEqual("NOOP", m.determine_action(out, fp)[0])

        (out / "overlay.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual("DRIFT_REFUSE", m.determine_action(out, fp)[0])

    def test_rejects_wrong_latest_version(self):
        self.entry.write_text(
            json.dumps({"name": "litellm", "latest_version": "9.9.9"}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(m.OverlayError, "latest_version"):
            m.build_desired(
                self.published,
                self.entry,
                app="litellm",
                train="community",
                version="1.0.0",
                root=self.root / "work",
            )


if __name__ == "__main__":
    unittest.main()
