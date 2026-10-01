#!/usr/bin/env python3
import copy
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "build_official_catalog_t6_control", HERE / "build_official_catalog_t6_control.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)
MANIFEST = MOD.load(HERE.parent / ".foundry" / "official-catalog-controls.json")
REF = "1" * 40


class BuildOfficialCatalogT6ControlTests(unittest.TestCase):
    def test_primary_control_is_native_catalog_and_public_safe(self):
        got = MOD.build(copy.deepcopy(MANIFEST), REF, "ntfy")
        self.assertEqual(got["schema"], "semper-supra.official-catalog-truenas-t6-control/1")
        self.assertFalse(got["runtime"]["create_payload"]["custom_app"])
        self.assertEqual(got["runtime"]["create_payload"]["catalog_app"], "ntfy")
        self.assertEqual(got["runtime"]["create_payload"]["version"], "1.1.21")
        self.assertEqual(got["control"]["app_version"], "v2.28.0")
        self.assertEqual(got["control"]["lib_version"], "2.3.4")
        self.assertEqual(
            got["control"]["lib_version_hash"],
            "2e3a8847308fb2eb0da046018f287c73822c094b5950a10377c3235794ff1242",
        )
        self.assertEqual(got["runtime"]["config_oracle"]["updated"]["TZ"], "Europe/Berlin")
        self.assertFalse(got["runtime"]["delete_options"]["remove_ix_volumes"])
        self.assertFalse(got["runtime"]["delete_options"]["remove_images"])
        self.assertTrue(got["runtime"]["upgrade"]["not_applicable_requires_receipt"])
        self.assertFalse(got["secrets_captured"])
        self.assertFalse(got["universal_qualified"])

    def test_specialized_control_cannot_be_exported_as_generic_t6_control(self):
        with self.assertRaisesRegex(MOD.BuildError, "universal candidate"):
            MOD.build(copy.deepcopy(MANIFEST), REF, "forgejo-runner")

    def test_custom_app_fallback_tamper_fails_closed(self):
        manifest = copy.deepcopy(MANIFEST)
        item = next(x for x in manifest["controls"] if x["id"] == "ntfy")
        item["custom_app_fallback"] = True
        with self.assertRaisesRegex(MOD.BuildError, "fail-closed"):
            MOD.build(manifest, REF, "ntfy")

    def test_foundry_ref_must_be_exact_commit(self):
        with self.assertRaisesRegex(MOD.BuildError, "40-hex"):
            MOD.build(copy.deepcopy(MANIFEST), "main", "ntfy")


if __name__ == "__main__":
    unittest.main()
