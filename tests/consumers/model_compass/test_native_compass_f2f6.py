"""Synthetic-only checks for the actual native F2–F6 probe boundaries.

No Docker/TrueNAS/SSH invocation; no private site or secret.
"""
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
os.environ["FOUNDRY_SOURCE_ROOT"] = str(ROOT)
sys.path.insert(0, str(ROOT / "tests/consumers/model_compass"))

import native_zfs_retention as p
import truenas_native_compass_f2f6 as q


class NativeCompassF2F6Contract(unittest.TestCase):
    def test_exact_source_bound_and_existing_foundry(self):
        self.assertEqual(p.SOURCE_SHA, "6e88ccbe09f7f0989a8db4e75967654d409f8f64")
        self.assertEqual(q.ROOT, ROOT)
        self.assertEqual(q.APP, p.APP_NAME)
        self.assertEqual(q.DATASET, p.DATASET)
        self.assertTrue(q.lifecycle.target.load_registry(ROOT/".foundry/truenas-target-tracks.json"))
        self.assertEqual(p.template()["app_lifecycle_executor"], "EXISTING_FOUNDRY_GENERIC_ONLY")

    def test_product_guest_compose_security_and_retained_zfs(self):
        image = "127.0.0.1:15431/compass-guest-fixture@sha256:" + "a" * 64
        a = q.compose(image)["services"]["model-compass"]
        self.assertEqual(a["image"], image)
        self.assertEqual(a["user"], "65532:65532")
        self.assertTrue(a["read_only"])
        self.assertEqual(a["cap_drop"], ["ALL"])
        self.assertEqual(a["security_opt"], ["no-new-privileges:true"])
        self.assertLessEqual(a["mem_limit"], 268435456)
        self.assertEqual(len(a["volumes"]), 2)
        self.assertEqual(a["volumes"][0]["source"], p.MOUNT)
        self.assertEqual(a["volumes"][1]["source"], p.MOUNT + "/compass_token")
        self.assertTrue(all(v["read_only"] for v in a["volumes"]))
        self.assertEqual(a["labels"]["org.sempersupra.rdte.owner"], p.OWNERSHIP)
        self.assertNotIn("privileged", a)
        self.assertNotIn("network_mode", a)
        self.assertNotIn("devices", a)
        self.assertNotIn("/var/run/docker.sock", str(a))
        # Only the disposable guest opens this path to NAT. Runner side is
        # independently constrained to loopback; source product remains :8088.
        self.assertEqual(a["ports"], ["0.0.0.0:18088:8088"])
        self.assertEqual(q.compose(image,2)["services"]["model-compass"]["environment"]["RDTE_GENERATION"], "2")
        self.assertNotEqual(q.identity(q.compose(image)), q.identity(q.compose(image,2)))

    def test_synthetic_seed_is_separate_nonnative_privilege_free_container(self):
        s=q.seed_compose()["services"]["seed"]
        self.assertEqual(s["image"], q.SEED_IMAGE)
        self.assertEqual(s["user"], "65532:65532")
        self.assertEqual(s["cap_drop"], ["ALL"])
        self.assertTrue(s["read_only"])
        self.assertEqual(s["restart"], "no")
        self.assertEqual(s["volumes"], [{"type":"bind","source":p.MOUNT,"target":"/seed","read_only":False}])
        self.assertNotIn("ports",s)
        self.assertNotIn("privileged",s)
        self.assertNotIn("docker.sock",str(s))
        self.assertIn("chmod 0400",s["command"][0])
        self.assertEqual(len(q.SYNTHETIC_TOKEN),64)
        self.assertEqual(q.SNAPSHOT["schema"],"synthetic-native-zfs/v1")

    def test_uses_generic_foundry_planner_not_an_invented_apply_layer(self):
        import inspect
        text=inspect.getsource(q.run)
        for method in ("lifecycle.plan", "lifecycle.verify", "lifecycle.target.plan",
                       "lifecycle.target.verify", "core.get_methods", "pool.dataset.create",
                       "filesystem.setperm", "filesystem.stat",
                       "app.start", "app.stop", "app.update", "app.redeploy", "app.delete"):
            self.assertIn(method,text)
        for unsafe in ("daemon.json", "docker load", "filesystem.file_receive", "sudo ", "ssh "):
            self.assertNotIn(unsafe,text)
        self.assertIn('native_F2_F6', text)
        self.assertIn('EXISTING_FOUNDRY_GENERIC_ONLY', str(p.template()))


if __name__=="__main__":
    unittest.main()
