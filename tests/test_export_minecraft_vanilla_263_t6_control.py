"""Adversarial structural checks for current-generation native TrueNAS control."""
import copy
import json
import pathlib
import sys
import unittest

import yaml

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from export_minecraft_vanilla_263_t6_control import (
    BLOB, IMAGE, IDENTITY, MIDDLEWARE, PIN, PROFILE, SCHEMA, SOURCE,
    VALUES, ExportRefused, canonical_sha256, produce
)


def fixture():
    pin=json.loads(PIN.read_text())
    values=yaml.safe_load(VALUES.read_text())
    profile=json.loads(PROFILE.read_text())
    ev={
        "result":"PASS", "truenas_target":"25.04.2.6",
        "runtime_qualification":False,
        "upstream":{"ref":SOURCE,"app":"community/minecraft"},
        "server":{"catalog_version":"1.15.30",
                  "type":"VANILLA","minecraft_version":"26.3",
                  "image_selector":"j25_image","image_ref":IMAGE,
                  "ownership_metadata":IDENTITY,
                  "world_mount":{"source":"/opt/tests/collage-vanilla-263-world"}},
        "compose_sha256":"a"*64,
    }
    return ("b"*40, ev, pin, values, profile, BLOB)


class NativeExportTests(unittest.TestCase):
    def test_signed_source_contract_no_runtime_claims(self):
        a=produce(*fixture())
        self.assertEqual(a["schema"],SCHEMA)
        self.assertEqual(a["runtime"]["minecraft_protocol"],777)
        self.assertEqual(a["runtime"]["image_selector"],"j25_image")
        self.assertEqual(a["source"]["image_reference"],IMAGE)
        self.assertEqual(a["target"]["middleware_commit"],MIDDLEWARE)
        sign=dict(a)
        actual=sign.pop("control_sha256")
        self.assertEqual(actual,canonical_sha256(sign))
        self.assertFalse(a["evidence"]["native_guest_created"])
        self.assertEqual(a["physical_truenas_apply"],"HOLD")
    def test_reject_forged_source_and_unauthorized_guest_claim(self):
        for k,v in (("result","FAIL"),("truenas_target","25.04.1"),
                    ("runtime_qualification",True),("compose_sha256","bad")):
            args=list(copy.deepcopy(fixture()))
            args[1][k]=v
            with self.subTest(field=k),self.assertRaises(ExportRefused):
                produce(*args)
    def test_reject_wrong_game_image_and_version(self):
        for k,v in (("image_ref","bad"),("type","PAPER"),
                    ("minecraft_version","1.21.11"),("image_selector","image")):
            args=list(copy.deepcopy(fixture()))
            args[1]["server"][k]=v
            with self.subTest(field=k),self.assertRaises(ExportRefused):
                produce(*args)
    def test_reject_wrong_catalog_or_target(self):
        for k,v in (("image","wrong"),("catalog_version","1.15.29")):
            args=list(copy.deepcopy(fixture()))
            args[2][k]=v
            with self.subTest(field=k),self.assertRaises(ExportRefused):
                produce(*args)
        args=list(copy.deepcopy(fixture()))
        args[5]="c"*40
        with self.assertRaises(ExportRefused):
            produce(*args)
    def test_reject_world_and_owner_drift(self):
        args=list(copy.deepcopy(fixture()))
        args[3]["storage"]["additional_storage"][0]["host_path_config"]["path"]="/foreign"
        with self.assertRaises(ExportRefused):
            produce(*args)
        args=list(copy.deepcopy(fixture()))
        args[3]["minecraft"]["additional_envs"][0]["value"]="false"
        with self.assertRaises(ExportRefused):
            produce(*args)
    def test_reject_bad_online_rcon_and_network_defaults(self):
        for k,v in (("online_mode",False),("enable_rcon",True)):
            args=list(copy.deepcopy(fixture()))
            args[3]["minecraft"][k]=v
            with self.subTest(field=k),self.assertRaises(ExportRefused):
                produce(*args)
        args=list(copy.deepcopy(fixture()))
        args[3]["network"]["host_network"]=True
        with self.assertRaises(ExportRefused):
            produce(*args)

if __name__=="__main__":
    unittest.main()
