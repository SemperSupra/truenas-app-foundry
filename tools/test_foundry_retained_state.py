import copy
import unittest

from tools.foundry_retained_state import (
    inspect_layout, inspect_replacement, state_contract,
)
from tools.foundry_workload_artifact import (
    WorkloadContractError, canonical_digest, inspect_artifact,
)
from tools.test_foundry_workload_artifact import fixture


def d(n):
    return "sha256:" + n * 64


def layout():
    return {
        "schema": "foundry-retained-state-contract/v1",
        "runtime": {"policy": "disposable", "rebuild_recipe_sha256": d("a")},
        "scratch_policy": "disposable", "secret_policy": "external-references-only",
        "configuration_recipe_sha256": d("b"),
        "retained": [
            {"slot": "user-config", "role": "user-config", "ownership": "independent",
             "retention": "retain-data", "schema_sha256": d("c")},
            {"slot": "user-files", "role": "user-files", "ownership": "independent",
             "retention": "retain-data", "schema_sha256": d("d")},
        ],
    }


def scenario():
    state = layout()
    previous = fixture()
    previous["data"]["contract_sha256"] = canonical_digest(state_contract(state))
    desired = copy.deepcopy(previous)
    desired["artifact"]["sha256"] = d("5")
    prior_id = inspect_artifact(previous)["materialization_identity"]
    next_id = inspect_artifact(desired)["materialization_identity"]
    before = {"materialization_identity": prior_id, "runtime_storage_sha256": d("1"),
              "state": "stable", "bindings": [
                  {"slot": "user-config", "storage_sha256": d("2"), "checkpoint_sha256": d("6")},
                  {"slot": "user-files", "storage_sha256": d("3"), "checkpoint_sha256": d("7")},
              ]}
    after = copy.deepcopy(before)
    after["materialization_identity"] = next_id
    after["runtime_storage_sha256"] = d("4")
    recovery = {"previous_artifact_sha256": prior_id, "backup_receipt_sha256": d("8"),
                "restore_receipt_sha256": d("9"),
                "state_contract_sha256": previous["data"]["contract_sha256"]}
    return previous, desired, state, before, after, recovery


class RetainedStateTests(unittest.TestCase):
    def test_disposable_runtime_independent_state(self):
        p, _, s, *_ = scenario()
        r = inspect_layout(p, s)
        self.assertEqual(r["declared_retained_slots"], 2)
        self.assertEqual(r["required_phases"], ["OBSERVE_DISCOVER", "PLAN", "APPLY", "VERIFY"])
        for key in ("reproducibility_verified", "reversibility_verified",
                    "physical_separation_verified", "apply_authorized", "storage_delete_authorized"):
            self.assertIs(r[key], False)

    def test_layout_order_deterministic(self):
        p, _, s, *_ = scenario()
        x = inspect_layout(p, s)
        s["retained"].reverse()
        self.assertEqual(x, inspect_layout(p, s))

    def test_declared_no_retained_slots_is_explicit(self):
        p, _, s, *_ = scenario()
        s["retained"] = []
        p["data"]["contract_sha256"] = canonical_digest(state_contract(s))
        self.assertEqual(inspect_layout(p, s)["declared_retained_slots"], 0)

    def test_reject_runtime_and_retention_drift(self):
        for path, value in (("policy", "persistent"), ("scratch_policy", "retain"),
                            ("secret_policy", "embed")):
            _, _, s, *_ = scenario()
            if path == "policy":
                s["runtime"][path] = value
            else:
                s[path] = value
            with self.assertRaises(WorkloadContractError):
                state_contract(s)
        for field, value in (("ownership", "runtime"), ("retention", "delete"), ("role", "scratch")):
            _, _, s, *_ = scenario()
            s["retained"][0][field] = value
            with self.assertRaises(WorkloadContractError):
                state_contract(s)

    def test_reject_wrong_artifact_contract_or_duplicate_slots(self):
        p, _, s, *_ = scenario()
        p["data"]["contract_sha256"] = d("0")
        with self.assertRaises(WorkloadContractError):
            inspect_layout(p, s)
        s["retained"].append(copy.deepcopy(s["retained"][0]))
        with self.assertRaises(WorkloadContractError):
            state_contract(s)

    def test_replace_preserves_controlled_state_references(self):
        args = scenario()
        r = inspect_replacement(*args)
        self.assertEqual(r["status"], "CONSISTENT_REFERENCES_ONLY")
        self.assertTrue(r["runtime_changed"])
        self.assertEqual(r["retained_slots_unchanged"], 2)
        self.assertFalse(r["recovery_verified"])
        self.assertFalse(r["apply_authorized"])
        self.assertEqual(r, inspect_replacement(*args))

    def test_repeat_same_observation_is_not_new_replacement(self):
        p, _, s, before, _, recovery = scenario()
        r = inspect_replacement(p, p, s, before, before, recovery)
        self.assertFalse(r["runtime_changed"])
        self.assertFalse(r["live_state_verified"])

    def test_reject_missing_state_or_binding_drift_or_alias(self):
        for mutation in ("missing", "storage", "checkpoint", "alias", "same-runtime", "ambiguous"):
            p, n, s, before, after, rec = scenario()
            if mutation == "missing":
                after["bindings"].pop()
            elif mutation == "storage":
                after["bindings"][0]["storage_sha256"] = d("f")
            elif mutation == "checkpoint":
                after["bindings"][0]["checkpoint_sha256"] = d("f")
            elif mutation == "alias":
                after["runtime_storage_sha256"] = after["bindings"][0]["storage_sha256"]
            elif mutation == "same-runtime":
                after["runtime_storage_sha256"] = before["runtime_storage_sha256"]
            else:
                after["state"] = "ambiguous"
            with self.subTest(mutation=mutation), self.assertRaises(WorkloadContractError):
                inspect_replacement(p, n, s, before, after, rec)

    def test_reject_missing_recovery_or_incompatible_target(self):
        p, n, s, before, after, rec = scenario()
        del rec["restore_receipt_sha256"]
        with self.assertRaises(WorkloadContractError):
            inspect_replacement(p, n, s, before, after, rec)
        p, n, s, before, after, rec = scenario()
        n["target"]["version"] = "2.0.0"
        with self.assertRaises(WorkloadContractError):
            inspect_replacement(p, n, s, before, after, rec)


if __name__ == "__main__":
    unittest.main()
