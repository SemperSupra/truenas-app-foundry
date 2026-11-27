"""Actual filesystem fixture for disposable runtime and durable state.

Only run-owned TemporaryDirectory storage. No native hypervisor, TrueNAS host,
network, secrets or application payload. Reuses existing source contracts;
does not claim native lifecycle qualification or provide a deployment actuator.
"""
import copy
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.foundry_retained_state import inspect_replacement, state_contract
from tools.foundry_workload_artifact import (
    WorkloadContractError, canonical_digest, inspect_artifact,
)
from tools.test_foundry_retained_state import layout
from tools.test_foundry_workload_artifact import fixture


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def file_digest(path):
    return sha(path.read_bytes())


def storage_id(path):
    stat = path.stat()
    return canonical_digest({"device": stat.st_dev, "inode": stat.st_ino})


def build_artifact(version, state):
    payload = ("fictional runtime version " + version + "\n").encode("ascii")
    artifact = fixture()
    artifact["build_sha256"] = sha(payload)
    artifact["artifact"]["sha256"] = sha(payload)
    artifact["data"]["contract_sha256"] = canonical_digest(state_contract(state))
    return artifact, payload


def stage(root, artifact, payload):
    root.mkdir()
    if sha(payload) != artifact["artifact"]["sha256"]:
        raise WorkloadContractError("fixture artifact bytes do not match")
    (root / "system").write_bytes(payload)
    return root


def observe(runtime, bindings, artifact):
    if file_digest(runtime / "system") != artifact["artifact"]["sha256"]:
        raise WorkloadContractError("observed fixture runtime bytes do not match")
    return {
        "materialization_identity": inspect_artifact(artifact)["materialization_identity"],
        "runtime_storage_sha256": storage_id(runtime),
        "state": "stable",
        "bindings": [
            {"slot": slot, "storage_sha256": storage_id(path),
             "checkpoint_sha256": file_digest(path / "sentinel")}
            for slot, path in sorted(bindings.items())
        ],
    }


def backup_and_restore(root, bindings, artifact):
    # Independent copy and restore readback of real controlled bytes. Only the
    # digest of the tiny sentinel map leaves the test; no production backup.
    saved, restored = root / "backup", root / "restore"
    saved.mkdir()
    restored.mkdir()
    expected = {slot: file_digest(path / "sentinel") for slot, path in bindings.items()}
    for slot, path in bindings.items():
        shutil.copytree(path, saved / slot)
        shutil.copytree(saved / slot, restored / slot)
    backup = {slot: file_digest(saved / slot / "sentinel") for slot in bindings}
    recovery = {slot: file_digest(restored / slot / "sentinel") for slot in bindings}
    if backup != expected or recovery != expected:
        raise WorkloadContractError("controlled restore readback differs")
    if any(storage_id(restored / slot) == storage_id(path)
           for slot, path in bindings.items()):
        raise WorkloadContractError("restore aliases original storage")
    return {
        "previous_artifact_sha256": inspect_artifact(artifact)["materialization_identity"],
        "backup_receipt_sha256": canonical_digest(backup),
        "restore_receipt_sha256": canonical_digest(recovery),
        "state_contract_sha256": artifact["data"]["contract_sha256"],
    }


def planned_action(observed, desired):
    # Fixture-only plan: compare actual observed materialization identity, not
    # a real native lifecycle planner or apply authority.
    return ("NOOP" if observed["materialization_identity"] ==
            inspect_artifact(desired)["materialization_identity"] else "REPLACE")


class RetainedFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="foundry-state-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.layout = layout()
        self.previous, self.old_bytes = build_artifact("1", self.layout)
        self.desired, self.new_bytes = build_artifact("2", self.layout)
        self.bindings = {}
        for slot, data in (("user-config", b"fictional setting = enabled\n"),
                           ("user-files", b"fictional user file\n")):
            directory = self.root / slot
            directory.mkdir()
            (directory / "sentinel").write_bytes(data)
            self.bindings[slot] = directory
        self.old = stage(self.root / "runtime-1", self.previous, self.old_bytes)
        self.before = observe(self.old, self.bindings, self.previous)

    def test_replace_repeat_noop_and_rollback_real_bytes(self):
        self.assertEqual(planned_action(self.before, self.desired), "REPLACE")
        rec = backup_and_restore(self.root, self.bindings, self.previous)
        # Independent deterministic rebuild in a new directory, before retiring
        # the old one (avoid inode reuse masquerading as identity continuity).
        candidate = stage(self.root / "runtime-2", self.desired, self.new_bytes)
        rebuilt, repeat_bytes = build_artifact("2", copy.deepcopy(self.layout))
        repeat = stage(self.root / "runtime-repeat", rebuilt, repeat_bytes)
        self.assertEqual(file_digest(candidate / "system"), file_digest(repeat / "system"))
        self.assertEqual(inspect_artifact(self.desired), inspect_artifact(rebuilt))
        shutil.rmtree(self.old)
        self.assertFalse(self.old.exists())
        after = observe(candidate, self.bindings, self.desired)
        result = inspect_replacement(self.previous, self.desired, self.layout,
                                     self.before, after, rec)
        self.assertTrue(result["runtime_changed"])
        self.assertEqual(result["retained_slots_unchanged"], 2)
        self.assertFalse(result["apply_authorized"])
        before_repeat = observe(candidate, self.bindings, self.desired)
        self.assertEqual(planned_action(before_repeat, self.desired), "NOOP")
        self.assertEqual(before_repeat, observe(candidate, self.bindings, self.desired))
        # Recreate prior runtime and verify retained state. Back up current
        # state separately, rather than restoring old data over user writes.
        rollback_dir = self.root / "rollback-recovery"
        rollback_dir.mkdir()
        rollback_rec = backup_and_restore(rollback_dir, self.bindings, self.desired)
        prior = stage(self.root / "runtime-rollback", self.previous, self.old_bytes)
        shutil.rmtree(candidate)
        rolled_back = observe(prior, self.bindings, self.previous)
        rollback = inspect_replacement(self.desired, self.previous, self.layout,
                                       after, rolled_back, rollback_rec)
        self.assertTrue(rollback["runtime_changed"])
        self.assertEqual(rolled_back["bindings"], self.before["bindings"])
        self.assertEqual(planned_action(rolled_back, self.previous), "NOOP")

    def test_actual_retained_data_drift_rejected(self):
        rec = backup_and_restore(self.root, self.bindings, self.previous)
        candidate = stage(self.root / "runtime-2", self.desired, self.new_bytes)
        (self.bindings["user-files"] / "sentinel").write_bytes(b"unexpected change")
        after = observe(candidate, self.bindings, self.desired)
        with self.assertRaisesRegex(WorkloadContractError, "checkpoint drift"):
            inspect_replacement(self.previous, self.desired, self.layout,
                                self.before, after, rec)

    def test_actual_runtime_corruption_rejected(self):
        candidate = stage(self.root / "runtime-2", self.desired, self.new_bytes)
        (candidate / "system").write_bytes(b"corrupted fixture")
        with self.assertRaisesRegex(WorkloadContractError, "runtime bytes do not match"):
            observe(candidate, self.bindings, self.desired)

    def test_actual_retained_binding_alias_rejected(self):
        rec = backup_and_restore(self.root, self.bindings, self.previous)
        candidate = stage(self.root / "runtime-2", self.desired, self.new_bytes)
        alias = dict(self.bindings)
        alias["user-files"] = alias["user-config"]
        after = observe(candidate, alias, self.desired)
        with self.assertRaisesRegex(WorkloadContractError, "aliased"):
            inspect_replacement(self.previous, self.desired, self.layout,
                                self.before, after, rec)


if __name__ == "__main__":
    unittest.main()
