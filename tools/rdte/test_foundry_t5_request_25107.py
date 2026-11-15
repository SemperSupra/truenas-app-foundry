"""Version-scoped one-use 25.10.7 native T5 source/admission and T3 receipt oracle."""
import copy
import unittest

from tools.rdte.foundry_t5_request import validate, SCHEMA
from tools.rdte.github_t3_evidence import require, EvidenceError, REPO


def request():
    return {
        "schema": SCHEMA,
        "request_id": "fndry-t5-25-10-7-20261115-qual01",
        "version": "25.10.7",
        "rung": "t5",
        "t3_run_id": 43747010576,
        "t3_head_sha": "2b9826f7e2b23fa0c44cf1451b1e5ab4a269a852",
        "t3_artifact_id": 14174951708,
        "scope": "public-disposable-platform-nginx-only",
    }


def run():
    r = request()
    return {
        "id": r["t3_run_id"], "head_sha": r["t3_head_sha"],
        "status": "completed", "conclusion": "success",
        "name": "Foundry exact TrueNAS 25.10.7 native T3 ZFS (no AD)",
        "repository": {"full_name": REPO},
    }


def artifact():
    r = request()
    return {"artifacts": [{
        "id": r["t3_artifact_id"],
        "name": "foundry-native-25-10-7-t3-zfs",
        "expired": False,
        "size_in_bytes": 8025,
        "workflow_run": {"id": r["t3_run_id"]},
    }]}


class Exact25107T5(unittest.TestCase):
    def test_request_admission(self):
        self.assertEqual(validate(request()), [])

    def test_other_version_or_scope_denied(self):
        for key, value in (
            ("version", "latest"), ("scope", "private-live"),
            ("t3_artifact_id", 0), ("t3_head_sha", "unknown"),
            ("request_id", "fndry-t5-25-04-2-6-fake-20261115"),
        ):
            data = request()
            data[key] = value
            with self.subTest(key=key):
                self.assertTrue(validate(data))

    def test_positive_exact_t3_identity(self):
        self.assertTrue(require(request(), run(), artifact()))

    def test_foreign_t3_source_and_artifact_denied(self):
        for key, changed in (
            ("name", "Foundry direct native TrueNAS T3 ZFS (no AD)"),
            ("head_sha", "a" * 40),
            ("conclusion", "failure"),
        ):
            bad = run()
            bad[key] = changed
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                require(request(), bad, artifact())
        for key, changed in (("name", "foundry-native-25-04-2-6-t3-zfs"), ("expired", True), ("id", 123)):
            bad = copy.deepcopy(artifact())
            bad["artifacts"][0][key] = changed
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                require(request(), run(), bad)

    def test_version_swaps_are_not_interchangeable(self):
        old = request()
        old["version"] = "25.04.2.6"
        with self.assertRaises(EvidenceError):
            require(old, run(), artifact())


if __name__ == "__main__":
    unittest.main()
