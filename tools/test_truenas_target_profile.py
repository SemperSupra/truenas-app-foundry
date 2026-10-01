#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "truenas_target_profile", HERE / "truenas_target_profile.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)
REGISTRY = mod.load_registry(HERE.parent / ".foundry" / "truenas-target-tracks.json")


def observation(
    version="TrueNAS-25.04.1",
    ownership="absent",
    present=False,
    identity="",
):
    return {
        "schema_version": 1,
        "system": {"version": version, "platform": "linux-amd64"},
        "capabilities": {
            "methods": [
                "system.version",
                "core.get_methods",
                "app.query",
                "app.config",
                "app.create",
                "app.update",
                "app.redeploy",
                "app.stop",
                "app.start",
                "app.delete",
            ]
        },
        "ownership": {"state": ownership},
        "app": {
            "present": present,
            "state": "RUNNING" if present else "ABSENT",
            "materialization_identity": identity,
            "active_workloads": 1 if present else 0,
        },
    }


DESIRED = {
    "app_name": "example",
    "materialization_identity": "sha256:desired",
    "expected_state": "RUNNING",
    "min_active_workloads": 1,
}


class TargetProfileTests(unittest.TestCase):
    def test_current_deployed_version_resolves_exact_profile(self):
        got = mod.discover(observation(), REGISTRY)
        self.assertEqual(got["status"], "EXACT_PROFILE")
        self.assertEqual(got["observed_version"], "25.04.1")
        self.assertTrue(got["exact_version_match"])
        self.assertFalse(got["apply_qualified"])

    def test_current_stable_resolves_exact_profile_but_is_not_apply_qualified(self):
        got = mod.discover(observation("TrueNAS-25.10.7"), REGISTRY)
        self.assertEqual(got["status"], "EXACT_PROFILE")
        self.assertEqual(
            got["profile"],
            ".foundry/truenas-compatibility/25.10.7-materialization.json",
        )
        self.assertEqual(
            got["middleware_commit"],
            "8ede398839710e56893d88ce85088139d8fab18e",
        )
        self.assertTrue(got["qualification_only"])
        self.assertEqual(got["accepted_runtime_rung"], "T5")
        self.assertFalse(got["apply_qualified"])

    def test_beta3_has_exact_profile_and_retains_t6_runtime_gate(self):
        got = mod.discover(observation("TrueNAS-26.0.0-BETA.3"), REGISTRY)
        self.assertEqual(got["status"], "EXACT_PROFILE")
        self.assertEqual(
            got["profile"],
            ".foundry/truenas-compatibility/26.0.0-BETA.3-materialization.json",
        )
        self.assertEqual(got["accepted_runtime_rung"], "T6")
        self.assertFalse(got["apply_qualified"])

    def test_registry_profile_paths_exist(self):
        for target in REGISTRY["targets"]:
            profile = target.get("profile")
            if profile:
                self.assertTrue((HERE.parent / profile).is_file(), profile)


    def test_registry_binds_exact_profile_blob_and_dependency_contract(self):
        for target in REGISTRY["targets"]:
            profile = target.get("profile")
            contract = target.get("profile_contract")
            self.assertIsInstance(contract, dict, target["version"])
            path = HERE.parent / profile
            raw = path.read_bytes()
            blob_sha = hashlib.sha1(
                f"blob {len(raw)}\0".encode() + raw
            ).hexdigest()
            self.assertEqual(contract["profile_blob_sha"], blob_sha, target["version"])
            self.assertEqual(contract["middleware_commit"], target["middleware_commit"])
            self.assertTrue(contract["source_api_family"])
            self.assertTrue(contract["storage_semantics"])
            self.assertTrue(contract["apps_gate_semantics"])
            self.assertIn("app.create", contract["required_public_methods"])
            self.assertIn("app.delete", contract["required_public_methods"])

    def test_exact_version_alone_does_not_satisfy_profile(self):
        obs = observation("TrueNAS-25.10.7")
        obs["capabilities"]["methods"].remove("app.delete")
        got = mod.discover(obs, REGISTRY)
        self.assertEqual(got["status"], "EXACT_PROFILE_CAPABILITY_MISMATCH")
        self.assertTrue(got["exact_version_match"])
        self.assertFalse(got["profile_contract_match"])
        self.assertIn("app.delete", got["missing_profile_methods"])
        self.assertFalse(got["apply_qualified"])
        self.assertTrue(got["qualification_only"])

    def test_plan_binds_observation_and_exact_profile_identity(self):
        registry = copy.deepcopy(REGISTRY)
        registry["targets"][0]["apply_qualified"] = True
        obs = observation()
        got = mod.plan(obs, DESIRED, registry)
        self.assertEqual(got["status"], "READY")
        self.assertEqual(got["action"], "CREATE")
        self.assertEqual(got["observation_sha256"], mod.canonical_sha256(obs))
        self.assertEqual(
            got["profile_identity_sha256"],
            got["target"]["profile_identity_sha256"],
        )
        self.assertTrue(got["preconditions"]["reobserve_profile_contract_before_apply"])
        self.assertTrue(got["preconditions"]["require_observation_sha256_match_before_apply"])
        self.assertTrue(got["preconditions"]["require_profile_identity_sha256_match_before_apply"])

    def test_exact_nightly_is_never_promoted_from_family_match(self):
        got = mod.discover(
            observation("TrueNAS-26.0.0-MASTER+20260929-020101"), REGISTRY
        )
        self.assertEqual(got["status"], "FUTURE_TRACK_UNQUALIFIED")
        self.assertFalse(got["exact_version_match"])
        self.assertTrue(got["qualification_only"])

    def test_unknown_build_fails_closed(self):
        got = mod.discover(observation("TrueNAS-99.1.2"), REGISTRY)
        self.assertEqual(got["status"], "UNKNOWN_TARGET")
        self.assertFalse(got["apply_qualified"])

    def test_plan_blocks_until_exact_profile_is_apply_qualified(self):
        got = mod.plan(observation(), DESIRED, REGISTRY)
        self.assertEqual(got["status"], "BLOCKED")
        self.assertIn("target profile is not apply-qualified", got["blockers"])

    def test_plan_blocks_foreign_state_even_if_registry_were_qualified(self):
        registry = copy.deepcopy(REGISTRY)
        registry["targets"][0]["apply_qualified"] = True
        got = mod.plan(
            observation(ownership="foreign", present=True), DESIRED, registry
        )
        self.assertEqual(got["action"], "BLOCKED")
        self.assertTrue(
            any("foreign/unowned" in item for item in got["blockers"])
        )

    def test_plan_converges_create_update_noop_when_profile_is_qualified(self):
        registry = copy.deepcopy(REGISTRY)
        registry["targets"][0]["apply_qualified"] = True
        self.assertEqual(
            mod.plan(observation(), DESIRED, registry)["action"], "CREATE"
        )
        self.assertEqual(
            mod.plan(
                observation(
                    ownership="owned", present=True, identity="sha256:old"
                ),
                DESIRED,
                registry,
            )["action"],
            "UPDATE",
        )
        self.assertEqual(
            mod.plan(
                observation(
                    ownership="owned",
                    present=True,
                    identity="sha256:desired",
                ),
                DESIRED,
                registry,
            )["action"],
            "NOOP",
        )

    def test_verify_requires_owned_running_matching_workload(self):
        got = mod.verify(
            observation(
                ownership="owned",
                present=True,
                identity="sha256:desired",
            ),
            DESIRED,
            REGISTRY,
        )
        self.assertEqual(got["status"], "VERIFIED")

        bad = observation(
            ownership="owned", present=True, identity="sha256:other"
        )
        self.assertEqual(
            mod.verify(bad, DESIRED, REGISTRY)["status"], "VERIFY_FAILED"
        )


if __name__ == "__main__":
    unittest.main()
