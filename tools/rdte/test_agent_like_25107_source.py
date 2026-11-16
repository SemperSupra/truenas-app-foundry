"""Public synthetic (NOT Agent Dispatch) 25.10.7 F0 preflight source oracle.

The fixture is disposable source data only; it cannot qualify native F0/F1,
effects, user custody, remote admission or any physical TrueNAS deployment.
"""
from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import tempfile
import unittest

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "agent_like_25107.compose.json"
PUBLIC_IMAGE = (
    "nginx@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10"
)
ROLES = ("control", "worker")
VOLUMES = {"rdte_agentlike_custody", "rdte_agentlike_ledger"}
ALLOWED_SERVICE_FIELDS = {
    "image", "user", "read_only", "cap_drop", "security_opt",
    "entrypoint", "command", "tmpfs", "volumes", "healthcheck", "restart",
}


def validate(compose: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(compose, dict):
        return ["compose-object-required"]
    if set(compose) != {"name", "services", "volumes"}:
        errors.append("unexpected-top-level")
    if compose.get("name") != "foundry-agentlike-public-25107":
        errors.append("unexpected-project-name")
    volumes = compose.get("volumes")
    if not isinstance(volumes, dict) or set(volumes) != VOLUMES:
        errors.append("external-named-volumes-required")
    elif any(value != {"external": True} for value in volumes.values()):
        errors.append("persistent-external-volume-required")
    services = compose.get("services")
    if not isinstance(services, dict) or set(services) != set(ROLES):
        return errors + ["exactly-two-named-services-required"]
    for role in ROLES:
        service = services[role]
        label = role + ":"
        if not isinstance(service, dict):
            errors.append(label + "invalid-service")
            continue
        if set(service) != ALLOWED_SERVICE_FIELDS:
            errors.append(label + "unexpected-service-fields")
        if service.get("image") != PUBLIC_IMAGE:
            errors.append(label + "unapproved-or-mutable-image")
        if service.get("user") != "65532:65532":
            errors.append(label + "nonroot-identity")
        if service.get("read_only") is not True:
            errors.append(label + "read-only-root-required")
        if service.get("cap_drop") != ["ALL"]:
            errors.append(label + "capability-dropping-required")
        if service.get("security_opt") != ["no-new-privileges:true"]:
            errors.append(label + "no-new-privileges-required")
        if service.get("entrypoint") != ["/bin/sh", "-c"] or service.get("command") != ["sleep 3600"]:
            errors.append(label + "fixed-inert-entrypoint-required")
        if service.get("restart") != "unless-stopped":
            errors.append(label + "bounded-restart-required")
        if service.get("tmpfs") != ["/tmp:rw,nosuid,nodev,noexec,size=16m"]:
            errors.append(label + "bounded-ephemeral-tmp-required")
        if service.get("healthcheck") != {
            "test": ["CMD", "/bin/sh", "-c", "test -d /custody && test -d /ledger"],
            "interval": "20s", "timeout": "5s", "retries": 3,
        }:
            errors.append(label + "inert-readiness-oracle-required")
        mounts = service.get("volumes")
        expected_mounts = [
            {"type": "volume", "source": "rdte_agentlike_custody",
             "target": "/custody", "read_only": True},
            {"type": "volume", "source": "rdte_agentlike_ledger",
             "target": "/ledger", "read_only": role != "control"},
        ]
        if mounts != expected_mounts:
            errors.append(label + "custody-ledger-rights-required")
    return errors


class PublicSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obj = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_good(self):
        self.assertEqual(validate(self.obj), [])

    def test_forbidden_extra_service(self):
        obj = copy.deepcopy(self.obj)
        obj["services"]["shadow"] = obj["services"]["worker"]
        self.assertIn("exactly-two-named-services-required", validate(obj))

    def test_forbidden_ambient_authority(self):
        for field, value in (
            ("privileged", True),
            ("network_mode", "host"),
            ("pid", "host"),
            ("ports", ["0.0.0.0:4444:4444"]),
            ("environment", {"PRIVATE_TOKEN": "synthetic"}),
            ("devices", ["/dev/kvm"]),
            ("volumes_from", ["other"]),
        ):
            obj = copy.deepcopy(self.obj)
            obj["services"]["control"][field] = value
            with self.subTest(field=field):
                self.assertIn("control:unexpected-service-fields", validate(obj))

    def test_forbidden_image_and_user_changes(self):
        for field, value, code in (
            ("image", "nginx:latest", "unapproved-or-mutable-image"),
            ("image", "ghcr.io/private/agent-dispatch:latest", "unapproved-or-mutable-image"),
            ("user", "0:0", "nonroot-identity"),
            ("read_only", False, "read-only-root-required"),
            ("cap_drop", [], "capability-dropping-required"),
            ("security_opt", [], "no-new-privileges-required"),
        ):
            obj = copy.deepcopy(self.obj)
            obj["services"]["worker"][field] = value
            with self.subTest(field=field, value=value):
                self.assertIn("worker:" + code, validate(obj))

    def test_forbidden_storage_escalation_and_persistence_loss(self):
        for role in ROLES:
            obj = copy.deepcopy(self.obj)
            obj["services"][role]["volumes"][0]["read_only"] = False
            with self.subTest(role=role):
                self.assertIn(role + ":custody-ledger-rights-required", validate(obj))
        obj = copy.deepcopy(self.obj)
        obj["services"]["worker"]["volumes"][1]["read_only"] = False
        self.assertIn("worker:custody-ledger-rights-required", validate(obj))
        obj = copy.deepcopy(self.obj)
        obj["volumes"]["rdte_agentlike_ledger"] = {}
        self.assertIn("persistent-external-volume-required", validate(obj))

    def test_inert_only_no_hidden_synthetic_exec(self):
        obj = copy.deepcopy(self.obj)
        obj["services"]["control"]["command"] = ["sh -c 'curl example.com'"]
        self.assertIn("control:fixed-inert-entrypoint-required", validate(obj))
        obj = copy.deepcopy(self.obj)
        obj["services"]["control"]["healthcheck"]["test"] = ["CMD", "echo", "ready"]
        self.assertIn("control:inert-readiness-oracle-required", validate(obj))


class NativeT6AdmissionGuard(unittest.TestCase):
    """Missing native GARM F0-F5 probe must not consume a QEMU slot.

    Copy the existing entrypoint into an isolated directory with *no* probe
    or registry: a safe regression against accidentally starting expensive
    native qualification. A present future probe is never executed.
    """

    def test_missing_native_probe_fails_before_state_allocation(self):
        source = (
            pathlib.Path(__file__).parent
            / "vendor" / "truenas-kvm" / "scripts" / "gha_kvm_truenas_rdte.sh"
        )
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            entrypoint = root / "gha_kvm_truenas_rdte.sh"
            entrypoint.write_bytes(source.read_bytes())
            state, receipt = root / "vm-state", root / "receipt.json"
            cmd = [
                "bash", str(entrypoint),
                "--out", str(receipt),
                "--state-dir", str(state),
                "--target-version", "25.10.7",
                "--rung", "t6",
                "--t6-product", "garm-controller-f0f5",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("HOLD_NATIVE_GARM_F0F5_ORACLE_MISSING", proc.stderr)
            self.assertFalse(state.exists(), "preflight must not allocate VM state")
            self.assertFalse(receipt.exists(), "missing oracle must not fabricate success receipt")

            # The guard is scoped to this product, not to all T6 selectors.
            alternate = cmd[:-1] + ["garm"]
            other = subprocess.run(
                alternate, capture_output=True, text=True, timeout=10, check=False
            )
            self.assertEqual(other.returncode, 2, other.stderr)
            self.assertNotIn("HOLD_NATIVE_GARM_F0F5_ORACLE_MISSING", other.stderr)
            self.assertIn("missing exact TrueNAS target registry", other.stderr)


if __name__ == "__main__":
    unittest.main()
