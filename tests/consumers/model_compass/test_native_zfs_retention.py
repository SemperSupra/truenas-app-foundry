"""Adversarial source-only ZFS data/secret retention planner tests."""
import copy
import unittest

from native_zfs_retention import (
    APP_NAME, DATASET, MOUNT, OWNERSHIP, SCHEMA, SOURCE_SHA, TARGET_VERSION,
    UID, evaluate, template,
)

DIGEST = "sha256:" + "c" * 64


def observation():
    return {
        "scope": "public_disposable_kvm_only",
        "target_version": TARGET_VERSION,
        "native_image_transport": "SUPPORTED",
        "image_digest": DIGEST,
        "dataset": {
            "id": DATASET, "mountpoint": MOUNT,
            "owner_receipt": OWNERSHIP,
            "ownership": "experiment_owned",
            "mount_read_only_to_product": True,
        },
        "secret": {"uid": UID, "mode": "0400", "bytes": 64},
        "snapshot": {"external_source": True, "valid_json": True},
        "app": {
            "name": APP_NAME, "image_digest": DIGEST,
            "owner_receipt": OWNERSHIP, "state": "RUNNING",
        },
    }


class NativeStatePlanTests(unittest.TestCase):
    def test_immutable_source_and_durable_external_state_contract(self):
        p = template()
        assert p["source_sha"] == SOURCE_SHA
        assert p["app_mounts"]["/state"] == {"source": MOUNT, "read_only": True}
        assert p["app_mounts"]["/run/secrets/compass_token"]["read_only"] is True
        assert p["expected_secret"]["mode"] == "0400"
        assert p["dataset_delete_policy"] == "never_by_app_lifecycle"
        assert p["native_F2_F6"] == "NOT_RUN"
        assert p["filesystem_file_receive_public_api"] is False
        assert p["app_lifecycle_executor"] == "EXISTING_FOUNDRY_GENERIC_ONLY"

    def test_owned_normal_routing_remains_plan_only(self):
        scenarios = [
            ("ENSURE_RUNNING", observation(), "NOOP"),
            ("ENSURE_ABSENT", observation(), "DELETE_APP_RETAIN_DATA_VIA_FOUNDRY"),
            ("REDEPLOY", observation(), "REDEPLOY_VIA_EXISTING_FOUNDRY"),
        ]
        absent = observation()
        absent["app"] = None
        scenarios += [
            ("ENSURE_RUNNING", absent, "CREATE_VIA_EXISTING_FOUNDRY"),
            ("ENSURE_ABSENT", absent, "NOOP_DATA_RETAINED"),
        ]
        stopped = observation()
        stopped["app"]["state"] = "STOPPED"
        scenarios.append(("ENSURE_RUNNING", stopped, "START_VIA_EXISTING_FOUNDRY"))
        for operation, obs, action in scenarios:
            with self.subTest(operation=operation, action=action):
                result = evaluate(template(), obs, operation)
                self.assertEqual(result["status"], "PLAN_ONLY")
                self.assertEqual(result["operation"], action)
                self.assertEqual(result["native_F2_F6"], "NOT_RUN")
                self.assertFalse(result["side_effects"])

    def test_external_dataset_create_is_separate_owner_gate(self):
        o = observation()
        o["dataset"] = None
        r = evaluate(template(), o)
        self.assertEqual(r["operation"], "CREATE_OWNED_DATASET")
        self.assertEqual(r["dataset_api"], "pool.dataset.create")
        self.assertEqual(r["next_gate"], "independent_owner_provenance_and_secret_seed")
        self.assertEqual(evaluate(template(), o, "ENSURE_ABSENT")["status"], "BLOCKED")

    def test_owned_dataset_cleanup_separate_from_app_uninstall(self):
        o = observation()
        r = evaluate(template(), o, "CLEANUP_OWNED_DATASET", explicit_dataset_cleanup=True)
        self.assertEqual(r["status"], "BLOCKED")
        o["app"] = None
        self.assertEqual(evaluate(template(), o, "CLEANUP_OWNED_DATASET")["status"], "BLOCKED")
        r = evaluate(template(), o, "CLEANUP_OWNED_DATASET", explicit_dataset_cleanup=True)
        self.assertEqual(r["operation"], "EXPLICIT_OWNED_DATASET_DELETE_SEPARATE_FROM_APP")

    def test_no_implicit_missing_ownership_or_auth(self):
        for name, poison in [
            ("wrong version", lambda o: o.update(target_version="TrueNAS-25.10.7")),
            ("physical site", lambda o: o.update(scope="physical-nas")),
            ("unqualified image transport", lambda o: o.update(native_image_transport="UNKNOWN")),
            ("mutable image tag", lambda o: o.update(image_digest="latest")),
            ("foreign dataset", lambda o: o["dataset"].update(id="prod/my-data")),
            ("foreign mounted source", lambda o: o["dataset"].update(mountpoint="/mnt/other")),
            ("foreign owner receipt", lambda o: o["dataset"].update(owner_receipt="untrusted")),
            ("dataset owner unknown", lambda o: o["dataset"].update(ownership="UNKNOWN")),
            ("writable state", lambda o: o["dataset"].update(mount_read_only_to_product=False)),
            ("no token", lambda o: o.pop("secret")),
            ("token wrong user", lambda o: o["secret"].update(uid=0)),
            ("token readable by all", lambda o: o["secret"].update(mode="0644")),
            ("short token", lambda o: o["secret"].update(bytes=12)),
            ("nonexternal snapshot", lambda o: o["snapshot"].update(external_source=False)),
            ("malformed snapshot", lambda o: o["snapshot"].update(valid_json=False)),
            ("foreign app", lambda o: o["app"].update(name="unowned-app")),
            ("untrusted app owner", lambda o: o["app"].update(owner_receipt="wrong")),
            ("installed image digest drift", lambda o: o["app"].update(image_digest="sha256:"+"d"*64)),
            ("app unknown", lambda o: o["app"].update(state="UNKNOWN")),
        ]:
            with self.subTest(name=name):
                o = observation()
                poison(o)
                result = evaluate(template(), o)
                self.assertEqual(result["status"], "BLOCKED", result)
                self.assertEqual(result["native_F2_F6"], "NOT_RUN")

    def test_request_mismatch_and_unexpected_commands_refused(self):
        o=observation()
        for change in [
            {"source_sha": "f" * 40},
            {"dataset": {"id": "prod/zfs", "mountpoint": "/mnt/prod/zfs"}},
            {"app_lifecycle_executor": "new-product-specific-installer"},
            {"native_F2_F6": "PASS"},
        ]:
            with self.subTest(change=change):
                p=copy.deepcopy(template())
                p.update(change)
                self.assertEqual(evaluate(p,o)["status"],"BLOCKED")
        for command in ["DELETE_ZFS", "AUTO_ADOPT", "REPLACE_PRODUCTION_APP", "SKIP_HIL"]:
            self.assertEqual(evaluate(template(),o,command)["status"],"BLOCKED")
        self.assertEqual(evaluate(template(),None)["status"],"BLOCKED")


if __name__ == "__main__":
    unittest.main()
