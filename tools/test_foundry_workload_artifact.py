import copy
import json
import unittest

from tools.foundry_workload_artifact import (
    ADAPTERS, WorkloadContractError, inspect_artifact, load_artifact,
)


def fixture(kind="vm", adapter="truenas-native-vm", platform="truenas", fmt="raw"):
    return {
        "schema": "foundry-workload-artifact/v1",
        "product_id": "fictional-workload",
        "kind": kind,
        "build_sha256": "sha256:" + "1" * 64,
        "target": {"adapter": adapter, "platform": platform,
                   "version": "1.2.3", "profile_sha256": "sha256:" + "2" * 64},
        "artifact": {"format": fmt, "sha256": "sha256:" + "3" * 64},
        "data": {"policy": "retain-data", "contract_sha256": "sha256:" + "4" * 64},
    }


class WorkloadArtifactTests(unittest.TestCase):
    def test_every_declared_family_is_identity_only(self):
        for adapter, (kind, platform, formats) in ADAPTERS.items():
            for fmt in formats:
                with self.subTest(adapter=adapter, fmt=fmt):
                    r = inspect_artifact(fixture(kind, adapter, platform, fmt))
                    self.assertEqual(r["status"], "IDENTITY_ONLY")
                    for field in ("apply_authorized", "runtime_qualified",
                                  "ownership_verified", "storage_delete_authorized"):
                        self.assertIs(r[field], False)

    def test_portable_build_distinct_materialization(self):
        a = fixture()
        b = fixture("vm", "hyperv-vm", "hyperv", "vhdx")
        b["artifact"]["sha256"] = "sha256:" + "5" * 64
        x, y = inspect_artifact(a), inspect_artifact(b)
        self.assertEqual(x["build_identity"], y["build_identity"])
        self.assertNotEqual(x["materialization_identity"], y["materialization_identity"])

    def test_data_contract_changes_build_identity(self):
        a = fixture()
        b = copy.deepcopy(a)
        b["data"]["contract_sha256"] = "sha256:" + "6" * 64
        self.assertNotEqual(inspect_artifact(a)["build_identity"],
                            inspect_artifact(b)["build_identity"])

    def test_deterministic_json_order(self):
        a = fixture()
        b = dict(reversed(list(a.items())))
        self.assertEqual(inspect_artifact(a), load_artifact(json.dumps(b).encode()))

    def test_reject_adapter_kind_platform_or_format_mismatch(self):
        for field, value in (("kind", "app"), ("adapter", "foundry-custom"),
                             ("platform", "hyperv"), ("format", "vhdx")):
            with self.subTest(field=field):
                a = fixture()
                if field == "kind":
                    a[field] = value
                elif field == "format":
                    a["artifact"][field] = value
                else:
                    a["target"][field] = value
                with self.assertRaises(WorkloadContractError):
                    inspect_artifact(a)

    def test_reject_missing_unknown_secret_and_permission_fields(self):
        for field in ("target", "data", "build_sha256"):
            a = fixture()
            del a[field]
            with self.assertRaises(WorkloadContractError):
                inspect_artifact(a)
        for field in ("host_path", "token", "apply_authorized", "runtime_qualified"):
            a = fixture()
            a["target"][field] = "fictional"
            with self.assertRaises(WorkloadContractError):
                inspect_artifact(a)

    def test_reject_invalid_digest_or_version(self):
        for value in ("latest", "UNKNOWN", "a/b", None):
            a = fixture()
            a["target"]["version"] = value
            with self.assertRaises(WorkloadContractError):
                inspect_artifact(a)
        for value in ("main", "sha256:" + "A" * 64, None):
            a = fixture()
            a["artifact"]["sha256"] = value
            with self.assertRaises(WorkloadContractError):
                inspect_artifact(a)

    def test_retained_data_only(self):
        a = fixture()
        a["data"]["policy"] = "delete"
        with self.assertRaises(WorkloadContractError):
            inspect_artifact(a)

    def test_reject_duplicate_nested_keys_and_bad_json(self):
        raw = json.dumps(fixture()).encode()
        duplicate = raw.replace(b'"policy": "retain-data"',
                                b'"policy": "delete", "policy": "retain-data"')
        for payload in (duplicate, b"{}", raw + b"{}", b" " * 65537, b"\xff"):
            with self.subTest(payload=payload[:50]):
                with self.assertRaises(WorkloadContractError):
                    load_artifact(payload)


if __name__ == "__main__":
    unittest.main()
