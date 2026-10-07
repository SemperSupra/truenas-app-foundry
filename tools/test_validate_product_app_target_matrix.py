import copy
import json
import pathlib
import tempfile
import unittest

from tools.validate_product_app_target_matrix import MatrixError, validate


VERSIONS = ["25.04.1", "25.04.2.6", "25.10.7", "26.0.0-BETA.3"]


def registry():
    return {"targets": [{"version": v} for v in VERSIONS]}


def cell(status="OPEN"):
    return {"status": status, "evidence": None}


def matrix():
    return {
        "schema": "truenas-foundry-product-target-matrix/v1",
        "required_target_versions": VERSIONS,
        "required_external_product_ids": [],
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

    def test_required_external_product_cannot_be_omitted(self):
        td, root = self.repo()
        self.addCleanup(td.cleanup)
        m = matrix()
        m["required_external_product_ids"] = ["litellm-app"]
        with self.assertRaisesRegex(MatrixError, "required external products omitted"):
            validate(m, registry(), root)

    def test_required_external_product_cannot_masquerade_as_candidate(self):
        td, root = self.repo()
        self.addCleanup(td.cleanup)
        p = root / "candidates/litellm"
        p.mkdir(parents=True)
        (p / "candidate.json").write_text("{}\n", encoding="utf-8")
        m = matrix()
        m["required_external_product_ids"] = ["litellm-app"]
        m["entries"].append({
            "id": "litellm-app",
            "classification": "product",
            "required_for_all_products_claim": True,
            "source": {
                "kind": "foundry-candidate",
                "candidate_path": "candidates/litellm/candidate.json",
            },
            "target_status": {v: cell() for v in VERSIONS},
        })
        with self.assertRaisesRegex(MatrixError, "required external product"):
            validate(m, registry(), root)

    def test_repository_matrix_requires_foliorelay_external_product(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        doc = json.loads((root / ".foundry/product-app-target-matrix.json").read_text(encoding="utf-8"))
        self.assertIn("foliorelay-app", doc["required_external_product_ids"])
        rows = {entry["id"]: entry for entry in doc["entries"]}
        self.assertIn("foliorelay-app", rows)
        self.assertEqual(rows["foliorelay-app"]["classification"], "product")
        self.assertEqual(rows["foliorelay-app"]["source"]["kind"], "external-foundry-product-authority")
        folio_status = rows["foliorelay-app"]["target_status"]
        self.assertEqual(folio_status["26.0.0-BETA.3"]["status"], "PASS")
        self.assertTrue(folio_status["26.0.0-BETA.3"]["evidence"]["f0_f5_complete"])
        self.assertTrue(folio_status["26.0.0-BETA.3"]["evidence"]["oracle_satisfied"])
        self.assertEqual(folio_status["25.10.7"]["status"], "PASS")
        self.assertTrue(folio_status["25.10.7"]["evidence"]["f0_f5_complete"])
        self.assertTrue(folio_status["25.10.7"]["evidence"]["oracle_satisfied"])
        self.assertGreaterEqual(len(folio_status["25.10.7"]["prior_failure_evidence"]), 4)
        self.assertEqual(folio_status["25.04.2.6"]["status"], "PASS")
        self.assertTrue(folio_status["25.04.2.6"]["evidence"]["f0_f5_complete"])
        self.assertTrue(folio_status["25.04.2.6"]["evidence"]["oracle_satisfied"])
        self.assertEqual(folio_status["25.04.1"]["status"], "PASS")
        self.assertTrue(folio_status["25.04.1"]["evidence"]["f0_f5_complete"])
        self.assertTrue(folio_status["25.04.1"]["evidence"]["oracle_satisfied"])

    def test_repository_matrix_garm_beta3_is_full_f0_f5_pass(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        doc = json.loads((root / ".foundry/product-app-target-matrix.json").read_text(encoding="utf-8"))
        rows = {entry["id"]: entry for entry in doc["entries"]}
        garm = rows["garm-controller-app"]["target_status"]
        beta = garm["26.0.0-BETA.3"]
        self.assertEqual(beta["status"], "PASS")
        self.assertEqual(beta["evidence"]["run_id"], 37587664305)
        self.assertEqual(beta["evidence"]["artifact_id"], 11467413455)
        self.assertEqual(beta["evidence"]["classification"], "SUPPORTED")
        self.assertTrue(beta["evidence"]["oracle_satisfied"])
        self.assertTrue(beta["evidence"]["f0_f5_complete"])
        for target in ("25.10.7", "25.04.2.6", "25.04.1"):
            self.assertEqual(garm[target]["status"], "OPEN")
            self.assertIsNone(garm[target]["evidence"])

if __name__ == "__main__":
    unittest.main()
