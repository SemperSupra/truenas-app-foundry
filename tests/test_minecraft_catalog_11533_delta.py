"""Synthetic red/blue checks: source comparison cannot certify new library or guest."""
from __future__ import annotations

import copy
import unittest

from tools.qualify_minecraft_catalog_11533_delta import (
    FILES, OLD_VERSION, NEW_VERSION, OLD_LIBRARY, NEW_LIBRARY,
    OLD_LIB_HASH, NEW_LIB_HASH, compare, fetch)


def fixture():
    old = {
        "app.yaml": (f"version: {OLD_VERSION}\nlib_version: {OLD_LIBRARY}\n"
                     f"lib_version_hash: {OLD_LIB_HASH}\napp_version: 2026.10.0-java21\n").encode(),
        "questions.yaml": b"fixed questions for same Minecraft version\n",
        "ix_values.yaml": b"fixed default OCI tag and Java25 image selector\n",
        "templates/docker-compose.yaml": b"fixed bounded Compose source\n",
        "app_migrations.yaml": b"fixed migration table\n",
    }
    new = copy.deepcopy(old)
    new["app.yaml"] = (f"version: {NEW_VERSION}\nlib_version: {NEW_LIBRARY}\n"
                       f"lib_version_hash: {NEW_LIB_HASH}\napp_version: 2026.10.0-java21\n").encode()
    return old, new


class SourceDeltaTests(unittest.TestCase):
    def test_valid_delta_retains_all_runtime_negatives(self):
        before, after = fixture()
        receipt = compare(before, after)
        self.assertEqual(receipt["classification"], "EXACT_UPSTREAM_SOURCE_DELTA_ONLY")
        self.assertTrue(receipt["unchanged_runtime_input_and_compose_source"])
        self.assertTrue(receipt["changed_shared_library_requires_render_qualification"])
        for key in ("rendered_compose_semantics_qualified",
                    "signed_foundry_11533_control_qualified",
                    "native_guest_catalog_verified", "backend_world_qualified"):
            self.assertFalse(receipt[key])
        self.assertEqual(receipt["physical_true_nas_apply"], "HOLD")
        self.assertEqual(set(receipt["source_files_sha256"]), set(FILES))

    def test_any_changed_template_or_question_or_oci_defaults_refused(self):
        for name in (key for key in FILES if key != "app.yaml"):
            before, after = fixture()
            after[name] += b"malicious or unqualified source edit"
            with self.subTest(name=name), self.assertRaisesRegex(
                    ValueError, "UPSTREAM_RUNTIME_INPUT_OR_TEMPLATE_DRIFT"):
                compare(before, after)

    def test_unknown_app_metadata_and_library_refused(self):
        for field in ("library", "hash", "new_field", "version"):
            before, after = fixture()
            if field == "library":
                after["app.yaml"] = after["app.yaml"].replace(
                    b"2.3.17", b"99.0.0")
            elif field == "hash":
                after["app.yaml"] = after["app.yaml"].replace(
                    NEW_LIB_HASH.encode(), b"f"*64)
            elif field == "version":
                after["app.yaml"] = after["app.yaml"].replace(
                    NEW_VERSION.encode(), b"1.15.34")
            else:
                after["app.yaml"] += b"new_upstream_flag: dangerous\n"
            with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError, "UPSTREAM_APP_"):
                compare(before, after)

    def test_refuse_missing_files_and_wrong_type(self):
        old, new = fixture()
        del new["questions.yaml"]
        with self.assertRaisesRegex(ValueError, "EXACT_FILE_SET_REQUIRED"):
            compare(old, new)
        old, new = fixture()
        new["ix_values.yaml"] = "forged text not bytes"
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_FILE_BYTES"):
            compare(old, new)

    def test_fetch_cannot_be_redirected_to_unpinned_source(self):
        for ref, ver, path in (
            ("main", NEW_VERSION, "app.yaml"),
            ("f"*40, NEW_VERSION, "app.yaml"),
            ("99"*20, OLD_VERSION, "app.yaml"),
            (NEW_VERSION, NEW_VERSION, "../secret"),
        ):
            with self.subTest(ref=ref), self.assertRaisesRegex(
                    ValueError, "UNPINNED_UPSTREAM_FILE"):
                fetch(ref, ver, path)


if __name__ == "__main__":
    unittest.main()
