from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "build_wow_sidecar_t6_control.py"
SPEC = importlib.util.spec_from_file_location("build_wow_sidecar_t6_control", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def candidate():
    return {
        "candidate": "wow-sidecar-truenas-app",
        "phase": "render-qualified-private-hil-pending",
        "container": {"registry_reference": MODULE.EXPECTED_IMAGE, "runtime_user": "10001:10001"},
        "permissions_helper": {"reference": MODULE.EXPECTED_HELPER},
        "truenas_source": {"commit": "a"*40, "lib_version": "2.3.4", "lib_hash": "b"*64},
        "gates": {"public_app_render_qualified": True, "hil_eligible": True},
    }


def compose():
    common = {"user":"10001:10001","privileged":False,"read_only":True,"cap_drop":["ALL"]}
    return {
        "services": {
            "wow-sidecar": {
                **common,
                "image": MODULE.EXPECTED_IMAGE,
                "environment": {"GITHUB_APP_ID":"12345"},
                "configs": [],
                "volumes": [
                    {"source": MODULE.CONFIG_DIR, "target": "/etc/wow-sidecar", "read_only": True},
                    {"source": MODULE.STATE_DIR, "target": "/var/lib/wow-sidecar", "read_only": False},
                ],
                "command": ["--control-repository","ExampleOrg/control"],
                "labels": {"fixture":"ExampleOrg/operator"},
            },
            "wow-sidecar-config-seed": {
                **common,
                "image": MODULE.EXPECTED_IMAGE,
                "network_mode":"none",
                "volumes": [
                    {"source": MODULE.CONFIG_DIR, "target": "/etc/wow-sidecar", "read_only": False},
                ],
                "environment": {"FIXTURE": MODULE.FIXTURE_MARKER},
            },
            "permissions": {
                "image": MODULE.EXPECTED_HELPER,
                "network_mode":"none",
                "privileged":False,
            },
        },
        "configs": {
            "wow-github-app-private-key": {"content": "-----BEGIN PRIVATE KEY-----\n"+MODULE.FIXTURE_MARKER+"\n-----END PRIVATE KEY-----"},
            "wow-operator-profile": {"content": '{"repository":"ExampleOrg/operator"}'},
        },
    }


class WowSidecarT6ControlTests(unittest.TestCase):
    def test_builds_public_safe_exact_control(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            c=root/"candidate.json"; r=root/"compose.json"; out=root/"bundle"
            c.write_text(json.dumps(candidate()),encoding="utf-8")
            r.write_text(json.dumps(compose()),encoding="utf-8")
            result=MODULE.build(c,r,out,"c"*40)
            self.assertEqual(MODULE.SCHEMA,result["schema"])
            self.assertFalse(result["secrets_captured"])
            self.assertFalse(result["runtime"]["production_credentials_present"])
            self.assertEqual(MODULE.EXPECTED_IMAGE,result["candidate"]["wow_image"])
            self.assertTrue((out/"compose.json").is_file())

    def test_rejects_private_identity(self):
        value=compose()
        value["services"]["wow-sidecar"]["labels"]["leak"]="SemperSupra/example-private"
        with self.assertRaisesRegex(MODULE.ControlError,"private repository"):
            MODULE.validate(candidate(),value)

    def test_rejects_image_drift(self):
        value=compose()
        value["services"]["wow-sidecar"]["image"]="ghcr.io/sempersupra/wow-sidecar:latest"
        with self.assertRaisesRegex(MODULE.ControlError,"image drifted"):
            MODULE.validate(candidate(),value)


if __name__ == "__main__":
    unittest.main()
