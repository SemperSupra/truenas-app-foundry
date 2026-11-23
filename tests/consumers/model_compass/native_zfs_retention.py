"""Deterministic external-ZFS ownership and retention gate for a future native
TrueNAS 25.04.2.6 model-compass F2-F6 workcell.

Source-only evaluator. No middleware request, storage mutation, secret creation,
Docker invocation, registry image publication or separate app lifecycle executor.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "foundry-compass-zfs-retention-preflight/v1"
SOURCE_SHA = "6e88ccbe09f7f0989a8db4e75967654d409f8f64"
TARGET_VERSION = "TrueNAS-25.04.2.6"
DATASET = "rdtepool/rdte-model-compass-state"
MOUNT = "/mnt/" + DATASET
APP_NAME = "rdte-model-compass"
UID = 65532
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
OWNERSHIP = hashlib.sha256(f"{SOURCE_SHA}:{TARGET_VERSION}:{DATASET}:{APP_NAME}:synthetic-only".encode()).hexdigest()


def template() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "source_sha": SOURCE_SHA,
        "target_version": TARGET_VERSION,
        "scope": "public_disposable_kvm_only",
        "dataset": {"id": DATASET, "mountpoint": MOUNT, "owner_receipt": OWNERSHIP},
        "app_name": APP_NAME,
        "run_user": UID,
        "external_paths": {
            "snapshot": MOUNT + "/snapshot.json",
            "token": MOUNT + "/compass_token",
        },
        "app_mounts": {
            "/state": {"source": MOUNT, "read_only": True},
            "/run/secrets/compass_token": {
                "source": MOUNT + "/compass_token", "read_only": True,
            },
        },
        "expected_secret": {"uid": UID, "mode": "0400", "min_bytes": 32},
        "expected_snapshot": {"status": "EXTERNAL_SNAPSHOT_UNVERIFIED"},
        "first_seed_method": "OWNER_ADMITTED_SYNTHETIC_NATIVE_FIXTURE_ONLY",
        "filesystem_file_receive_public_api": False,
        "app_lifecycle_executor": "EXISTING_FOUNDRY_GENERIC_ONLY",
        "app_delete_policy": "retain-data",
        "dataset_delete_policy": "never_by_app_lifecycle",
        "native_F2_F6": "NOT_RUN",
        "live_trueNAS_hil": "NOT_RUN",
    }


def deny(reason: str) -> dict:
    return {
        "schema": SCHEMA,
        "status": "BLOCKED",
        "operation": "NONE",
        "reason": reason,
        "native_F2_F6": "NOT_RUN",
    }


def evaluate(
    request: dict,
    observed: dict,
    operation: str = "ENSURE_RUNNING",
    *,
    explicit_dataset_cleanup: bool = False,
) -> dict:
    """Plan only: represent unsupported/foreign/unverified as DENIED, never apply."""
    expected = template()
    if not isinstance(request, dict) or request != expected:
        return deny("source_bound_request_or_policy_drift")
    if not isinstance(observed, dict):
        return deny("missing_observation")
    if observed.get("target_version") != TARGET_VERSION or observed.get("scope") != "public_disposable_kvm_only":
        return deny("wrong_target_or_live_site")
    if observed.get("native_image_transport") != "SUPPORTED":
        return deny("guest_image_transport_not_qualified")
    if not bool(DIGEST_RE.fullmatch(str(observed.get("image_digest", "")))):
        return deny("missing_immutable_oci_digest")
    dataset = observed.get("dataset")
    if dataset is None:
        if operation == "ENSURE_RUNNING":
            return {
                "schema": SCHEMA, "status": "PLAN_ONLY", "operation": "CREATE_OWNED_DATASET",
                "native_F2_F6": "NOT_RUN", "dataset_name": DATASET,
                "dataset_api": "pool.dataset.create",
                "owner_receipt": OWNERSHIP,
                "next_gate": "independent_owner_provenance_and_secret_seed",
            }
        return deny("dataset_absent")
    if not isinstance(dataset, dict) or dataset.get("id") != DATASET or dataset.get("mountpoint") != MOUNT:
        return deny("foreign_dataset_or_path")
    if dataset.get("owner_receipt") != OWNERSHIP or dataset.get("ownership") != "experiment_owned":
        return deny("foreign_dataset_owner")
    if dataset.get("mount_read_only_to_product") is not True:
        return deny("container_may_modify_durable_data")
    secret = observed.get("secret")
    snapshot = observed.get("snapshot")
    if not isinstance(secret, dict) or secret.get("uid") != UID or secret.get("mode") != "0400" or secret.get("bytes", 0) < 32:
        return deny("external_secret_missing_or_insecure")
    if not isinstance(snapshot, dict) or snapshot.get("external_source") is not True or snapshot.get("valid_json") is not True:
        return deny("external_snapshot_not_ready")
    app = observed.get("app")
    if app is not None:
        if not isinstance(app, dict) or app.get("name") != APP_NAME:
            return deny("foreign_app")
        if app.get("image_digest") != observed["image_digest"]:
            return deny("app_digest_drift")
        if app.get("owner_receipt") != OWNERSHIP:
            return deny("app_not_owned")
    if operation == "ENSURE_RUNNING":
        if app is None:
            action = "CREATE_VIA_EXISTING_FOUNDRY"
        elif app.get("state") == "RUNNING":
            action = "NOOP"
        elif app.get("state") == "STOPPED":
            action = "START_VIA_EXISTING_FOUNDRY"
        else:
            return deny("uncertain_app_state")
    elif operation == "ENSURE_ABSENT":
        action = "DELETE_APP_RETAIN_DATA_VIA_FOUNDRY" if app else "NOOP_DATA_RETAINED"
    elif operation == "REDEPLOY":
        if app is None or app.get("state") != "RUNNING":
            return deny("cannot_redeploy_missing_or_inactive_app")
        action = "REDEPLOY_VIA_EXISTING_FOUNDRY"
    elif operation == "CLEANUP_OWNED_DATASET":
        if app is not None or explicit_dataset_cleanup is not True:
            return deny("dataset_cleanup_requires_absent_app_and_explicit_owner_intent")
        action = "EXPLICIT_OWNED_DATASET_DELETE_SEPARATE_FROM_APP"
    else:
        return deny("unsupported_operation")
    return {
        "schema": SCHEMA, "status": "PLAN_ONLY",
        "operation": action,
        "owned_dataset": DATASET,
        "retention": "retain-on-app-deletion",
        "source_sha": SOURCE_SHA,
        "native_F2_F6": "NOT_RUN",
        "executor": "EXISTING_FOUNDRY_GENERIC_ONLY",
        "side_effects": False,
    }


if __name__ == "__main__":
    print(json.dumps(template(), indent=2, sort_keys=True))
