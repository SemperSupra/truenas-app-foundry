"""Catalog bootstrap rehearsal with EXISTING generic TrueNAS site binder + artifact packager.

The OCI reference points to registry.invalid and is intentionally UNDEPLOYABLE.
This proves deterministic operator handoff semantics only. Product packaging,
native install, live TrueNAS and independent rescue remain open CP3 gates.
"""
from __future__ import annotations

import copy
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(HERE))

import bind_truenas_site as binding
import package_truenas_deployment_artifact as package

FAKE_IMAGE = "registry.invalid/foundry-catalog@sha256:" + "a" * 64

# A minimal eventual image shape, not a working / released image.
BASE = {
    "services": {
        "catalog": {
            "image": FAKE_IMAGE,
            "read_only": True,
            "user": "65532:65532",
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "volumes": [
                {"type": "bind", "source": "/mnt/rdte/catalog/indices",
                 "target": "/data/indexes", "read_only": True},
                {"type": "bind", "source": "/mnt/rdte/catalog/token",
                 "target": "/run/secrets/catalog-read", "read_only": True},
            ],
            "ports": ["127.0.0.1:38081:8081"],
        }
    }
}


def site_spec():
    return {
        "schema": binding.SCHEMA,
        "app_name": "foundry-catalog",
        "expected_base_compose_sha256": package.canonical_sha256(BASE),
        "patches": [
            {"path": "/services/catalog/volumes/0/source",
             "expected": "/mnt/rdte/catalog/indices",
             "value": "/mnt/tank/apps/foundry-catalog/indices"},
            {"path": "/services/catalog/volumes/1/source",
             "expected": "/mnt/rdte/catalog/token",
             "value": "/mnt/tank/apps/foundry-catalog/token"},
        ],
        "host_resources": [
            {"path": "/mnt/tank/apps/foundry-catalog/indices",
             "kind": "directory", "uid": 65532, "gid": 65532,
             "mode": "0700", "ownership": "foundry-owned",
             "retain_on_remove": True},
            {"path": "/mnt/tank/apps/foundry-catalog/token",
             "kind": "file", "uid": 65532, "gid": 65532,
             "mode": "0400", "ownership": "foundry-owned",
             "retain_on_remove": True,
             "content_policy": {"kind": "generated-random-base64", "bytes": 48}},
        ],
    }


class GenericCatalogBootstrapRehearsal(unittest.TestCase):
    def test_bind_then_package_uses_existing_foundry_components(self):
        bound, resources = binding.bind(BASE, site_spec())
        artifact = package.build_artifact("foundry-catalog", bound, {
            "status": "TEST_ONLY_UNDEPLOYABLE",
            "bootstrap_contract": "generic-site-binding-plus-deployment-artifact",
            "base_compose_sha256": "sha256:" + package.canonical_sha256(BASE),
        })
        self.assertEqual(artifact["schema"], "truenas-foundry-deployment-artifact/v1")
        self.assertEqual(artifact["create_payload"]["custom_app"], True)
        self.assertEqual(artifact["create_payload"]["custom_compose_config"], bound)
        self.assertEqual(len(resources), 2)
        self.assertTrue(all(r["retain_on_remove"] for r in resources))
        self.assertTrue(all(volume["read_only"] for volume in
                            bound["services"]["catalog"]["volumes"]))
        self.assertTrue(bound["services"]["catalog"]["read_only"])
        self.assertTrue(bound["services"]["catalog"]["image"].startswith(
            "registry.invalid/"))
        self.assertNotIn("generated-random-base64", str(artifact))
        self.assertNotIn("plaintext", str(artifact).lower())
        self.assertEqual(
            package.canonical_sha256(bound), artifact["compose_sha256"]
        )

    def test_identical_binding_produces_identical_artifact(self):
        spec = site_spec()
        first, _ = binding.bind(BASE, spec)
        second, _ = binding.bind(BASE, spec)
        self.assertEqual(first, second)
        self.assertEqual(package.build_artifact("foundry-catalog", first),
                         package.build_artifact("foundry-catalog", second))

    def test_tampered_source_requires_fresh_binding(self):
        spec = site_spec()
        different = copy.deepcopy(BASE)
        different["services"]["catalog"]["image"] = "registry.invalid/unrelated:latest"
        with self.assertRaises(binding.BindingError):
            binding.bind(different, spec)

    def test_non_mnt_secret_reference_rejected(self):
        spec = site_spec()
        spec["host_resources"][1]["path"] = "/etc/shadow"
        with self.assertRaises(binding.BindingError):
            binding.bind(BASE, spec)

    def test_plaintext_secret_in_resource_policy_rejected(self):
        spec = site_spec()
        spec["host_resources"][1]["content_policy"]["value"] = "plaintext"
        with self.assertRaises(binding.BindingError):
            binding.bind(BASE, spec)

    def test_missing_resource_fails_closed(self):
        spec = site_spec()
        spec["patches"][0]["expected"] = "/mnt/alien/catalog"
        with self.assertRaises(binding.BindingError):
            binding.bind(BASE, spec)

    def test_no_direct_true_nas_or_docker_api_in_rehearsal(self):
        # Existing public binder/packager operate only on in-memory JSON and
        # produce a CREATE payload for a separately authorized executor.
        bound, _ = binding.bind(BASE, site_spec())
        artifact = package.build_artifact("foundry-catalog", bound)
        self.assertEqual(artifact["required_methods"][:2], ["app.query", "app.config"])
        self.assertNotIn("docker", str(artifact["create_payload"]).lower())
        self.assertNotIn("docker.sock", str(artifact["create_payload"]).lower())


if __name__ == "__main__":
    unittest.main()
