#!/usr/bin/env python3
import copy
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
            "methods": ["app.query", "app.create", "app.update", "app.redeploy"]
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
        self.assertFalse(got["apply_qualified"])

    def test_beta3_has_exact_profile_but_retains_t3_runtime_gate(self):
        got = mod.discover(observation("TrueNAS-26.0.0-BETA.3"), REGISTRY)
        self.assertEqual(got["status"], "EXACT_PROFILE")
        self.assertEqual(
            got["profile"],
            ".foundry/truenas-compatibility/26.0.0-BETA.3-materialization.json",
        )
        self.assertEqual(got["accepted_runtime_rung"], "T3")
        self.assertFalse(got["apply_qualified"])

    def test_registry_profile_paths_exist(self):
        for target in REGISTRY["targets"]:
            profile = target.get("profile")
            if profile:
                self.assertTrue((HERE.parent / profile).is_file(), profile)

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
