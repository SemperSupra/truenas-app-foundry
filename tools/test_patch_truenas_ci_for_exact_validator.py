#!/usr/bin/env python3
import importlib.util
import pathlib
import py_compile
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "patch_truenas_ci_for_exact_validator",
    HERE / "patch_truenas_ci_for_exact_validator.py",
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


FIXTURE = '''import subprocess
import sys

CONTAINER_IMAGE = "ghcr.io/truenas/apps_validation:latest"
PLATFORM = "linux/amd64"

def print_stderr(msg):
    print(msg, file=sys.stderr)

def pull_app_catalog_container():
    print_stderr(f"Pulling container image [{CONTAINER_IMAGE}]")
    res = subprocess.run(
        f"docker pull --platform {PLATFORM} --quiet {CONTAINER_IMAGE}",
        shell=True,
        capture_output=True,
    )
    if res.returncode != 0:
        print_stderr(f"Failed to pull container image [{CONTAINER_IMAGE}]")
        sys.exit(1)
    print_stderr(f"Done pulling container image [{CONTAINER_IMAGE}]")

def untouched():
    return "render-health-cleanup logic stays upstream-owned"
'''


class PatchTests(unittest.TestCase):
    def test_replaces_only_floating_image_acquisition_seam(self):
        image = "foundry/apps-validation:" + "a" * 12
        patched = MOD.patch_ci(FIXTURE, image)
        self.assertIn(f'CONTAINER_IMAGE = "{image}"', patched)
        self.assertIn('["docker", "image", "inspect", CONTAINER_IMAGE]', patched)
        self.assertNotIn("ghcr.io/truenas/apps_validation:latest", patched)
        self.assertNotIn("docker pull --platform", patched)
        self.assertIn(
            'return "render-health-cleanup logic stays upstream-owned"',
            patched,
        )

    def test_patched_fixture_still_compiles(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "ci.py"
            path.write_text(
                MOD.patch_ci(FIXTURE, "foundry/apps-validation:" + "b" * 12),
                encoding="utf-8",
            )
            py_compile.compile(str(path), doraise=True)

    def test_rejects_upstream_function_drift(self):
        with self.assertRaises(MOD.PatchError):
            MOD.patch_ci(
                FIXTURE.replace("Done pulling", "Finished pulling"),
                "foundry/apps-validation:" + "c" * 12,
            )

    def test_rejects_untrusted_image_name(self):
        with self.assertRaises(MOD.PatchError):
            MOD.patch_ci(FIXTURE, "ghcr.io/truenas/apps_validation:latest")


if __name__ == "__main__":
    unittest.main()
