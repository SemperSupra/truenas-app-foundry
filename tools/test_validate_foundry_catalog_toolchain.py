#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "validate_foundry_catalog_toolchain",
    HERE / "validate_foundry_catalog_toolchain.py",
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)

def good():
    return {
        "schema": MOD.SCHEMA,
        "apps": {
            "repository": "https://github.com/truenas/apps.git",
            "ref": "a" * 40,
            "validator_command": "/usr/local/bin/apps_dev_charts_validate validate --path /work",
        },
        "apps_validation": {
            "repository": "https://github.com/truenas/apps_validation.git",
            "ref": "b" * 40,
            "declared_base": "ghcr.io/truenas/middleware:master",
            "validator_cli": "/usr/local/bin/apps_dev_charts_validate",
        },
        "policy": {
            "exact_git_refs_required": True,
            "resolve_floating_base_to_digest_per_run": True,
            "floating_validator_image_forbidden": True,
            "catalog_ready_requires_native_validator_and_render_install": True,
        },
    }

class ToolchainTests(unittest.TestCase):
    def test_accepts_exact_contract(self):
        out = MOD.validate(good())
        self.assertEqual(out["status"], "PASS")

    def test_rejects_floating_git_ref(self):
        data = good()
        data["apps"]["ref"] = "master"
        with self.assertRaises(MOD.ToolchainError):
            MOD.validate(data)

    def test_rejects_validator_command_drift(self):
        data = good()
        data["apps"]["validator_command"] = "something else"
        with self.assertRaises(MOD.ToolchainError):
            MOD.validate(data)

    def test_rejects_unacknowledged_floating_base(self):
        data = good()
        data["policy"]["resolve_floating_base_to_digest_per_run"] = False
        with self.assertRaises(MOD.ToolchainError):
            MOD.validate(data)

if __name__ == "__main__":
    unittest.main()
