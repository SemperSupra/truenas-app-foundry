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
REGISTRY = TARGET.load_registry(HERE.parent / ".foundry" / "truenas-target-tracks.json")

PROFILE_METHODS = [
    "system.version",
    "app.query",
    "app.config",
    "app.create",
    "app.update",
    "app.redeploy",
    "app.stop",
    "app.start",
    "app.delete",
]


def observation(
    *,
    state="RUNNING",
    ownership="owned",
    present=True,
    workloads=1,
    custom_app=True,
    catalog_version=None,
    upgrade_available=None,
    operation_state="stable",
    completed_tokens=None,
):
    app = {
        "name": "probe-app",
        "present": present,
        "state": state if present else "ABSENT",
        "materialization_identity": "sha256:desired" if present else "",
        "active_workloads": workloads if present else 0,
        "custom_app": custom_app if present else None,
    }
    if catalog_version is not None:
        app["catalog_version"] = catalog_version
    if upgrade_available is not None:
        app["upgrade_available"] = upgrade_available
    return {
        "schema_version": 1,
        "system": {"version": "TrueNAS-25.04.1", "platform": "linux-amd64"},
        "capabilities": {
            "bootstrap_probes": {"core.get_methods": True},
            "methods": PROFILE_METHODS + ["app.upgrade"],
        },
        "ownership": {"state": ownership},
        "app": app,
        "operation": {
            "state": operation_state,
            "completed_tokens": list(completed_tokens or []),
        },
    }


def intent(
    operation,
    *,
    adapter="foundry-custom",
    token=None,
    delete_policy=None,
    desired_catalog_version=None,
):
    value = {
        "schema": MOD.SCHEMA,
        "operation": operation,
        "adapter": adapter,
        "app_name": "probe-app",
        "materialization_identity": "sha256:desired",
    }
    if token is not None:
        value["operation_token"] = token
    if delete_policy is not None:
        value["delete_policy"] = delete_policy
    if desired_catalog_version is not None:
        value["desired_catalog_version"] = desired_catalog_version
    return value


def qualified_registry():
    registry = copy.deepcopy(REGISTRY)
    target = next(x for x in registry["targets"] if x["version"] == "25.04.1")
    target["apply_qualified"] = True
    return registry


