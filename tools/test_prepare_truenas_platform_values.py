#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("prepare_truenas_platform_values.py")
SPEC = importlib.util.spec_from_file_location("prepare_truenas_platform_values", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


QUESTIONS = {
    "questions": [
        {
            "variable": "network",
            "schema": {
                "type": "dict",
                "attrs": [
                    {
                        "variable": "certificate_id",
                        "schema": {"type": "int", "$ref": ["definitions/certificate"]},
                    },
                    {
                        "variable": "host_ips",
                        "schema": {
                            "type": "list",
                            "items": [
                                {
                                    "variable": "host_ip",
                                    "schema": {
                                        "type": "string",
                                        "$ref": ["definitions/node_bind_ip"],
                                    },
                                }
                            ],
                        },
                    },
                ],
            },
        },
        {
            "variable": "storage",
            "schema": {
                "type": "dict",
                "attrs": [
                    {
                        "variable": "config",
                        "schema": {
                            "type": "dict",
                            "attrs": [
                                {
                                    "variable": "ix_volume_config",
                                    "schema": {
                                        "type": "dict",
                                        "$ref": ["normalize/ix_volume"],
                                        "attrs": [
                                            {"variable": "dataset_name", "schema": {"type": "string"}}
                                        ],
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        },
    ]
}


class PlatformValuesTests(unittest.TestCase):
    def base_values(self):
        return {
            "network": {"certificate_id": 7, "host_ips": []},
            "storage": {
                "config": {
                    "type": "ix_volume",
                    "ix_volume_config": {"dataset_name": "state"},
                }
            },
            "ix_certificates": {999: {"certificate": "SPOOF", "privatekey": "SPOOF"}},
            "ix_volumes": {"spoof": "/tmp/spoof"},
        }

    def resolved(self, certificate="CERTIFICATE-A"):
        return {
            "certificates": {
                "7": {
                    "id": 7,
                    "name": "service-cert",
                    "certificate": certificate,
                    "privatekey": "SECRET-PRIVATE-KEY",
                }
            },
            "ix_volumes": {
                "state": {
                    "host_path": "/mnt/.ix-apps/app_mounts/example/state",
                    "properties": {"acltype": "posix"},
                }
            },
        }

    def test_certificate_and_volume_are_injected(self):
        normalized, plan = MOD.prepare_values(QUESTIONS, self.base_values(), self.resolved())
        self.assertEqual(normalized["ix_certificates"][7]["certificate"], "CERTIFICATE-A")
        self.assertEqual(normalized["ix_certificates"][7]["privatekey"], "SECRET-PRIVATE-KEY")
        self.assertNotIn(999, normalized["ix_certificates"])
        self.assertEqual(
            normalized["ix_volumes"]["state"],
            "/mnt/.ix-apps/app_mounts/example/state",
        )
        self.assertNotIn("spoof", normalized["ix_volumes"])
        self.assertEqual(plan["dependencies"][0]["id"], "7")
        self.assertEqual(plan["actions"][0]["dataset_name"], "state")

    def test_sanitized_plan_contains_no_private_material_or_host_path(self):
        _normalized, plan = MOD.prepare_values(QUESTIONS, self.base_values(), self.resolved())
        text = json.dumps(plan, sort_keys=True)
        self.assertNotIn("SECRET-PRIVATE-KEY", text)
        self.assertNotIn("CERTIFICATE-A", text)
        self.assertNotIn("/mnt/.ix-apps", text)
        self.assertIn("public_certificate_sha256", text)
        self.assertIn("host_path_sha256", text)

    def test_certificate_renewal_changes_dependency_identity(self):
        _a_values, a = MOD.prepare_values(QUESTIONS, self.base_values(), self.resolved("CERTIFICATE-A"))
        _b_values, b = MOD.prepare_values(QUESTIONS, self.base_values(), self.resolved("CERTIFICATE-B"))
        self.assertNotEqual(a["dependency_identity_sha256"], b["dependency_identity_sha256"])
        self.assertNotEqual(
            a["dependencies"][0]["public_certificate_sha256"],
            b["dependencies"][0]["public_certificate_sha256"],
        )

    def test_missing_resolution_fails_closed(self):
        resolved = self.resolved()
        del resolved["certificates"]["7"]
        with self.assertRaises(MOD.MaterializationError):
            MOD.prepare_values(QUESTIONS, self.base_values(), resolved)

    def test_active_node_bind_ip_fails_closed(self):
        values = self.base_values()
        values["network"]["host_ips"] = ["192.0.2.10"]
        with self.assertRaises(MOD.MaterializationError):
            MOD.prepare_values(QUESTIONS, values, self.resolved())

    def test_unknown_active_ref_fails_closed(self):
        questions = copy.deepcopy(QUESTIONS)
        questions["questions"].append(
            {
                "variable": "future",
                "schema": {"type": "string", "$ref": ["definitions/future_platform_thing"]},
            }
        )
        values = self.base_values() | {"future": "enabled"}
        with self.assertRaises(MOD.MaterializationError):
            MOD.prepare_values(questions, values, self.resolved())

    def test_private_output_mode_is_0600(self):
        normalized, _plan = MOD.prepare_values(QUESTIONS, self.base_values(), self.resolved())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "normalized.yaml"
            MOD.write_private_yaml(path, normalized)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
