"""Separate exact v1.15.30 control qualification, preserving old v1.15.29."""
import copy
import importlib.util
import pathlib
import unittest
from unittest import mock

ROOT=pathlib.Path(__file__).resolve().parents[1]
MODULE=ROOT/"tools/export_minecraft_paper_t6_control.py"
spec=importlib.util.spec_from_file_location("minecraft_export",MODULE)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
REF="a"*40
EVIDENCE={
    "result":"PASS",
    "upstream":{"ref":"559b9fe85212c800bc6770f152a65211df137a44",
                "app":"community/minecraft"},
    "server":{
        "catalog_version":"1.15.30",
        "image_ref":"ghcr.io/itzg/minecraft-server:2026.10.0-java21@sha256:d4057e7019e9b19f25e039d4a204cc502e1a112d1a2305966a534f3d7079e644",
    },
    "compose_sha256":"9"*64,
}

class ExactProfileTests(unittest.TestCase):
    def setUp(self):
        def exact_git_response(command, text=False):
            if command[-2:] == ["rev-parse", "HEAD"]:
                return REF
            if command[-2] == "hash-object":
                return "800aca038ded29e6a91bfc4c1b1fe2d2199182e8"
            raise AssertionError("unexpected git source inspection")
        self.patch=mock.patch.object(mod.subprocess,"check_output",
                                     side_effect=exact_git_response)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_new_profile_source_candidate_not_a_runtime_acceptance(self):
        x=mod.source_control(REF,copy.deepcopy(EVIDENCE),catalog_version="1.15.30")
        self.assertEqual(x["source"]["apps_commit"],
                         "559b9fe85212c800bc6770f152a65211df137a44")
        self.assertEqual(x["runtime"]["catalog_version_candidate"],"1.15.30")
        self.assertEqual(x["runtime"]["paper_version"],"1.21.11")
        self.assertFalse(x["evidence"]["live_catalog_version_verified"])
        self.assertFalse(x["evidence"]["live_minecraft_server_qualified"])
        self.assertFalse(x["evidence"]["physical_truenas_qualified"])
        self.assertFalse(x["secrets_captured"])
        temp=x.copy()
        signature=temp.pop("control_sha256")
        self.assertEqual(signature,mod.digest(temp))

    def test_old_default_is_unchanged(self):
        self.assertEqual(mod.CATALOG_VERSION,"1.15.29")
        self.assertEqual(mod.CATALOG_PROFILES["1.15.29"]["ref"],
                         "bb96ef6fd8c2708765012a4a3ca3739370a4f92c")

    def test_new_profile_never_accepts_old_catalog_or_image(self):
        x=copy.deepcopy(EVIDENCE)
        x["server"]["catalog_version"]="1.15.29"
        with self.assertRaisesRegex(mod.ControlError,"catalog revision"):
            mod.source_control(REF,x,catalog_version="1.15.30")
        x=copy.deepcopy(EVIDENCE)
        x["server"]["image_ref"]=mod.CATALOG_PROFILES["1.15.29"]["image"]
        with self.assertRaisesRegex(mod.ControlError,"digest-pinned"):
            mod.source_control(REF,x,catalog_version="1.15.30")

    def test_unadmitted_profile_refused(self):
        with self.assertRaisesRegex(mod.ControlError,"unadmitted"):
            mod.source_control(REF,EVIDENCE,catalog_version="1.15.31")

if __name__=="__main__":
    unittest.main()
