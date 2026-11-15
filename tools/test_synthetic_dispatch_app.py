#!/usr/bin/env python3
"""Adversarial public-only tests; never loads private artifacts or credentials."""
import copy
import json
from pathlib import Path
import unittest

from tools.validate_synthetic_dispatch_app import FIXTURE, validate


class SyntheticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))

    def assert_denied(self, mutate):
        specimen = copy.deepcopy(self.fixture)
        mutate(specimen)
        self.assertTrue(validate(specimen), "unsafe mutated fixture was admitted")

    def test_baseline_source_contract(self):
        self.assertEqual(validate(self.fixture), [])

    def test_cannot_claim_private_or_deployable_status(self):
        self.assert_denied(lambda x: x.update(classification="private-repo"))
        self.assert_denied(lambda x: x.update(release_or_deployment_authority="apply"))
        self.assert_denied(lambda x: x.update(source_is_private_product=True))
        self.assert_denied(lambda x: x.update(image="ghcr.io/private/svc@sha256:" + "a" * 64))

    def test_nonroot_immutable_capabilities(self):
        for role in ("control", "worker"):
            for field, bad in (("user", "0:0"), ("read_only", False), ("privileged", True),
                               ("host_network", True), ("cap_drop", []), ("security_opt", [])):
                with self.subTest(role=role, field=field):
                    self.assert_denied(lambda x, r=role, k=field, v=bad: x["services"][r].update({k: v}))

    def test_network_exposure_is_loopback_control_only(self):
        self.assert_denied(lambda x: x["services"]["control"].update(ports=["0.0.0.0:18081:8080"]))
        self.assert_denied(lambda x: x["services"]["worker"].update(ports=["18081:8080"]))
        self.assert_denied(lambda x: x["services"]["control"].update(health_path="/debug"))

    def test_custody_read_only_ledger_rw_and_retained(self):
        self.assert_denied(lambda x: x["services"]["control"].update(mounts=[
            "/synthetic/custody:/custody:rw", "/synthetic/ledger:/ledger:rw"]))
        self.assert_denied(lambda x: x["services"]["worker"].update(mounts=[
            "/synthetic/custody:/custody:ro", "/synthetic/ledger:/ledger:ro"]))
        self.assert_denied(lambda x: x["storage"].update(retain_on_app_delete=False))
        self.assert_denied(lambda x: x["storage"].update(custody="/mnt/realhost/custody"))

    def test_no_extra_services_or_unreviewed_fields(self):
        self.assert_denied(lambda x: x["services"].update(proxy={}))
        self.assert_denied(lambda x: x["services"]["control"].update(network_mode="host"))
        self.assert_denied(lambda x: x.update(secrets={"token": "literal"}))


if __name__ == "__main__":
    unittest.main()
