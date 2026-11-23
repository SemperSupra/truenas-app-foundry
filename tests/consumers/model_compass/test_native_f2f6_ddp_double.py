"""Public offline TrueNAS DDP state-machine double for native F2-F6 source.

This is NOT a guest/host substitute or a production acceptance result. It
executes the same source-owned generic Foundry planner and lifecycle orchestration
against bounded synthetic native API calls, with negatives for foreign ownership.
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[3]
os.environ["FOUNDRY_SOURCE_ROOT"]=str(ROOT)
sys.path.insert(0,str(ROOT/"tests/consumers/model_compass"))

import truenas_native_compass_f2f6 as f
import native_zfs_retention as z


class NativeDouble:
    def __init__(self):
        targets=f.lifecycle.target.load_registry(ROOT/".foundry/truenas-target-tracks.json")
        track=next(x for x in targets["targets"] if x["version"]=="25.04.2.6")
        self.methods=set(track["profile_contract"]["required_public_methods"]) | {
            "app.query","app.config","app.create","app.stop","app.start",
            "app.update","app.redeploy","app.delete","pool.dataset.create",
            "pool.dataset.query","pool.dataset.delete","filesystem.stat","filesystem.setperm",
        }
        self.apps={}
        self.dataset=False
        self.perms=False
        self.seeded=False
        self.deleted=False
        self.history=[]
        self.next_job=10

    def call(self, method, params):
        self.history.append(method)
        if method=="core.get_methods":
            return {name:{"description":"synthetic-only"} for name in sorted(self.methods) if name!="core.get_methods"}
        if method=="app.query":
            name=params[0][0][2]
            return [dict(self.apps[name]["observable"])] if name in self.apps else []
        if method=="app.config":
            return self.apps[params[0]]["config"]
        if method=="pool.dataset.query":
            return [{"id":z.DATASET,"mountpoint":{"value":z.MOUNT}}] if self.dataset else []
        if method=="pool.dataset.create":
            assert not self.dataset and params[0]["name"]==z.DATASET
            self.dataset=True
            return {"id":z.DATASET}
        if method=="pool.dataset.delete":
            assert self.dataset and not self.apps
            self.dataset=False
            self.deleted=True
            return True  # True must NOT be misidentified as async job ID.
        if method=="filesystem.setperm":
            assert self.dataset
            assert params[0]["uid"]==65532 and params[0]["mode"]=="700"
            self.perms=True
            return True
        if method=="filesystem.stat":
            path=params[0]
            if path==z.MOUNT:
                assert self.dataset and self.perms
                return {"realpath":path,"uid":65532,"mode":0o40700,"acl":False}
            assert self.seeded and self.dataset
            if path.endswith("/compass_token"):
                return {"realpath":path,"uid":65532,"mode":0o100400,"size":65,"acl":False}
            if path.endswith("/snapshot.json"):
                return {"realpath":path,"uid":65532,"mode":0o100400,"size":64,"acl":False}
            raise AssertionError("unowned stat path")
        if method=="app.create":
            data=params[0];name=data["app_name"]
            assert name not in self.apps and self.dataset
            config=data["custom_compose_config"]
            self.apps[name]={
                "config":config,
                "observable":{"id":name,"state":"RUNNING","custom_app":True,
                              "active_workloads":{"containers":1}},
            }
            if name==f.SEED_APP:
                assert self.perms
                self.seeded=True
            return self._job()
        if method in {"app.start","app.stop","app.redeploy","app.delete"}:
            name=params[0]
            assert name in self.apps
            if method=="app.delete":
                del self.apps[name]
            elif method=="app.stop":
                self.apps[name]["observable"]["state"]="STOPPED"
                self.apps[name]["observable"]["active_workloads"]["containers"]=0
            else:
                self.apps[name]["observable"]["state"]="RUNNING"
                self.apps[name]["observable"]["active_workloads"]["containers"]=1
            return self._job()
        if method=="app.update":
            name=params[0]
            assert name in self.apps
            self.apps[name]["config"]=params[1]["custom_compose_config"]
            return self._job()
        raise AssertionError("out-of-contract native API: "+method)

    def _job(self):
        self.next_job+=1
        return self.next_job

    def job(self, number,label):
        assert type(number) is int and number>=10,label


class NativeF2F6MockTests(unittest.TestCase):
    def test_full_lifecycle_matches_existing_foundry_and_retains_zfs(self):
        backend=NativeDouble()
        receipt={"evidence":{},"native_F2_F6":"NOT_RUN"}
        def fake_http(path,**kw):
            if path=="/healthz":
                return 200,{"status":"UP"}
            if path=="/v1/snapshot":
                if kw.get("auth") is False:
                    return 401,{"status":"ERROR"}
                return 200,{"status":"EXTERNAL_SNAPSHOT_UNVERIFIED","snapshot":f.SNAPSHOT}
            if path=="/v1/recommend":
                return 200,{"qualification":"UNKNOWN","automatic_admission":False}
            raise AssertionError(path)
        with patch.object(f,"http",side_effect=fake_http):
            f.run(
                backend.call,backend.job,
                "127.0.0.1:15431/compass-guest-fixture@sha256:"+"a"*64,
                receipt,state_timeout=4,
            )
        self.assertEqual(receipt["native_F2_F6"],"GUEST_REAL_PASS")
        self.assertEqual(receipt["native_product"]["full_F2_F6"],"GUEST_REAL_PASS")
        self.assertEqual(receipt["native_product"]["status"],"VERIFIED")
        self.assertFalse(receipt["native_product"]["private_discovery_proof"]["returned_as_public_method"])
        self.assertEqual(receipt["native_product"]["private_discovery_proof"]["evidence"],"AUTHENTICATED_DDP_INVOCATION_SUCCEEDED")
        self.assertTrue(backend.deleted)
        self.assertEqual(backend.apps,{})
        self.assertFalse(backend.dataset)
        self.assertIn("CLEANUP_OWNED_ZFS_DATASET_ABSENT",receipt["native_product"]["events"])
        self.assertIn("F6_REINSTALL_RETAINED_DATA_AND_VALID_AUTH",receipt["native_product"]["events"])
        self.assertEqual(backend.history.count("app.create"),3)  # seed, initial, reinstalled
        self.assertEqual(backend.history.count("app.redeploy"),1)
        self.assertIn("app.stop",backend.history)
        self.assertIn("app.start",backend.history)
        self.assertIn("app.update",backend.history)

    def test_missing_true_runtime_method_blocks_foundry_before_app_create(self):
        backend=NativeDouble()
        backend.methods.remove("system.version")
        receipt={"evidence":{}}
        with self.assertRaises(f.NativeQualificationError):
            f.run(
                backend.call,backend.job,
                "127.0.0.1:15431/compass-guest-fixture@sha256:"+"a"*64,
                receipt,state_timeout=2,
            )
        self.assertEqual(receipt["native_product"]["generic_create_plan"]["status"],"BLOCKED")
        self.assertIn(
            "system.version",
            receipt["native_product"]["generic_create_plan"]["profile_missing_methods"],
        )
        self.assertNotIn("compass_create",str(receipt.get("evidence")))
        self.assertNotIn(f.APP,backend.apps)
        self.assertFalse(backend.dataset,"bounded owned test dataset not cleaned after failed plan")
        self.assertIn("CLEANUP_OWNED_ZFS_DATASET_ABSENT",receipt["native_product"]["events"])

    def test_foreign_app_denied_before_any_native_write(self):
        backend=NativeDouble()
        backend.apps[f.APP]={
            "config":f.compose("sha256:"+"a"*64),
            "observable":{"id":f.APP,"state":"RUNNING","active_workloads":{"containers":1}},
        }
        receipt={"evidence":{}}
        with self.assertRaises(f.NativeQualificationError):
            f.run(
                backend.call,backend.job,
                "127.0.0.1:15431/compass-guest-fixture@sha256:"+"a"*64,
                receipt,state_timeout=1,
            )
        self.assertFalse(backend.dataset)
        self.assertNotIn("pool.dataset.create",backend.history)
        self.assertNotIn("app.delete",backend.history)


if __name__=="__main__":
    unittest.main()
