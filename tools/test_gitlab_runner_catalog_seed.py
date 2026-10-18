#!/usr/bin/env python3
"""Negative mutation tests for SOURCE-SHAPE gate. Does not require Docker or TrueNAS."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from validate_gitlab_runner_catalog_seed import ROOT, SourceContractError, check

class GitLabRunnerSeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "candidates/gitlab-runner-app",
                        self.root / "candidates/gitlab-runner-app")
    def tearDown(self):
        self.tmp.cleanup()
    def test_source_shape_only(self):
        receipt = check(self.root)
        self.assertEqual(receipt["result"], "PASS_SOURCE_SHAPE_ONLY")
        self.assertFalse(receipt["runtime_qualified"])
    def test_reject_unpinned_image(self):
        path = self.root / "candidates/gitlab-runner-app/candidate.json"
        m = json.loads(path.read_text())
        m["manager_image"]["reference"] = "gitlab/gitlab-runner:latest"
        path.write_text(json.dumps(m))
        with self.assertRaises(SourceContractError):
            check(self.root)
    def test_reject_spurious_qualification(self):
        path = self.root / "candidates/gitlab-runner-app/candidate.json"
        m = json.loads(path.read_text())
        m["gates"]["official_catalog"] = "PASS"
        path.write_text(json.dumps(m))
        with self.assertRaises(SourceContractError):
            check(self.root)
    def test_reject_unqualified_capacity(self):
        path = self.root / "candidates/gitlab-runner-app/ix-dev/community/gitlab-runner/questions.yaml"
        data = path.read_text().replace("max: 1", "max: 10")
        path.write_text(data)
        with self.assertRaises(SourceContractError):
            check(self.root)
    def test_reject_host_docker_socket(self):
        path = self.root / "candidates/gitlab-runner-app/ix-dev/community/gitlab-runner/templates/docker-compose.yaml"
        path.write_text(path.read_text() + "\n# /var/run/docker.sock\n")
        with self.assertRaises(SourceContractError):
            check(self.root)
    def test_reject_missing_seed_guard(self):
        path = self.root / "candidates/gitlab-runner-app/ix-dev/community/gitlab-runner/templates/docker-compose.yaml"
        path.write_text(path.read_text().replace("exit 42", "exit 0"))
        with self.assertRaises(SourceContractError):
            check(self.root)

if __name__ == "__main__":
    unittest.main()
