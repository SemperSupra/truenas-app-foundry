#!/usr/bin/env python3
"""Cheap negative/source contract tests; no TrueNAS, Docker, or credentials."""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools/export_minecraft_paper_t6_control.py"
spec = importlib.util.spec_from_file_location("minecraft_exporter", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
REF = "a" * 40
EVIDENCE = {
    "result": "PASS",
    "upstream": {
        "ref": "532236882212e8c5e51d5b49cfe2c6ce3dd5675e",
        "app": "community/minecraft",
    },
    "compose_sha256": "1" * 64,
}


class TestControl(unittest.TestCase):
    def setUp(self):
        self.head = mock.patch.object(mod.subprocess, "check_output", side_effect=[
            REF, "800aca038ded29e6a91bfc4c1b1fe2d2199182e8",
        ])
        self.head.start()
        self.addCleanup(self.head.stop)

    def test_exact_candidate_is_explicitly_not_runtime_pass(self):
        control = mod.source_control(REF, copy.deepcopy(EVIDENCE))
        self.assertEqual(control["target"]["truenas_version"], "25.04.1")
        self.assertEqual(control["runtime"]["paper_version"], "1.21.11")
        self.assertFalse(control["evidence"]["live_minecraft_server_qualified"])
        self.assertFalse(control["evidence"]["physical_truenas_qualified"])
        self.assertFalse(control["secrets_captured"])
        identity = dict(control)
        digest = identity.pop("control_sha256")
        self.assertEqual(digest, mod.digest(identity))

    def test_no_source_pass_refused(self):
        evidence = dict(EVIDENCE, result="INCONCLUSIVE")
        with self.assertRaisesRegex(mod.ControlError, "render did not pass"):
            mod.source_control(REF, evidence)

    def test_wrong_upstream_ref_refused(self):
        evidence = copy.deepcopy(EVIDENCE)
        evidence["upstream"]["ref"] = "0" * 40
        with self.assertRaisesRegex(mod.ControlError, "upstream identity"):
            mod.source_control(REF, evidence)

    def test_no_compose_digest_refused(self):
        evidence = dict(EVIDENCE, compose_sha256="float")
        with self.assertRaisesRegex(mod.ControlError, "Compose digest"):
            mod.source_control(REF, evidence)

    def test_invalid_requested_ref_refused(self):
        with self.assertRaisesRegex(mod.ControlError, "immutable"):
            mod.source_control("main", EVIDENCE)


class TestValues(unittest.TestCase):
    def mutate(self, path, updater, reason):
        data = yaml.safe_load(mod.VALUES.read_text(encoding="utf-8"))
        updater(data)
        with tempfile.TemporaryDirectory() as directory:
            changed = pathlib.Path(directory) / "values.yaml"
            changed.write_text(yaml.safe_dump(data), encoding="utf-8")
            with mock.patch.object(mod, "VALUES", changed):
                with mock.patch.object(mod.subprocess, "check_output", side_effect=[
                    REF, "800aca038ded29e6a91bfc4c1b1fe2d2199182e8",
                ]):
                    with self.assertRaisesRegex(mod.ControlError, reason):
                        mod.source_control(REF, EVIDENCE)

    def test_world_readonly_refused(self):
        self.mutate(None, lambda d: d["storage"]["additional_storage"][0].update(read_only=True), "world must be writable")

    def test_world_mount_removed_refused(self):
        self.mutate(None, lambda d: d["storage"].update(additional_storage=[]), "world mount required")

    def test_online_mode_disabled_refused(self):
        self.mutate(None, lambda d: d["minecraft"].update(online_mode=False), "EULA/online-mode")

    def test_owner_identity_changed_refused(self):
        self.mutate(None, lambda d: d["minecraft"]["additional_envs"][0].update(value="false"), "ownership metadata")

    def test_paper_version_changed_refused(self):
        self.mutate(None, lambda d: d["minecraft"].update(version="latest"), "Paper source version")

    def test_host_network_refused(self):
        self.mutate(None, lambda d: d["network"].update(host_network=True), "host networking")


if __name__ == "__main__":
    unittest.main()
