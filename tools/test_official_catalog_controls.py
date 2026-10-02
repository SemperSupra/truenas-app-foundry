#!/usr/bin/env python3
import copy
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "official_catalog_controls", HERE / "official_catalog_controls.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)

MANIFEST = MOD.load(HERE.parent / ".foundry" / "official-catalog-controls.json", "controls")
REGISTRY = MOD.load(HERE.parent / ".foundry" / "truenas-target-tracks.json", "registry")


class OfficialCatalogControlTests(unittest.TestCase):
    def test_current_manifest_is_valid_with_one_runtime_row_accepted(self):
        result = MOD.validate(copy.deepcopy(MANIFEST), copy.deepcopy(REGISTRY))
        self.assertEqual(result["status"], "PASS")
        ntfy = next(x for x in result["controls"] if x["id"] == "ntfy")
        self.assertFalse(ntfy["universal_qualified"])
        self.assertEqual(ntfy["runtime_qualified_targets"], ["25.04.1"])
        self.assertEqual(
            set(ntfy["pending_targets"]),
            set(result["required_targets"]) - {"25.04.1"},
        )

    def test_universal_candidate_requires_runtime_fixture_identity_and_values(self):
        manifest = copy.deepcopy(MANIFEST)
        ntfy = next(x for x in manifest["controls"] if x["id"] == "ntfy")
        ntfy.pop("runtime_fixture_source")
        with self.assertRaisesRegex(MOD.ControlError, "runtime_fixture_source"):
            MOD.validate(manifest, copy.deepcopy(REGISTRY))

    def test_runtime_schema_identity_is_required(self):
        manifest = copy.deepcopy(MANIFEST)
        ntfy = next(x for x in manifest["controls"] if x["id"] == "ntfy")
        ntfy.pop("runtime_schema_source")
        with self.assertRaisesRegex(MOD.ControlError, "runtime_schema_source"):
            MOD.validate(manifest, copy.deepcopy(REGISTRY))

    def test_renderer_only_fields_are_forbidden_in_runtime_values(self):
        manifest = copy.deepcopy(MANIFEST)
        ntfy = next(x for x in manifest["controls"] if x["id"] == "ntfy")
        ntfy["runtime_create_values"]["storage"]["config"]["ix_volume_config"]["create_host_path"] = True
        with self.assertRaisesRegex(MOD.ControlError, "renderer-only"):
            MOD.validate(manifest, copy.deepcopy(REGISTRY))

    def test_matrix_growth_invalidates_stale_universal_candidate(self):
        registry = copy.deepcopy(REGISTRY)
        registry["targets"].append({"version": "26.0.0-RC.1"})
        with self.assertRaisesRegex(MOD.ControlError, "matrix coverage mismatch"):
            MOD.validate(copy.deepcopy(MANIFEST), registry)

    def test_universal_claim_requires_every_exact_target(self):
        manifest = copy.deepcopy(MANIFEST)
        ntfy = next(x for x in manifest["controls"] if x["id"] == "ntfy")
        ntfy["universal_qualified"] = True
        with self.assertRaisesRegex(MOD.ControlError, "must exactly reflect"):
            MOD.validate(manifest, copy.deepcopy(REGISTRY))

    def test_runtime_qualification_cannot_escape_declared_matrix(self):
        manifest = copy.deepcopy(MANIFEST)
        ntfy = next(x for x in manifest["controls"] if x["id"] == "ntfy")
        ntfy["runtime_qualified_targets"] = ["99.99.99"]
        with self.assertRaisesRegex(MOD.ControlError, "must be declared targets"):
            MOD.validate(manifest, copy.deepcopy(REGISTRY))

    def test_custom_app_fallback_is_forbidden(self):
        manifest = copy.deepcopy(MANIFEST)
        ntfy = next(x for x in manifest["controls"] if x["id"] == "ntfy")
        ntfy["custom_app_fallback"] = True
        with self.assertRaisesRegex(MOD.ControlError, "Custom App fallback"):
            MOD.validate(manifest, copy.deepcopy(REGISTRY))

    def test_library_hash_must_be_exact_sha256(self):
        manifest = copy.deepcopy(MANIFEST)
        ntfy = next(x for x in manifest["controls"] if x["id"] == "ntfy")
        ntfy["lib_version_hash"] = "latest"
        with self.assertRaisesRegex(MOD.ControlError, "lib_version_hash"):
            MOD.validate(manifest, copy.deepcopy(REGISTRY))

    def test_specialized_runner_does_not_claim_generic_matrix(self):
        result = MOD.validate(copy.deepcopy(MANIFEST), copy.deepcopy(REGISTRY))
        forgejo = next(x for x in result["controls"] if x["id"] == "forgejo-runner")
        self.assertEqual(forgejo["role"], "specialized-control")
        self.assertEqual(forgejo["declared_targets"], [])
        self.assertFalse(forgejo["universal_qualified"])


if __name__ == "__main__":
    unittest.main()
