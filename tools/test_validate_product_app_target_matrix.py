import copy
import json
import pathlib
import tempfile
import unittest

from validate_product_app_target_matrix import MatrixError, validate


VERSIONS = ["25.04.1", "25.04.2.6", "25.10.7", "26.0.0-BETA.3"]


def registry():
    return {"targets": [{"version": v} for v in VERSIONS]}


def cell(status="OPEN"):
    return {"status": status, "evidence": None}


def matrix():
    return {
        "schema": "truenas-foundry-product-target-matrix/v1",
        "required_target_versions": VERSIONS,
        "entries": [
            {
                "id": "demo",
                "classification": "product",
                "required_for_all_products_claim": True,
                "source": {"kind": "foundry-candidate", "candidate_path": "candidates/demo/candidate.json"},
                "target_status": {v: cell() for v in VERSIONS},
            }
        ],
        "all_required_product_cells_qualified": False,
    }


def pass_evidence():
    return {
        "run_id": 1,
        "artifact_id": 2,
        "artifact_digest": "sha256:" + "a" * 64,
        "profile_identity": "profile-sha",
        "source_identity": "source-sha",
        "classification": "SUPPORTED",
        "oracle_satisfied": True,
        "f0_f5_complete": True,
    }


class MatrixTests(unittest.TestCase):
    def repo(self):
        td = tempfile.TemporaryDirectory()
        root = pathlib.Path(td.name)
        p = root / "candidates/demo"
        p.mkdir(parents=True)
        (p / "candidate.json").write_text("{}\n", encoding="utf-8")
        return td, root

    def test_open_matrix_passes_contract_without_support_claim(self):
        td, root = self.repo()
        self.addCleanup(td.cleanup)
        result = validate(matrix(), registry(), root)
        self.assertFalse(result["all_required_product_cells_qualified"])

    def test_new_target_invalidates_stale_matrix(self):
        td, root = self.repo()
        self.addCleanup(td.cleanup)
        reg = registry()
        reg["targets"].append({"version": "27.0.0"})
        with self.assertRaises(MatrixError):
            validate(matrix(), reg, root)

    def test_unregistered_candidate_fails_closed(self):
        td, root = self.repo()
        self.addCleanup(td.cleanup)
        p = root / "candidates/other"
        p.mkdir(parents=True)
        (p / "candidate.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(MatrixError):
            validate(matrix(), registry(), root)

    def test_pass_requires_complete_runtime_receipt(self):
        td, root = self.repo()
        self.addCleanup(td.cleanup)
        m = matrix()
        m["entries"][0]["target_status"][VERSIONS[0]] = {
            "status": "PASS",
            "evidence": {"run_id": 1},
        }
        with self.assertRaises(MatrixError):
            validate(m, registry(), root)

    def test_all_product_cells_true_only_when_every_cell_passes(self):
        td, root = self.repo()
        self.addCleanup(td.cleanup)
        m = matrix()
        for v in VERSIONS:
            m["entries"][0]["target_status"][v] = {
                "status": "PASS",
                "evidence": pass_evidence(),
            }
        m["all_required_product_cells_qualified"] = True
        result = validate(m, registry(), root)
        self.assertTrue(result["all_required_product_cells_qualified"])


if __name__ == "__main__":
    unittest.main()
