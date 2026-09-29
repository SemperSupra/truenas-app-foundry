from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_litellm_candidate.py"
SPEC = importlib.util.spec_from_file_location("validate_litellm_candidate", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LiteLlmCandidateTests(unittest.TestCase):
    def test_authoritative_candidate_sources_are_consistent(self):
        result = MODULE.validate()
        self.assertEqual("PASS", result["result"])
        self.assertEqual("v1.103.0", result["upstream_version"])
        self.assertEqual("2.3.11", result["truenas_lib_version"])
        self.assertEqual("S1", result["secret_tier"])
        self.assertFalse(result["management_credentials_allowed"])
        self.assertFalse(result["moving_tags_allowed"])
        self.assertTrue(result["appliance_digest"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
