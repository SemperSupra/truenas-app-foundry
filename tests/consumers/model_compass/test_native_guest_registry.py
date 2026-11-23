"""Negative policy oracles for possible disposable native TrueNAS image transport.

Tests are pure Python; no Docker registry, QEMU, TrueNAS, or network calls.
"""
import copy
import unittest

from native_guest_registry import (
    DIGEST,
    GUEST_PORT,
    HOST_PORT,
    REGISTRY_APP_NAME,
    REGISTRY_REF,
    TARGET,
    PlanError,
    bind_guest_pull_digest,
    plan,
    verify_plan_contract,
)

PRODUCT = "6e88ccbe09f7f0989a8db4e75967654d409f8f64"
CONTENT_DIGEST = "sha256:" + "a" * 64


def good():
    return plan(
        product_commit=PRODUCT,
        target_version=TARGET,
        isolated_kvm=True,
        public_source_only=True,
    )


class GuestRegistryPlanTests(unittest.TestCase):
    def test_hypothesis_bounded_to_public_disposable_guest(self):
        p = good()
        self.assertEqual(p["classification"], "CANDIDATE_NOT_HIL")
        self.assertEqual(p["native_F2_F6"], "NOT_RUN")
        self.assertFalse(p["image_published_external"])
        self.assertTrue(p["never_edit_docker_daemon"])
        self.assertTrue(p["requires_zero_qemu_residue"])
        self.assertEqual(p["guest_registry_native_app"], REGISTRY_APP_NAME)
        self.assertEqual(p["qemu_hostfwd"], f"hostfwd=tcp:127.0.0.1:{HOST_PORT}-:{GUEST_PORT}")
        self.assertIn("sha256:", REGISTRY_REF)
        self.assertTrue(DIGEST.fullmatch(p["registry_source_digest"]))
        self.assertEqual(p["guest_registry_compose"]["services"]["registry"]["ports"], [f"0.0.0.0:{GUEST_PORT}:5000"])
        self.assertNotIn("/var/run/docker.sock", str(p))
        verify_plan_contract(p)

    def test_identity_and_canonicalization(self):
        a = good()
        b = good()
        self.assertEqual(a, b)
        c = plan(product_commit="b" * 40, target_version=TARGET, isolated_kvm=True, public_source_only=True)
        self.assertNotEqual(a["plan_sha256"], c["plan_sha256"])
        self.assertEqual(
            bind_guest_pull_digest(a, CONTENT_DIGEST),
            f"127.0.0.1:{GUEST_PORT}/compass-guest-fixture@{CONTENT_DIGEST}",
        )

    def test_reject_non_exact_source_and_environment(self):
        cases = [
            {"product_commit": "main"},
            {"product_commit": "A" * 40},
            {"product_commit": "a" * 39},
            {"target_version": "25.10.7"},
            {"isolated_kvm": False},
            {"public_source_only": False},
            {"host_bind": "0.0.0.0"},
            {"host_bind": "10.0.2.2"},
            {"host_port": 15432},
            {"guest_port": 15432},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(PlanError):
                arguments = dict(
                    product_commit=PRODUCT,
                    target_version=TARGET,
                    isolated_kvm=True,
                    public_source_only=True,
                )
                arguments.update(changes)
                plan(**arguments)

    def test_tampering_requires_replan(self):
        for name, patch in [
            ("unauthorized guest port", lambda p: p.update(qemu_hostfwd="hostfwd=tcp:0.0.0.0:15431-:15431")),
            ("hidden external registry", lambda p: p.update(image_published_external=True)),
            ("app name changed", lambda p: p.update(guest_registry_native_app="model-compass")),
            ("unrestricted docker", lambda p: p.update(never_edit_docker_daemon=False)),
            ("changed image source", lambda p: p["guest_registry_compose"]["services"]["registry"].update(image="registry:latest")),
            ("wrong state label", lambda p: p.update(native_F2_F6="PASS")),
        ]:
            with self.subTest(name=name), self.assertRaises(PlanError):
                p = copy.deepcopy(good())
                patch(p)
                verify_plan_contract(p)

    def test_untrusted_digest_and_guest_ref(self):
        for candidate in ["sha256:abc", "SHA256:" + "a" * 64, "latest", "sha256:" + "A" * 64]:
            with self.subTest(candidate=candidate), self.assertRaises(PlanError):
                bind_guest_pull_digest(good(), candidate)
        p = good()
        p["guest_pull_tag"] = "evil.example/model:main"
        with self.assertRaises(PlanError):
            bind_guest_pull_digest(p, CONTENT_DIGEST)

if __name__ == "__main__":
    unittest.main()
