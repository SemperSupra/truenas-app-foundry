from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reconcile_truenas_catalog_overlay",
    ROOT / "tools" / "reconcile_truenas_catalog_overlay.py",
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class CatalogOverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.catalog = self.root / "catalog"
        self.catalog.mkdir()
        subprocess.run(["git", "init", "-q", self.catalog], check=True)
        subprocess.run(["git", "-C", self.catalog, "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", self.catalog, "config", "user.email", "test@example.invalid"], check=True)
        (self.catalog / "catalog.json").write_text(
            json.dumps({"community": {"other": {"name": "other"}}}, indent=4) + "\n",
            encoding="utf-8",
        )
        (self.catalog / "trains" / "community" / "other" / "1.0.0").mkdir(parents=True)
        (self.catalog / "trains" / "community" / "other" / "1.0.0" / "app.yaml").write_text(
            "name: other\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", self.catalog, "add", "."], check=True)
        subprocess.run(["git", "-C", self.catalog, "commit", "-q", "-m", "baseline"], check=True)

        self.overlay = self.root / "overlay"
        tree = self.overlay / "trains" / "community" / "litellm"
        (tree / "1.0.0").mkdir(parents=True)
        (tree / "item.yaml").write_text("name: litellm\n", encoding="utf-8")
        (tree / "app_versions.json").write_text('{"1.0.0": {"healthy": true}}\n', encoding="utf-8")
        (tree / "1.0.0" / "app.yaml").write_text("name: litellm\n", encoding="utf-8")
        entry = {"name": "litellm", "latest_version": "1.0.0", "healthy": True}
        manifest = {
            "schema": "semper-supra.truenas-catalog-overlay/1",
            "app": "litellm",
            "train": "community",
            "version": "1.0.0",
            "catalog_entry": entry,
            "tree_fingerprint": m.tree_fingerprint(tree),
        }
        (self.overlay / "overlay.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_noop_revert(self):
        overlay = m.load_overlay(self.overlay)
        plan = m.inspect(self.catalog, overlay)
        self.assertEqual(("ABSENT", "CREATE"), (plan["status"], plan["action"]))

        applied = m.apply_overlay(self.catalog, overlay)
        self.assertEqual("APPLIED", applied["result"])
        again = m.apply_overlay(self.catalog, overlay)
        self.assertEqual("NOOP", again["result"])

        reverted = m.revert_overlay(self.catalog, overlay)
        self.assertEqual("REVERTED", reverted["result"])
        second = m.revert_overlay(self.catalog, overlay)
        self.assertEqual("NOOP", second["result"])

        data = json.loads((self.catalog / "catalog.json").read_text())
        self.assertEqual({"name": "other"}, data["community"]["other"])
        self.assertNotIn("litellm", data["community"])

    def test_unrelated_worktree_drift_refuses(self):
        (self.catalog / "unrelated.txt").write_text("drift\n", encoding="utf-8")
        overlay = m.load_overlay(self.overlay)
        plan = m.inspect(self.catalog, overlay)
        self.assertEqual("UNRELATED_DRIFT", plan["status"])
        self.assertEqual("REFUSE", plan["action"])

    def test_partial_overlay_refuses(self):
        dest = self.catalog / "trains" / "community" / "litellm"
        dest.mkdir(parents=True)
        (dest / "partial").write_text("x\n", encoding="utf-8")
        overlay = m.load_overlay(self.overlay)
        plan = m.inspect(self.catalog, overlay)
        self.assertEqual("PARTIAL_DRIFT", plan["status"])
        self.assertEqual("REFUSE", plan["action"])

    def test_upstream_owned_app_is_never_overlaid_or_removed(self):
        data = json.loads((self.catalog / "catalog.json").read_text())
        data["community"]["litellm"] = {"name": "official-litellm"}
        (self.catalog / "catalog.json").write_text(json.dumps(data, indent=4) + "\n")
        d = self.catalog / "trains" / "community" / "litellm" / "1.0.0"
        d.mkdir(parents=True)
        (d / "app.yaml").write_text("name: official\n")
        subprocess.run(["git", "-C", self.catalog, "add", "."], check=True)
        subprocess.run(["git", "-C", self.catalog, "commit", "-q", "-m", "upstream"], check=True)

        overlay = m.load_overlay(self.overlay)
        plan = m.inspect(self.catalog, overlay)
        self.assertEqual("UPSTREAM_PRESENT", plan["status"])
        self.assertEqual("NONE", plan["action"])
        reverted = m.revert_overlay(self.catalog, overlay)
        self.assertEqual("REFUSED", reverted["result"])

    def test_owned_drift_refuses_revert(self):
        overlay = m.load_overlay(self.overlay)
        m.apply_overlay(self.catalog, overlay)
        app_yaml = self.catalog / "trains" / "community" / "litellm" / "1.0.0" / "app.yaml"
        app_yaml.write_text("drift\n", encoding="utf-8")
        plan = m.inspect(self.catalog, overlay)
        self.assertEqual("OWNED_DRIFT", plan["status"])
        self.assertEqual("REFUSE", plan["action"])
        self.assertEqual("REFUSED", m.revert_overlay(self.catalog, overlay)["result"])


if __name__ == "__main__":
    unittest.main()
