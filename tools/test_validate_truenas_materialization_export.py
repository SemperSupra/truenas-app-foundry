import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("validate_truenas_materialization.py")
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("validate_truenas_materialization", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class MaterializationExportTests(unittest.TestCase):
    def test_writes_runtime_deployment_artifact_metadata(self):
        pin = {
            "repository": "https://github.com/truenas/apps.git",
            "ref": "a" * 40,
            "train": "community",
            "library_version": "2.3.4",
            "library_hash": "b" * 64,
        }
        source = {"services": {"probe": {"image": "example:tag"}}}
        compose = {"services": {"probe": {"image": "example@sha256:" + "c" * 64}}}
        fp = {"compose_sha256": MOD.canonical_sha256(compose)}
        deployment = MOD.build_artifact(
            "rdte-t6-probe",
            compose,
            provenance={"source_compose_sha256": MOD.canonical_sha256(source)},
        )
        controls = [{
            "app": "probe",
            "test_file": "runtime-values.yaml",
            "primary_service": "probe",
            "compose": compose,
            "fingerprint": fp,
            "runtime_safe": True,
            "qualification_role": "t6-live-stateless-control",
            "source_compose": source,
            "source_compose_sha256": MOD.canonical_sha256(source),
            "image_digests": {"probe": "example@sha256:" + "c" * 64},
            "target_lowering": {
                "published_port": {"from": 8080, "to": 32080},
                "images": "resolved-to-registry-digest",
            },
            "runtime_app_name": "rdte-t6-probe",
            "deployment_artifact": deployment,
        }]
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            MOD.write_materialized_controls(out, pin, controls)
            index = json.loads((out / "index.json").read_text())
            entry = index["controls"][0]
            dep = json.loads((out / entry["deployment_artifact_path"]).read_text())
        self.assertTrue(entry["runtime_safe"])
        self.assertEqual(entry["runtime_app_name"], "rdte-t6-probe")
        self.assertEqual(entry["deployment_artifact_sha256"], deployment["artifact_sha256"])
        self.assertEqual(dep["materialization_identity"], deployment["materialization_identity"])
        self.assertEqual(entry["target_lowering"]["published_port"]["to"], 32080)

    def test_writes_identity_bound_compose_and_index(self):
        pin = {
            "repository": "https://github.com/truenas/apps.git",
            "ref": "a" * 40,
            "train": "community",
            "library_version": "2.3.4",
            "library_hash": "b" * 64,
        }
        compose = {
            "services": {
                "probe": {"image": "example@sha256:" + "c" * 64}
            }
        }
        canonical = json.dumps(
            compose, sort_keys=True, separators=(",", ":")
        ).encode()
        fp = {"compose_sha256": MOD.hashlib.sha256(canonical).hexdigest()}
        controls = [{
            "app": "probe",
            "test_file": "basic-values.yaml",
            "primary_service": "probe",
            "compose": compose,
            "fingerprint": fp,
            "runtime_safe": True,
            "qualification_role": "t6-live-stateless-control",
        }]
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            MOD.write_materialized_controls(out, pin, controls)
            materialized = json.loads(
                (out / "probe--basic-values.compose.json").read_text()
            )
            index = json.loads((out / "index.json").read_text())

        self.assertEqual(materialized, compose)
        self.assertEqual(
            index["schema"],
            "truenas-foundry-materialized-controls/v1",
        )
        self.assertEqual(index["upstream"]["ref"], "a" * 40)
        self.assertEqual(
            index["controls"][0]["compose_sha256"],
            fp["compose_sha256"],
        )
        self.assertEqual(
            index["controls"][0]["compose_path"],
            "probe--basic-values.compose.json",
        )
        self.assertTrue(index["controls"][0]["runtime_safe"])
        self.assertEqual(
            index["controls"][0]["qualification_role"],
            "t6-live-stateless-control",
        )


if __name__ == "__main__":
    unittest.main()