class LifecycleV2Tests(unittest.TestCase):
    def test_real_registry_still_blocks_mutation(self):
        got = MOD.plan(
            observation(),
            intent("ENSURE_STOPPED"),
            REGISTRY,
        )
        self.assertEqual(got["status"], "BLOCKED")
        self.assertIn("target profile is not apply-qualified", got["blockers"])

    def test_failed_bootstrap_probe_blocks_lifecycle(self):
        registry = qualified_registry()
        obs = observation()
        obs["capabilities"]["bootstrap_probes"]["core.get_methods"] = False
        got = MOD.plan(obs, intent("ENSURE_RUNNING"), registry)
        self.assertEqual((got["status"], got["action"]), ("BLOCKED", "BLOCKED"))
        self.assertTrue(
            any("bootstrap probes=core.get_methods" in item for item in got["blockers"])
        )

    def test_running_and_stopped_desired_state_converge_to_noop(self):
        registry = qualified_registry()
        running = MOD.plan(observation(), intent("ENSURE_RUNNING"), registry)
        self.assertEqual((running["status"], running["action"]), ("READY", "NOOP"))

        stop = MOD.plan(observation(), intent("ENSURE_STOPPED"), registry)
        self.assertEqual((stop["status"], stop["action"]), ("READY", "STOP"))

        stopped = MOD.plan(
            observation(state="STOPPED", workloads=0),
            intent("ENSURE_STOPPED"),
            registry,
        )
        self.assertEqual((stopped["status"], stopped["action"]), ("READY", "NOOP"))

        start = MOD.plan(
            observation(state="STOPPED", workloads=0),
            intent("ENSURE_RUNNING"),
            registry,
        )
        self.assertEqual((start["status"], start["action"]), ("READY", "START"))

    def test_ambiguous_or_inflight_operation_blocks_retry(self):
        registry = qualified_registry()
        for state in ("ambiguous", "in-flight"):
            got = MOD.plan(
                observation(operation_state=state),
                intent("ENSURE_STOPPED"),
                registry,
            )
            self.assertEqual(got["status"], "BLOCKED")
            self.assertEqual(got["action"], "BLOCKED")
            self.assertTrue(
                any("reconciliation is required" in item for item in got["blockers"])
            )

    def test_ensure_absent_is_idempotent_and_retain_data_only(self):
        registry = qualified_registry()
        delete = MOD.plan(
            observation(),
            intent("ENSURE_ABSENT", delete_policy="retain-data"),
            registry,
        )
        self.assertEqual((delete["status"], delete["action"]), ("READY", "DELETE"))
        self.assertEqual(delete["required_method"], "app.delete")
        self.assertFalse(delete["preconditions"]["delete_owned_storage_allowed"])

        absent = MOD.plan(
            observation(ownership="absent", present=False, workloads=0),
            intent("ENSURE_ABSENT", delete_policy="retain-data"),
            registry,
        )
        self.assertEqual((absent["status"], absent["action"]), ("READY", "NOOP"))

        with self.assertRaises(MOD.LifecycleError):
            MOD.plan(
                observation(),
                intent("ENSURE_ABSENT", delete_policy="delete-data"),
                registry,
            )

    def test_redeploy_token_makes_event_idempotent(self):
        registry = qualified_registry()
        first = MOD.plan(
            observation(),
            intent("REDEPLOY", token="redeploy-001"),
            registry,
        )
        self.assertEqual((first["status"], first["action"]), ("READY", "REDEPLOY"))

        replay = MOD.plan(
            observation(completed_tokens=["redeploy-001"]),
            intent("REDEPLOY", token="redeploy-001"),
            registry,
        )
        self.assertEqual((replay["status"], replay["action"]), ("READY", "NOOP"))

    def test_custom_app_upgrade_is_materialization_update_not_native_upgrade(self):
        registry = qualified_registry()
        with self.assertRaisesRegex(MOD.LifecycleError, "materialization UPDATE"):
            MOD.plan(
                observation(),
                intent(
                    "UPGRADE",
                    adapter="foundry-custom",
                    desired_catalog_version="2.0.0",
                ),
                registry,
            )

    def test_official_catalog_upgrade_uses_native_method_and_converges(self):
        registry = qualified_registry()
        obs = observation(
            custom_app=False,
            catalog_version="1.0.0",
            upgrade_available=True,
        )
        got = MOD.plan(
            obs,
            intent(
                "UPGRADE",
                adapter="official-catalog",
                desired_catalog_version="2.0.0",
            ),
            registry,
        )
        self.assertEqual((got["status"], got["action"]), ("READY", "UPGRADE"))
        self.assertEqual(got["required_method"], "app.upgrade")

        converged = observation(
            custom_app=False,
            catalog_version="2.0.0",
            upgrade_available=False,
        )
        got = MOD.plan(
            converged,
            intent(
                "UPGRADE",
                adapter="official-catalog",
                desired_catalog_version="2.0.0",
            ),
            registry,
        )
        self.assertEqual((got["status"], got["action"]), ("READY", "NOOP"))

    def test_catalog_upgrade_fails_closed_when_no_native_path_is_observed(self):
        registry = qualified_registry()
        obs = observation(
            custom_app=False,
            catalog_version="1.0.0",
            upgrade_available=False,
        )
        got = MOD.plan(
            obs,
            intent(
                "UPGRADE",
                adapter="official-catalog",
                desired_catalog_version="2.0.0",
            ),
            registry,
        )
        self.assertEqual(got["status"], "BLOCKED")
        self.assertTrue(any("no native upgrade" in x for x in got["blockers"]))

    def test_reinstall_is_composition_not_a_blind_special_mutation(self):
        registry = qualified_registry()
        present = MOD.plan(
            observation(),
            intent("REINSTALL", token="reinstall-001", delete_policy="retain-data"),
            registry,
        )
        self.assertEqual(
            (present["status"], present["action"]),
            ("READY", "DELETE_FOR_REINSTALL"),
        )
        self.assertEqual(present["required_method"], "app.delete")

        absent = MOD.plan(
            observation(ownership="absent", present=False, workloads=0),
            intent("REINSTALL", token="reinstall-001", delete_policy="retain-data"),
            registry,
        )
        self.assertEqual(
            (absent["status"], absent["action"]),
            ("READY", "CREATE_HANDOFF"),
        )
        self.assertEqual(absent["handoff"], "truenas_target_profile.plan")

        complete = MOD.plan(
            observation(completed_tokens=["reinstall-001"]),
            intent("REINSTALL", token="reinstall-001", delete_policy="retain-data"),
            registry,
        )
        self.assertEqual((complete["status"], complete["action"]), ("READY", "NOOP"))

    def test_verify_requires_completed_token_for_redeploy_and_reinstall(self):
        registry = qualified_registry()
        bad = MOD.verify(
            observation(),
            intent("REDEPLOY", token="redeploy-002"),
            registry,
        )
        self.assertEqual(bad["status"], "VERIFY_FAILED")
        self.assertTrue(any("operation token" in x for x in bad["failures"]))

        good = MOD.verify(
            observation(completed_tokens=["redeploy-002"]),
            intent("REDEPLOY", token="redeploy-002"),
            registry,
        )
        self.assertEqual(good["status"], "VERIFIED")

    def test_profile_capability_drift_blocks_lifecycle(self):
        registry = qualified_registry()
        obs = observation()
        obs["capabilities"]["methods"].remove("app.delete")
        got = MOD.plan(obs, intent("ENSURE_RUNNING"), registry)
        self.assertEqual(got["status"], "BLOCKED")
        self.assertFalse(got["target"]["profile_contract_match"])

    def test_plan_binds_observation_and_profile_identity(self):
        registry = qualified_registry()
        obs = observation(state="STOPPED", workloads=0)
        got = MOD.plan(obs, intent("ENSURE_RUNNING"), registry)
        self.assertEqual(got["status"], "READY")
        self.assertEqual(got["observation_sha256"], TARGET.canonical_sha256(obs))
        self.assertEqual(
            got["profile_identity_sha256"],
            got["target"]["profile_identity_sha256"],
        )
        self.assertTrue(
            got["preconditions"]["reconcile_ambiguous_operation_before_retry"]
        )

    def test_recipe_names_complete_f0_f5_contract(self):
        recipe = MOD.lifecycle_recipe()
        self.assertEqual(
            [item["stage"] for item in recipe["stages"]],
            ["F0", "F1", "F2", "F3", "F4", "F5"],
        )
        self.assertIn("app.upgrade", recipe["adapter_rule"]["official-catalog"])
        self.assertIn("materialization UPDATE", recipe["adapter_rule"]["foundry-custom"])


if __name__ == "__main__":
    unittest.main()
