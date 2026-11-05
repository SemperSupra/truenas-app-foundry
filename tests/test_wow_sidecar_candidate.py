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

class WowSidecarCandidateTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads(CANDIDATE.read_text(encoding="utf-8"))

    def test_render_qualified_candidate_is_hil_eligible_but_not_hil_or_cutover_qualified(self):
        result = MODULE.validate(copy.deepcopy(self.value))
        self.assertEqual(result["result"], "PASS")
        self.assertIsNotNone(result["registry_reference"])
        self.assertTrue(result["permissions_helper_pinned"])
        self.assertTrue(result["hil_eligible"])
        self.assertFalse(result["private_hil_claimed"])
        self.assertFalse(result["cutover_claimed"])

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
        value["permissions_helper"]["reference"] = None
        with self.assertRaisesRegex(MODULE.ValidationError, "immutable permissions helper"):
            MODULE.validate(value)

    def test_render_gate_requires_exact_durable_evidence(self):
        value = copy.deepcopy(self.value)
        value["public_render_evidence"]["compose_sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.ValidationError, "rendered Compose digest drift"):
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
