import copy
import json
from pathlib import Path
import unittest

from tools.foundry_native_compute import inspect_native
from tools.foundry_workload_artifact import WorkloadContractError

PROFILE = json.loads((Path(__file__).resolve().parents[1] /
    ".foundry/native-compute/25.10.7-source.json").read_text(encoding="utf-8"))
VM = ["vm.query", "vm.device.nic_attach_choices", "vm.start", "vm.stop",
      "vm.restart", "vm.delete"]
CT = ["virt.instance.query", "virt.global.bridge_choices",
      "virt.instance.start", "virt.instance.stop", "virt.instance.restart",
      "virt.instance.delete"]


class NativeComputeTests(unittest.TestCase):
    def check(self, adapter="truenas-native-vm", version="25.10.7",
              operation="ENSURE_RUNNING", methods=None, profile=None):
        return inspect_native(PROFILE if profile is None else profile,
                              adapter=adapter, version=version,
                              operation=operation,
                              observed_methods=VM if methods is None else methods)

    def test_native_vm_methods_are_source_only(self):
        for op in ("ENSURE_RUNNING", "ENSURE_STOPPED", "RESTART", "ENSURE_ABSENT"):
            with self.subTest(op=op):
                r = self.check(operation=op)
                self.assertEqual(r["status"], "SOURCE_COMPATIBLE_ONLY")
                for field in ("apply_authorized", "runtime_qualified",
                              "ownership_verified", "storage_delete_authorized"):
                    self.assertIs(r[field], False)

    def test_legacy_container_family_and_retain_data_hold(self):
        for op in ("ENSURE_RUNNING", "ENSURE_STOPPED", "RESTART"):
            self.assertEqual(self.check(adapter="truenas-legacy-container",
                operation=op, methods=CT)["status"], "SOURCE_COMPATIBLE_ONLY")
        r = self.check(adapter="truenas-legacy-container",
                       operation="ENSURE_ABSENT", methods=CT)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("RETAIN_DATA_DELETE_NOT_QUALIFIED", r["blockers"])

    def test_other_exact_versions_not_inherited(self):
        for v in ("25.04.1", "25.04.2.6", "26.0.0-BETA.3", "25.10", "latest"):
            self.assertEqual(self.check(version=v)["status"], "BLOCKED")

    def test_missing_and_cross_family_methods(self):
        for methods in ([], CT, ["vm.query", "vm.start"], VM[:-1]):
            op = "ENSURE_ABSENT" if methods == VM[:-1] else "ENSURE_RUNNING"
            self.assertEqual(self.check(methods=methods, operation=op)["status"], "BLOCKED")

    def test_unsupported_native_container_and_unmapped_ops(self):
        self.assertEqual(self.check(adapter="truenas-native-container")["status"], "BLOCKED")
        self.assertEqual(self.check(operation="UPGRADE")["status"], "BLOCKED")

    def test_profile_cannot_grant_authority_or_switch_methods(self):
        p = copy.deepcopy(PROFILE)
        p["apply_authorized"] = True
        self.assertEqual(self.check(profile=p)["status"], "BLOCKED")
        p = copy.deepcopy(PROFILE)
        p["profiles"]["truenas-native-vm"]["operations"]["ENSURE_RUNNING"] = "app.start"
        self.assertEqual(self.check(profile=p, methods=VM + ["app.start"])["status"], "BLOCKED")

    def test_observation_must_be_explicit(self):
        with self.assertRaises(WorkloadContractError):
            self.check(methods="vm.query")


if __name__ == "__main__":
    unittest.main()
