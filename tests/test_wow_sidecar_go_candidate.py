from __future__ import annotations

import copy
import importlib.util
import json
import hashlib
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_wow_sidecar_go_candidate.py"
SPEC = importlib.util.spec_from_file_location("validate_wow_sidecar_go_candidate", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PYTHON_CANDIDATE_ROOT = ROOT / "candidates" / "wow-sidecar-app"
GO_CANDIDATE_JSON = ROOT / "candidates" / "wow-sidecar-go-app" / "candidate.json"
GO_APP_DIR = ROOT / "candidates" / "wow-sidecar-go-app" / "ix-dev" / "community" / "wow-sidecar"


class WowSidecarGoCandidateTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads(GO_CANDIDATE_JSON.read_text(encoding="utf-8"))
        self.basic_values = yaml.safe_load((GO_APP_DIR / "templates" / "test_values" / "basic-values.yaml").read_text(encoding="utf-8"))
        self.template_path = GO_APP_DIR / "templates" / "docker-compose.yaml"

    def test_python_era_candidate_remains_byte_untouched(self):
        # Known Python-era evidence files and manifest check
        python_candidate_json = PYTHON_CANDIDATE_ROOT / "candidate.json"
        self.assertTrue(python_candidate_json.exists())

        value = json.loads(python_candidate_json.read_text(encoding="utf-8"))
        self.assertEqual(value["candidate"], "wow-sidecar-truenas-app")
        self.assertEqual(value["truenas_source"]["source_path"], "candidates/wow-sidecar-app/ix-dev/community/wow-sidecar")
        self.assertEqual(value["container"]["registry_reference"], "ghcr.io/sempersupra/wow-sidecar@sha256:6b700ce7ba5ae44116b240ccbb54fb3b60dc952a9b4072ca1314b6f311bc5376")
        self.assertEqual(value["public_render_evidence"]["compose_sha256"], "46ed8d0a3fdd543b5ad359cd73e2b5bf06b69a65ab4f6312fd5c523d2445ab1a")

    def test_go_candidate_validation_passes(self):
        result = MODULE.validate(copy.deepcopy(self.value), root=ROOT)
        self.assertEqual(result["result"], "PASS")
        self.assertFalse(result["seed_helper_required"])
        self.assertEqual(result["runtime_user"], "10001:10001")
        self.assertFalse(result["deployable"])
        self.assertEqual(result["phase"], "exact-image-bound-public-render-pending")

    def test_go_candidate_image_contract_requires_exact_ghcr_digest(self):
        value = copy.deepcopy(self.value)
        value["container"]["registry_reference"] = "ghcr.io/sempersupra/wow-sidecar:latest"
        with self.assertRaisesRegex(MODULE.ValidationError, "exact GHCR digest"):
            MODULE.validate(value, root=ROOT)

    def test_no_seed_helper_or_shell_in_go_runtime(self):
        rendered = MODULE.render_template(self.template_path, self.basic_values)
        services = rendered.get("services", {})
        self.assertIn("wow-sidecar", services)
        self.assertNotIn("wow-sidecar-config-seed", services)
        self.assertEqual(len(services), 1)

    def test_go_candidate_security_contract(self):
        rendered = MODULE.render_template(self.template_path, self.basic_values)
        worker = rendered["services"]["wow-sidecar"]
        self.assertEqual(worker["user"], "10001:10001")
        self.assertTrue(worker["read_only"])
        self.assertIn("ALL", worker["cap_drop"])
        self.assertIn("no-new-privileges=true", worker["security_opt"])

        # Check volume mounts: state is ixVolume, /tmp is tmpfs
        volumes = worker["volumes"]
        state_vol = next(v for v in volumes if v["target"] == "/var/lib/wow-sidecar")
        self.assertEqual(state_vol["storage"]["type"], "ix_volume")

        tmp_vol = next(v for v in volumes if v["target"] == "/tmp")
        self.assertEqual(tmp_vol["storage"]["type"], "tmpfs")
        self.assertEqual(tmp_vol["storage"]["tmpfs_config"]["uid"], 10001)
        self.assertEqual(tmp_vol["storage"]["tmpfs_config"]["gid"], 10001)

    def test_secrets_file_backed_and_isolated_from_env(self):
        rendered = MODULE.render_template(self.template_path, self.basic_values)
        worker = rendered["services"]["wow-sidecar"]
        env = worker["environment"]

        self.assertEqual(env["GITHUB_APP_PRIVATE_KEY_FILE"], "/run/secrets/github-app.pem")
        # Ensure raw key string is not in environment
        for k, v in env.items():
            self.assertNotIn("BEGIN ", v)
            self.assertNotIn("PRIVATE KEY", v)

        # Ensure config secret file is present in configs and rendered configs
        configs = rendered["configs"]
        self.assertIn("wow-github-app-private-key", configs)
        self.assertEqual(configs["wow-github-app-private-key"]["target"], "/run/secrets/github-app.pem")
        self.assertEqual(configs["wow-github-app-private-key"]["mode"], "0400")

    def test_peer_mutation_disabled_by_default(self):
        rendered = MODULE.render_template(self.template_path, self.basic_values)
        worker = rendered["services"]["wow-sidecar"]
        env = worker["environment"]

        self.assertNotIn("WOW_PEER_RENDEZVOUS_ENABLED", env)
        self.assertNotIn("WOW_PEER_CREDENTIALS_FILE", env)
        self.assertNotIn("wow-peer-credentials", rendered["configs"])

    def test_partial_peer_mutation_config_cannot_render_as_enabled(self):
        # Case A: enabled = True, but credentials_json is empty string
        values_a = copy.deepcopy(self.basic_values)
        values_a["peer_rendezvous"]["enabled"] = True
        values_a["peer_rendezvous"]["credentials_json"] = "   "

        rendered_a = MODULE.render_template(self.template_path, values_a)
        env_a = rendered_a["services"]["wow-sidecar"]["environment"]
        self.assertNotIn("WOW_PEER_RENDEZVOUS_ENABLED", env_a)
        self.assertNotIn("WOW_PEER_CREDENTIALS_FILE", env_a)
        self.assertNotIn("wow-peer-credentials", rendered_a["configs"])

        # Case B: enabled = False, but credentials_json is provided
        values_b = copy.deepcopy(self.basic_values)
        values_b["peer_rendezvous"]["enabled"] = False
        values_b["peer_rendezvous"]["credentials_json"] = '{"secret": "pair-key"}'

        rendered_b = MODULE.render_template(self.template_path, values_b)
        env_b = rendered_b["services"]["wow-sidecar"]["environment"]
        self.assertNotIn("WOW_PEER_RENDEZVOUS_ENABLED", env_b)
        self.assertNotIn("WOW_PEER_CREDENTIALS_FILE", env_b)
        self.assertNotIn("wow-peer-credentials", rendered_b["configs"])

    def test_full_peer_mutation_config_renders_correctly(self):
        values = copy.deepcopy(self.basic_values)
        values["peer_rendezvous"]["enabled"] = True
        values["peer_rendezvous"]["credentials_json"] = '{"peer": "key-material"}'
        values["peer_rendezvous"]["max_skew_seconds"] = 15
        values["peer_rendezvous"]["replay_ttl_seconds"] = 45

        rendered = MODULE.render_template(self.template_path, values)
        worker = rendered["services"]["wow-sidecar"]
        env = worker["environment"]

        self.assertEqual(env["WOW_PEER_RENDEZVOUS_ENABLED"], "true")
        self.assertEqual(env["WOW_PEER_CREDENTIALS_FILE"], "/run/secrets/wow-peer-credentials.json")
        self.assertEqual(env["WOW_PEER_MAX_SKEW_SECONDS"], "15")
        self.assertEqual(env["WOW_PEER_REPLAY_TTL_SECONDS"], "45")

        self.assertNotIn("key-material", json.dumps(env))

        configs = rendered["configs"]
        self.assertIn("wow-peer-credentials", configs)
        self.assertEqual(configs["wow-peer-credentials"]["target"], "/run/secrets/wow-peer-credentials.json")
        self.assertEqual(configs["wow-peer-credentials"]["mode"], "0400")

    def test_rendezvous_complete_or_absent(self):
        # Absent case
        rendered_absent = MODULE.render_template(self.template_path, self.basic_values)
        env_absent = rendered_absent["services"]["wow-sidecar"]["environment"]
        self.assertNotIn("WOW_RENDEZVOUS_WORKSET_REF", env_absent)
        self.assertNotIn("WOW_RENDEZVOUS_DELEGATION_ID", env_absent)
        self.assertNotIn("WOW_RENDEZVOUS_LEASE_SECONDS", env_absent)

        # Complete case
        values = copy.deepcopy(self.basic_values)
        values["rendezvous"]["enabled"] = True
        values["rendezvous"]["workset_ref"] = "ws-1"
        values["rendezvous"]["delegation_id"] = "del-1"
        values["rendezvous"]["lease_seconds"] = 600

        rendered_complete = MODULE.render_template(self.template_path, values)
        env_complete = rendered_complete["services"]["wow-sidecar"]["environment"]
        self.assertEqual(env_complete["WOW_RENDEZVOUS_WORKSET_REF"], "ws-1")
        self.assertEqual(env_complete["WOW_RENDEZVOUS_DELEGATION_ID"], "del-1")
        self.assertEqual(env_complete["WOW_RENDEZVOUS_LEASE_SECONDS"], "600")


    def test_network_uses_supported_published_port_contract(self):
        rendered = MODULE.render_template(self.template_path, self.basic_values)
        ports = rendered["services"]["wow-sidecar"]["ports"]
        self.assertEqual(len(ports), 1)
        published = ports[0]["published"]
        self.assertEqual(published["bind_mode"], "published")
        self.assertEqual(published["port_number"], 18080)
        self.assertEqual(published["container_port"], 8080)

    def test_published_candidate_still_not_hil_eligible_before_public_render(self):
        self.assertEqual(self.value["phase"], "exact-image-bound-public-render-pending")
        self.assertFalse(self.value["container"]["synthetic_digest_fixture"])
        self.assertEqual(self.value["container"]["publication_state"], "published-verified")
        self.assertTrue(self.value["gates"]["registry_image_published"])
        self.assertTrue(self.value["gates"]["runtime_independent_accepted"])
        self.assertFalse(self.value["gates"]["public_app_render_qualified"])
        self.assertFalse(self.value["gates"]["hil_eligible"])

    def test_no_public_endpoint_advertised_by_default(self):
        rendered = MODULE.render_template(self.template_path, self.basic_values)
        env = rendered["services"]["wow-sidecar"]["environment"]
        self.assertNotIn("WOW_PUBLIC_ENDPOINT", env)

    def test_deterministic_rendering(self):
        render1 = json.dumps(MODULE.render_template(self.template_path, self.basic_values), sort_keys=True)
        render2 = json.dumps(MODULE.render_template(self.template_path, self.basic_values), sort_keys=True)
        self.assertEqual(render1, render2)


if __name__ == "__main__":
    unittest.main()
