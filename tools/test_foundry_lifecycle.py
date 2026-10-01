#!/usr/bin/env python3
import copy
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "foundry_lifecycle", HERE / "foundry_lifecycle.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)

TARGET = MOD.target
REGISTRY = TARGET.load_registry(HERE.parent / ".foundry/truenas-target-tracks.json")


def observation(state="RUNNING", ownership="owned", present=True, workloads=1):
    return {
        "system": {"version": "TrueNAS-25.04.1", "platform": "linux-amd64"},
        "capabilities": {
            "methods": [
                "app.query",
                "app.config",
                "app.start",
                "app.stop",
                "app.redeploy",
                "app.delete",
            ]
        },
        "ownership": {"state": ownership},
        "app": {
            "name": "probe-app",
            "present": present,
            "state": state,
            "materialization_identity": "sha256:desired" if present else None,
            "active_workloads": workloads,
        },
    }


def intent(operation, policy=None):
    value = {
        "schema": MOD.SCHEMA,
        "operation": operation,
        "app_name": "probe-app",
        "materialization_identity": "sha256:desired",
    }
    if policy is not None:
        value["delete_policy"] = policy
    return value


def qualified_registry():
    registry = copy.deepcopy(REGISTRY)
    target = next(x for x in registry["targets"] if x["version"] == "25.04.1")
    target["apply_qualified"] = True
    return registry


class LifecycleTests(unittest.TestCase):
    def test_real_registry_blocks_mutation_until_apply_qualified(self):
        got = MOD.plan(observation(), intent("STOP"), REGISTRY)
        self.assertEqual(got["status"], "BLOCKED")
        self.assertIn("target profile is not apply-qualified", got["blockers"])

    def test_stop_and_start_converge_to_noop(self):
        registry = qualified_registry()
        self.assertEqual(
            MOD.plan(observation("RUNNING"), intent("STOP"), registry)["action"],
            "STOP",
        )
        self.assertEqual(
            MOD.plan(observation("STOPPED", workloads=0), intent("STOP"), registry)["action"],
            "NOOP",
        )
        self.assertEqual(
            MOD.plan(observation("STOPPED", workloads=0), intent("START"), registry)["action"],
            "START",
        )
        self.assertEqual(
            MOD.plan(observation("RUNNING", workloads=1), intent("START"), registry)["action"],
            "NOOP",
        )

    def test_redeploy_requires_owned_identity(self):
        registry = qualified_registry()
        self.assertEqual(
            MOD.plan(observation(), intent("REDEPLOY"), registry)["action"],
            "REDEPLOY",
        )
        foreign = observation(ownership="foreign")
        self.assertEqual(MOD.plan(foreign, intent("REDEPLOY"), registry)["status"], "BLOCKED")

    def test_delete_is_retain_data_only(self):
        registry = qualified_registry()
        got = MOD.plan(observation(), intent("DELETE", "retain-data"), registry)
        self.assertEqual(got["action"], "DELETE")
        self.assertFalse(got["preconditions"]["delete_owned_storage_allowed"])
        with self.assertRaises(MOD.LifecycleError):
            MOD.plan(observation(), intent("DELETE", "delete-data"), registry)

    def test_verify_stop_start_redeploy_and_delete(self):
        registry = qualified_registry()
        self.assertEqual(
            MOD.verify(observation("STOPPED", workloads=0), intent("STOP"), registry)["status"],
            "VERIFIED",
        )
        self.assertEqual(
            MOD.verify(observation("RUNNING", workloads=1), intent("START"), registry)["status"],
            "VERIFIED",
        )
        self.assertEqual(
            MOD.verify(observation("RUNNING", workloads=1), intent("REDEPLOY"), registry)["status"],
            "VERIFIED",
        )
        absent = observation("ABSENT", ownership="absent", present=False, workloads=0)
        self.assertEqual(
            MOD.verify(absent, intent("DELETE", "retain-data"), registry)["status"],
            "VERIFIED",
        )

    def test_missing_method_fails_closed(self):
        registry = qualified_registry()
        obs = observation()
        obs["capabilities"]["methods"].remove("app.stop")
        got = MOD.plan(obs, intent("STOP"), registry)
        self.assertEqual(got["status"], "BLOCKED")
        self.assertIn("app.stop", got["missing_methods"])


if __name__ == "__main__":
    unittest.main()
