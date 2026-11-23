#!/usr/bin/env python3
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "package_truenas_deployment_artifact",
    HERE / "package_truenas_deployment_artifact.py",
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


class DeploymentArtifactTests(unittest.TestCase):
    def test_identity_is_deterministic_and_payloads_are_native_custom_app_shapes(self):
        compose_a = {
            "services": {
                "probe": {
                    "image": "example@sha256:" + "c" * 64,
                    "environment": {"B": "2", "A": "1"},
                }
            }
        }
        compose_b = {
            "services": {
                "probe": {
                    "environment": {"A": "1", "B": "2"},
                    "image": "example@sha256:" + "c" * 64,
                }
            }
        }
        a = MOD.build_artifact("probe-app", compose_a)
        b = MOD.build_artifact("probe-app", compose_b)
        self.assertEqual(a["compose_sha256"], b["compose_sha256"])
        self.assertEqual(a["materialization_identity"], b["materialization_identity"])
        self.assertTrue(a["create_payload"]["custom_app"])
        self.assertEqual(a["create_payload"]["app_name"], "probe-app")
        self.assertEqual(a["create_payload"]["custom_compose_config"], compose_a)
        self.assertEqual(a["update_payload"]["custom_compose_config"], compose_a)
        self.assertIn("app.config", a["required_methods"])

    def test_rejects_invalid_name_or_empty_compose(self):
        with self.assertRaises(MOD.ArtifactError):
            MOD.build_artifact("Bad_Name", {"services": {"x": {}}})
        with self.assertRaises(MOD.ArtifactError):
            MOD.build_artifact("good-name", {"services": {}})

    def test_cli_writes_mode_0600_without_printing_compose(self):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            compose = {
                "services": {
                    "probe": {
                        "image": "example@sha256:" + "d" * 64,
                        "environment": {"PRIVATE_TEST_SENTINEL": "do-not-print"},
                    }
                }
            }
            src = td / "compose.json"
            out = td / "artifact.json"
            src.write_text(json.dumps(compose), encoding="utf-8")
            import subprocess, sys
            cp = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "package_truenas_deployment_artifact.py"),
                    "--app-name", "probe-app",
                    "--compose", str(src),
                    "--out", str(out),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertNotIn("do-not-print", cp.stdout)
            self.assertEqual(os.stat(out).st_mode & 0o777, 0o600)
            artifact = json.loads(out.read_text())
            self.assertEqual(
                artifact["materialization_identity"],
                "sha256:" + artifact["compose_sha256"],
            )


    def test_strict_image_gate_accepts_digest_and_rejects_mutable_or_missing(self):
        valid = {"services": {"probe": {"image": "ghcr.io/example/probe@sha256:" + "a" * 64}}}
        MOD.require_immutable_images(valid)
        bad = [
            {"services": {"probe": {"image": "ghcr.io/example/probe:latest"}}},
            {"services": {"probe": {"image": "ghcr.io/example/probe:0.0.3-rc.1"}}},
            {"services": {"probe": {"build": "."}}},
            {"services": {"probe": {"image": "ghcr.io/example/probe@sha256:bad"}}},
            {"services": {"probe": {"image": "ghcr.io/example/probe@sha256:" + "a" * 63}}},
            {"services": {"probe": {"image": "ghcr.io/example/probe@sha256:" + "A" * 64}}},
        ]
        for compose in bad:
            with self.subTest(compose=compose), self.assertRaisesRegex(MOD.ArtifactError, "immutable image required"):
                MOD.require_immutable_images(compose)

    def test_strict_cli_fails_closed_before_artifact_creation(self):
        import subprocess, sys
        with tempfile.TemporaryDirectory() as dirname:
            root = pathlib.Path(dirname)
            source = root / "candidate-compose.json"
            output = root / "artifact.json"
            source.write_text(json.dumps({"services": {"probe": {"image": "example/probe:0.0.3-rc.1"}}}))
            command = [sys.executable, str(HERE / "package_truenas_deployment_artifact.py"),
                       "--app-name", "probe-app", "--compose", str(source), "--out", str(output),
                       "--require-immutable-images"]
            fail = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(fail.returncode, 2)
            self.assertIn("immutable image required", fail.stderr)
            self.assertFalse(output.exists(), "tag-only source must not produce a target artifact")
            source.write_text(json.dumps({"services": {"probe": {"image": "example/probe@sha256:" + "c" * 64}}}))
            success = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            artifact = json.loads(output.read_text())
            self.assertEqual(artifact["schema"], "truenas-foundry-deployment-artifact/v1")
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
