"""Offline negative contract tests for the pinned 1.15.30 catalog migration."""
import importlib.util
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
MODULE=ROOT/"tools"/"qualify_minecraft_catalog_11530_delta.py"
spec=importlib.util.spec_from_file_location("catalog_delta",MODULE)
target=importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


def payload():
    return {
        "questions.yaml": b"stable questions\n",
        "templates/docker-compose.yaml": b"stable template\n",
        "app.yaml": b"app_version: 2026.9.2-java21\nlib_version: 2.3.4\n",
        "ix_values.yaml": (
            "repository: ghcr.io/itzg/minecraft-server\n"
            f'tag: "{target.OLD_IMAGE}"\n').encode(),
    }, {
        "questions.yaml": b"stable questions\n",
        "templates/docker-compose.yaml": b"stable template\n",
        "app.yaml": b"app_version: 2026.10.0-java21\nlib_version: 2.3.4\n",
        "ix_values.yaml": (
            "repository: ghcr.io/itzg/minecraft-server\n"
            f'tag: "{target.NEW_IMAGE}"\n').encode(),
    }


class DeltaTests(unittest.TestCase):
    def test_bounded_delta_does_not_promote_runtime(self):
        a,b=payload()
        record=target.compare(a,b)
        self.assertEqual(record["classification"],"SOURCE_DELTA_OBSERVED")
        self.assertTrue(record["questions_bytes_identical"])
        self.assertTrue(record["compose_template_bytes_identical"])
        self.assertTrue(record["image_digest_changed"])
        for name in ("source_and_image_qualified_for_new_runtime",
                     "guest_catalog_verified","native_app_materialized",
                     "paper_gameplay_verified","physical_site_mutated"):
            self.assertIs(record[name],False)

    def test_changed_questions_refuse(self):
        a,b=payload()
        b["questions.yaml"]+=b"something else"
        with self.assertRaisesRegex(ValueError,"questions schema changed"):
            target.compare(a,b)

    def test_changed_compose_refuse(self):
        a,b=payload()
        b["templates/docker-compose.yaml"]+=b"foreign service"
        with self.assertRaisesRegex(ValueError,"Compose template changed"):
            target.compare(a,b)

    def test_unpinned_version_and_image_refuse(self):
        a,b=payload()
        b["ix_values.yaml"]=b"image: latest\n"
        with self.assertRaisesRegex(ValueError,"OCI image pin drift"):
            target.compare(a,b)

if __name__=="__main__":
    unittest.main()
