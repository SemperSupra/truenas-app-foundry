from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_wow_sidecar_candidate.py"
SPEC = importlib.util.spec_from_file_location("validate_wow_sidecar_candidate", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CANDIDATE = ROOT / "candidates" / "wow-sidecar-app" / "candidate.json"

def qualify(value):
    value["phase"] = "render-qualified-private-hil-pending"
    value["gates"]["public_app_render_qualified"] = True
    value["gates"]["hil_eligible"] = True
    value["public_render_evidence"] = {
        "schema": "wow-sidecar-public-app-qualification/v2",
        "result": "PASS",
        "run": 99999999999,
        "qualified_head": "a" * 40,
        "compose_sha256": "b" * 64,
        "ghcr_anonymous_pull": True,
        "seed_behavior": "PASS:create-once/preserve/fail-partial",
        "full_compose_behavior": "PASS:permissions/seed/worker",
        "materializer_commit": value["truenas_source"]["commit"],
        "wow_image": value["container"]["registry_reference"],
        "permissions_helper": value["permissions_helper"]["reference"],
        "worker_rootfs_read_only": True,
        "seed_rootfs_read_only": False,
        "seed_inline_config_mode": "0444",
        "persisted_managed_config_mode": "0400",
        "corrects_falsifier_runs": [36791533322, 36792356264],
    }
    return value

class WowSidecarCandidateTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads(CANDIDATE.read_text(encoding="utf-8"))

    def test_corrected_candidate_is_promoted_only_from_strengthened_render_evidence(self):
        result = MODULE.validate(copy.deepcopy(self.value))
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["phase"], "render-qualified-private-hil-pending")
        self.assertIsNotNone(result["registry_reference"])
        self.assertTrue(result["permissions_helper_pinned"])
        self.assertTrue(result["hil_eligible"])
        self.assertFalse(result["private_hil_claimed"])
        self.assertFalse(result["cutover_claimed"])
        evidence = self.value["public_render_evidence"]
        self.assertEqual(evidence["run"], 36793252392)
        self.assertEqual(evidence["qualified_head"], "6c4c20efe98048bc496e68894f249a2a227b92c6")
        self.assertEqual(evidence["corrects_falsifier_runs"], [36791533322, 36792356264])
        self.assertEqual(self.value["render_falsification"]["run"], 36791533322)
        self.assertEqual(self.value["render_falsification_followup"]["run"], 36792356264)

    def test_seed_rootfs_exception_is_narrow_and_worker_remains_read_only(self):
        contract = self.value["truenas_contract"]
        self.assertTrue(contract["worker_root_filesystem_read_only"])
        self.assertTrue(contract["seed_root_filesystem_writable_for_inline_configs"])
        self.assertEqual(
            contract["seed_rootfs_exception_scope"],
            "one-shot non-root network-disabled cap-drop-all no-new-privileges helper only",
        )
        self.assertEqual(contract["seed_inline_config_mode"], "0444")
        self.assertEqual(contract["persisted_managed_config_mode"], "0400")
        self.assertEqual(
            contract["seed_inline_config_scope"],
            "ephemeral one-shot network-disabled seed inputs only",
        )
        self.assertEqual(self.value["render_falsification_followup"]["run"], 36792356264)

    def test_hil_cannot_be_claimed_without_render_qualification(self):
        value = copy.deepcopy(self.value)
        value["phase"] = "image-published-render-unqualified"
        value["gates"]["public_app_render_qualified"] = False
        value["gates"]["hil_eligible"] = False
        value["gates"]["private_truenas_hil_qualified"] = True
        with self.assertRaisesRegex(MODULE.ValidationError, "private HIL cannot precede"):
            MODULE.validate(value)

    def test_registry_state_requires_exact_ghcr_digest(self):
        value = copy.deepcopy(self.value)
        value["container"]["registry_reference"] = "ghcr.io/sempersupra/wow-sidecar:latest"
        with self.assertRaisesRegex(MODULE.ValidationError, "exact GHCR digest"):
            MODULE.validate(value)

    def test_render_gate_requires_immutable_permissions_helper(self):
        value = copy.deepcopy(self.value)
        qualify(value)
        value["permissions_helper"]["reference"] = None
        with self.assertRaisesRegex(MODULE.ValidationError, "immutable permissions helper"):
            MODULE.validate(value)

    def test_render_gate_requires_exact_durable_evidence(self):
        value = copy.deepcopy(self.value)
        qualify(value)
        value["public_render_evidence"]["compose_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(MODULE.ValidationError, "rendered Compose digest invalid"):
            MODULE.validate(value)

    def test_runtime_identity_is_fixed_numeric_nonroot(self):
        value = copy.deepcopy(self.value)
        value["container"]["runtime_user"] = "root"
        with self.assertRaisesRegex(MODULE.ValidationError, "runtime user drift"):
            MODULE.validate(value)

    def test_hil_eligibility_is_derived_not_self_asserted(self):
        value = copy.deepcopy(self.value)
        value["phase"] = "image-published-render-unqualified"
        value["gates"]["public_app_render_qualified"] = False
        value["gates"]["hil_eligible"] = True
        with self.assertRaisesRegex(MODULE.ValidationError, "does not match"):
            MODULE.validate(value)

    def test_legacy_or_private_identity_is_rejected(self):
        value = copy.deepcopy(self.value)
        value["claim_boundary"] += " execution-control-private"
        with self.assertRaisesRegex(MODULE.ValidationError, "leaked"):
            MODULE.validate(value)

if __name__ == "__main__":
    unittest.main()
