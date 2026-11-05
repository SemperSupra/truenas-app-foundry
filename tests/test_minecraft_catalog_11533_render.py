"""Adversarial qualification of 1.15.31→1.15.33 canonical rendered Compose."""
from __future__ import annotations
import copy
import unittest
from tools.qualify_minecraft_catalog_11533_render import (
    evaluate, OLD, NEW, OWNER, WORLD, IMAGE, SCHEMA)

def fixture():
    def row(ref,ver,lib):
        return {"result":"PASS","runtime_qualification":False,
            "truenas_target":"25.04.2.6",
            "upstream":{"ref":ref,"library_version":lib},
            "server":{"catalog_version":ver,"type":"VANILLA",
                "minecraft_version":"26.3","image_selector":"j25_image",
                "image_ref":IMAGE,"ownership_metadata":copy.deepcopy(OWNER),
                "world_mount":{"source":WORLD,"target":"/data/world","read_only":False},
                "base_data_mount":{"source":"/opt/tests/collage-server-data",
                                   "target":"/data","read_only":False}},
            "platform_normalization":{"actions":[{"action":"ensure-ix-volume",
                                                  "dataset_name":"data"}],
                                      "dependency_identity_sha256":"a"*64},
            "compose_sha256":"f"*64}
    return row(OLD,"1.15.31","2.3.16"),row(NEW,"1.15.33","2.3.17")

class ExactRenderParityTests(unittest.TestCase):
    def test_source_pass_is_not_runtime_or_signed_consumer(self):
        old,new=fixture()
        r=evaluate(old,new)
        self.assertEqual(r["classification"],"SOURCE_RENDER_CANONICAL_COMPOSE_IDENTICAL")
        for key in ("runtime_guest_qualified","signed_foundry_consumer_updated",
                    "native_backend_world_qualified"):
            self.assertFalse(r[key])
        self.assertEqual(r["physical_truenas_apply"],"HOLD")
    def test_changed_any_rendered_digest_refused(self):
        old,new=fixture()
        new["compose_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"RENDERED_COMPOSE_CANONICAL_SHA_DRIFT"):
            evaluate(old,new)
    def test_foreign_upstream_and_library_refused(self):
        for field,value,error in (
            ("ref","0"*40,"UPSTREAM_EXACT_REF_DRIFT"),
            ("library_version","2.3.18","SHARED_LIBRARY_PIN_DRIFT"),
        ):
            a,b=fixture();b["upstream"][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,error):
                evaluate(a,b)
    def test_malicious_world_image_or_owner_refused(self):
        for action in ("image","world","owner","world_ro"):
            a,b=fixture()
            if action=="image":b["server"]["image_ref"]="ghcr.io/itzg/minecraft-server:latest"
            elif action=="world":b["server"]["world_mount"]["source"]="/foreign"
            elif action=="owner":b["server"]["ownership_metadata"]["SUPRACRAFT_COLLAGE_WORLD_ID"]="foreign"
            else:b["server"]["world_mount"]["read_only"]=True
            with self.subTest(action=action),self.assertRaisesRegex(
                ValueError,"NATIVE_RENDER_OWNERSHIP_IMAGE_OR_WORLD_DRIFT"):
                evaluate(a,b)
    def test_platform_synthetic_injection_refused(self):
        a,b=fixture()
        b["platform_normalization"]["actions"].append({"action":"add-dangerous-volume"})
        with self.assertRaisesRegex(ValueError,"PLATFORM_NORMALIZATION_ACTION_DRIFT"):
            evaluate(a,b)
    def test_extra_server_field_refused_even_matching_full_digest(self):
        a,b=fixture();b["server"]["privileged"]=True
        with self.assertRaisesRegex(ValueError,"SERVER_RUNTIME_PROJECTION_DRIFT"):
            evaluate(a,b)
    def test_missing_or_unqualified_old_or_new_refused(self):
        for mutation in ("old","new"):
            a,b=fixture();(a if mutation=="old" else b)["result"]="NOT_QUALIFIED"
            with self.subTest(mutation=mutation),self.assertRaisesRegex(
                ValueError,"RENDER_SOURCE_NOT_ACCEPTED"):
                evaluate(a,b)
if __name__=="__main__":unittest.main()
