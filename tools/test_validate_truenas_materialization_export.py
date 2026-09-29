import importlib.util
import json
import pathlib
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("validate_truenas_materialization.py")
SPEC = importlib.util.spec_from_file_location("validate_truenas_materialization", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class MaterializationExportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
