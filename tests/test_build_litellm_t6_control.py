from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "build_litellm_t6_control.py"
SPEC = importlib.util.spec_from_file_location("build_litellm_t6_control", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LiteLlmT6ControlTests(unittest.TestCase):
    def test_builds_exact_secret_safe_control(self):
        candidate = {
            "candidate": "litellm-app",
            "state": "DISPOSABLE_RUNTIME_QUALIFIED",
            "source_materializer": {
                "commit": "4" * 40,
                "lib_version": "2.3.11",
                "lib_hash": "8" * 64,
            },
            "appliance": {
                "reference": "ghcr.io/sempersupra/litellm-appliance@sha256:" + "2" * 64,
                "digest": "sha256:" + "2" * 64,
            },
            "invariants": {
                "minimum_secret_tier": "S1",
                "management_credentials_allowed": False,
                "moving_tags_allowed": False,
            },
        }
        compose = {
            "services": {
                "litellm": {
                    "image": candidate["appliance"]["reference"],
                    "environment": {"SEMPER_SECRET_DIR": "/run/secrets/semper-env"},
                    "ports": [{"target": 4000, "published": "30401", "protocol": "tcp"}],
                    "volumes": [
                        {"type": "bind", "source": MODULE.CONFIG_DIR, "target": "/config", "read_only": True},
                        {"type": "bind", "source": MODULE.SECRET_DIR, "target": "/run/secrets/semper-env", "read_only": True},
                    ],
                }
            }
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c = root / "candidate.json"
            r = root / "compose.json"
            cfg = root / "proxy_server_config.yaml"
            vals = root / "values.yaml"
            out = root / "bundle"
            c.write_text(json.dumps(candidate), encoding="utf-8")
            r.write_text(json.dumps(compose), encoding="utf-8")
            cfg.write_text("model_list: []\n", encoding="utf-8")
            vals.write_text("network: {}\n", encoding="utf-8")
            control = MODULE.build(c, r, cfg, vals, out, "a" * 40)

            self.assertEqual(MODULE.SCHEMA, control["schema"])
            self.assertFalse(control["secrets_captured"])
            self.assertEqual(["TEST_PROVIDER_KEY"], control["runtime"]["fixture_secret_names"])
            self.assertEqual(candidate["appliance"]["reference"], control["candidate"]["appliance_reference"])
            self.assertTrue((out / "compose.json").is_file())
            self.assertTrue((out / "control.json").is_file())

    def test_rejects_management_credential_render(self):
        candidate = {
            "source_materializer": {"commit": "4" * 40},
            "appliance": {
                "reference": "ghcr.io/sempersupra/litellm-appliance@sha256:" + "2" * 64,
                "digest": "sha256:" + "2" * 64,
            },
            "invariants": {
                "minimum_secret_tier": "S1",
                "management_credentials_allowed": False,
                "moving_tags_allowed": False,
            },
        }
        compose = {
            "services": {
                "litellm": {
                    "image": candidate["appliance"]["reference"],
                    "environment": {
                        "SEMPER_SECRET_DIR": "/run/secrets/semper-env",
                        "OPENROUTER_MANAGEMENT_KEY": "forbidden",
                    },
                    "ports": [{"target": 4000, "published": "30401"}],
                    "volumes": [
                        {"source": MODULE.CONFIG_DIR, "target": "/config", "read_only": True},
                        {"source": MODULE.SECRET_DIR, "target": "/run/secrets/semper-env", "read_only": True},
                    ],
                }
            }
        }
        with self.assertRaises(MODULE.ControlError):
            MODULE.validate(candidate, compose)


if __name__ == "__main__":
    unittest.main()
