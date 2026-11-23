"""Actual disposable TrueNAS Model-Compass F2–F6 lifecycle workcell.

This is an evidence probe, not a second lifecycle engine. Every product App
transition is *planned and verified* with existing Foundry generic
truenas_target_profile/foundry_lifecycle modules. Native middleware app.*
performs only the exact action returned by those contracts. No production API
or credentials, site hosts, mutable image registry or Agent Dispatch.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(os.environ["FOUNDRY_SOURCE_ROOT"]).resolve(strict=True)
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests" / "consumers" / "model_compass"))
import foundry_lifecycle as lifecycle
import native_zfs_retention as retention

DATASET = retention.DATASET
MOUNT = retention.MOUNT
APP = retention.APP_NAME
SEED_APP = "rdte-compass-synthetic-seed"
SEED_IMAGE = "nginx@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10"
SERVICE_PORT = 18088
HOST_PORT = 18098
# Public synthetic-only test credential. Never reusable as a production secret.
SYNTHETIC_TOKEN = "R" * 64
SNAPSHOT = {"schema": "synthetic-native-zfs/v1", "receipt": "model-compass-retention-rep-001"}


class NativeQualificationError(RuntimeError):
    pass


def require(value: bool, reason: str) -> None:
    if not value:
        raise NativeQualificationError(reason)


def compose(image: str, generation: int = 1) -> dict:
    # Only the *isolated QEMU guest* uses 0.0.0.0 so its NAT-forwarded test
    # endpoint is visible on runner loopback. Real product Compose retains
    # guest 127.0.0.1-only ingress; this is NOT its production configuration.
    return {"services": {"model-compass": {
        "image": image,
        "user": "65532:65532",
        "read_only": True,
        "init": False,
        "restart": "unless-stopped",
        "ports": [f"0.0.0.0:{SERVICE_PORT}:8088"],
        "environment": {
            "COMPASS_LISTEN": ":8088",
            "COMPASS_TOKEN_FILE": "/run/secrets/compass_token",
            "COMPASS_SNAPSHOT_FILE": "/state/snapshot.json",
            "COMPASS_MODEL_BIN": "/usr/local/bin/model-compass",
            "RDTE_GENERATION": str(generation),
        },
        "volumes": [
            {"type": "bind", "source": MOUNT, "target": "/state", "read_only": True},
            {"type": "bind", "source": MOUNT + "/compass_token", "target": "/run/secrets/compass_token", "read_only": True},
        ],
        "labels": {"org.sempersupra.rdte.owner": retention.OWNERSHIP},
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "pids_limit": 64,
        "mem_limit": 268435456,
        "cpus": 1.0,
        "tmpfs": ["/tmp:rw,noexec,nosuid,size=8m"],
    }}}


def identity(value: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def seed_compose() -> dict:
    snapshot = json.dumps(SNAPSHOT, sort_keys=True, separators=(",", ":"))
    # All fixture content is literal, synthetic, source-reviewed, and bounded.
    shell = (
        "set -eu; umask 077; "
        + "printf '%s\\n' '" + snapshot + "' > /seed/snapshot.json; "
        + "printf '%s\\n' '" + SYNTHETIC_TOKEN + "' > /seed/compass_token; "
        + "chmod 0400 /seed/compass_token; chmod 0400 /seed/snapshot.json; "
        + "exec sleep 1000"
    )
    return {"services": {"seed": {
        "image": SEED_IMAGE,
        "user": "65532:65532",
        "read_only": True,
        "restart": "no",
        "entrypoint": ["/bin/sh", "-ec"],
        "command": [shell],
        "volumes": [{"type": "bind", "source": MOUNT, "target": "/seed", "read_only": False}],
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "pids_limit": 32,
        "mem_limit": 67108864,
    }}}


def http(path: str, *, auth: bool = True, method: str = "GET", data: dict | None = None,
         timeout: float = 3.0) -> tuple[int, dict]:
    headers = {"Authorization": "Bearer " + SYNTHETIC_TOKEN} if auth else {}
    body = None if data is None else json.dumps(data).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{HOST_PORT}{path}", data=body,
        headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return r.status, json.loads(r.read(1048576))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read(1048576))


def run(call, job, guest_ref: str, receipt: dict, *, state_timeout: int = 180) -> None:
    """Call only after the current installed guest has a verified pulled image."""
    require(guest_ref.startswith("127.0.0.1:15431/compass-guest-fixture@sha256:"),
            "native image pull was not exact-source-digest pinned")
    registry = lifecycle.target.load_registry(ROOT / ".foundry/truenas-target-tracks.json")
    events: list[str] = []
    native = receipt.setdefault("native_product", {
        "status": "RUNNING", "events": events,
        "state_dataset": DATASET, "full_F2_F6": "NOT_RUN",
        "host_service_exposed": "QEMU_ONLY_LOOPBACK",
        "external_token": "SYNTHETIC_TEST_ONLY",
    })
    app_owned = False
    seed_owned = False
    dataset_owned = False
    current_compose = compose(guest_ref)
    profile_methods = call("core.get_methods", [])
    if isinstance(profile_methods, dict):
        all_methods = sorted(profile_methods)
    elif isinstance(profile_methods, list):
        all_methods = sorted(profile_methods)
    else:
        raise NativeQualificationError("missing independently observed public middleware method inventory")
    expected_methods = {
        "app.query", "app.config", "app.create", "app.stop", "app.start",
        "app.update", "app.redeploy", "app.delete", "pool.dataset.create",
        "pool.dataset.delete", "pool.dataset.query", "filesystem.setperm", "filesystem.stat",
    }
    require(expected_methods.issubset(set(all_methods)),
            "exact guest lacks expected native lifecycle/ZFS/permission methods")
    native["method_contract"] = "LIVE_MIDDLEWARE_LIST_VERIFIED"

    def query_app(name: str):
        result = call("app.query", [[[ "id", "=", name ]]])
        require(isinstance(result, list), "native app.query not a list")
        return result

    def query_dataset():
        result = call("pool.dataset.query", [[[ "id", "=", DATASET ]]])
        require(isinstance(result, list), "native dataset query not a list")
        return result

    def file_stat(path: str):
        value = call("filesystem.stat", [path])
        require(isinstance(value, dict) and value.get("realpath") == path,
                "guest filesystem.stat missing exact realpath")
        return value

    def wait_running(name: str, *, timeout: int = state_timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            q = query_app(name)
            if len(q) == 1 and q[0].get("state") == "RUNNING" and (
                q[0].get("active_workloads") or {}
            ).get("containers", 0) >= 1:
                return q[0]
            if q and q[0].get("state") in {"CRASHED", "ERROR"}:
                raise NativeQualificationError(f"native app {name} crashed")
            time.sleep(2)
        raise NativeQualificationError(f"native app {name} not RUNNING")

    def wait_state(name: str, state: str):
        end = time.monotonic() + state_timeout
        while time.monotonic() < end:
            q = query_app(name)
            if len(q) == 1 and q[0].get("state") == state:
                return q[0]
            time.sleep(2)
        raise NativeQualificationError(f"native app {name} not {state}")

    def remove_app(name: str):
        if query_app(name):
            job(call("app.delete", [name, {
                "remove_images": False,
                "remove_ix_volumes": False,
                "force_remove_custom_app": False,
            }]), f"{name}_delete")
        require(not query_app(name), "native app removal left residue")

    def assert_external():
        require(len(query_dataset()) == 1, "owned ZFS dataset disappeared")
        t = file_stat(MOUNT + "/compass_token")
        s = file_stat(MOUNT + "/snapshot.json")
        require(t.get("uid") == 65532 and (t.get("mode", 0) & 0o777) == 0o400
                and t.get("size") >= 32 and not t.get("acl"), "token mode/owner/ACL invalid")
        require(s.get("uid") == 65532 and (s.get("mode", 0) & 0o777) == 0o400
                and s.get("size") > 30, "external snapshot owner/size invalid")
        return (t["size"], s["size"])

    def assert_api():
        deadline = time.monotonic() + state_timeout
        while time.monotonic() < deadline:
            try:
                code, health = http("/healthz", auth=False)
                if code == 200 and health.get("status") == "UP":
                    break
            except (OSError, ValueError, urllib.error.URLError):
                pass
            time.sleep(2)
        else:
            raise NativeQualificationError("guest app HTTP unreachable through runner-loopback NAT")
        code, _ = http("/v1/snapshot", auth=False)
        require(code == 401, "unauthorized snapshot accepted")
        code, snapshot = http("/v1/snapshot")
        require(code == 200 and snapshot.get("status") == "EXTERNAL_SNAPSHOT_UNVERIFIED"
                and snapshot.get("snapshot") == SNAPSHOT, "external ZFS snapshot data mismatch")
        code, advisory = http(
            "/v1/recommend", method="POST",
            data={"task_family": "code_refactor", "estimated_context_tokens": 1024},
        )
        require(code == 200 and advisory.get("qualification") == "UNKNOWN"
                and advisory.get("automatic_admission") is False,
                "unverified advisory improperly admitted or unavailable")
        return hashlib.sha256(json.dumps(snapshot["snapshot"], sort_keys=True).encode()).hexdigest()

    def observed(expected_compose: dict | None, completed: list[str] | None = None):
        q = query_app(APP)
        require(len(q) <= 1, "multiple ambiguous app observations")
        if q:
            require(expected_compose is not None, "foreign or unplanned app observed")
            native_config = call("app.config", [APP])
            require(native_config.get("services", {}).get("model-compass", {}).get("image")
                    == guest_ref, "native OCI image identity drift")
            svc = native_config["services"]["model-compass"]
            require(svc.get("user") == "65532:65532" and svc.get("read_only") is True,
                    "native service nonroot/read-only drift")
            require(svc.get("volumes") == expected_compose["services"]["model-compass"]["volumes"],
                    "native external state/token mount drift")
            require(svc.get("labels", {}).get("org.sempersupra.rdte.owner") == retention.OWNERSHIP,
                    "native app synthetic owner marker drift")
            require(svc.get("environment", {}).get("RDTE_GENERATION")
                    == expected_compose["services"]["model-compass"]["environment"]["RDTE_GENERATION"],
                    "native generation config drift")
            require(app_owned, "foreign app was not created by this isolated test")
            app = {"name": APP, "present": True, "state": q[0]["state"],
                   "active_workloads": (q[0].get("active_workloads") or {}).get("containers", 0),
                   "custom_app": True, "materialization_identity": identity(expected_compose)}
            owner = {"state": "owned"}
        else:
            app = {"present": False, "state": "ABSENT", "active_workloads": 0}
            owner = {"state": "absent"}
        return {
            "schema_version": 1,
            "system": {"version": retention.TARGET_VERSION, "platform": "linux-amd64"},
            "capabilities": {"methods": all_methods},
            "app": app, "ownership": owner,
            "operation": {"state": "stable", "completed_tokens": completed or []},
        }

    def lifecycle_plan(operation: str, expect_action: str, expected_compose: dict | None,
                       *, token: str | None = None, completed: list[str] | None = None):
        intent = {"schema": lifecycle.SCHEMA, "operation": operation,
                  "adapter": "foundry-custom", "app_name": APP,
                  "materialization_identity": identity(expected_compose or current_compose)}
        if operation in {"ENSURE_ABSENT", "REINSTALL"}:
            intent["delete_policy"] = "retain-data"
        if token:
            intent["operation_token"] = token
        snapshot = observed(expected_compose, completed)
        plan = lifecycle.plan(snapshot, intent, registry)
        require(plan["status"] == "READY" and plan["action"] == expect_action,
                f"generic Foundry lifecycle declined {operation}/{expect_action}")
        require(plan["preconditions"]["delete_owned_storage_allowed"] is False
                and plan["preconditions"]["foreign_state_adoption_allowed"] is False,
                "generic lifecycle safety guards relaxed")
        return intent, plan

    try:
        require(not query_app(APP) and not query_app(SEED_APP), "foreign/unowned fixture app present")
        require(not query_dataset(), "foreign preexisting experiment dataset present")
        # Existing TrueNAS middleware performs the only pool dataset create.
        created = call("pool.dataset.create", [{"name": DATASET, "type": "FILESYSTEM"}])
        require(isinstance(created, dict) and created.get("id") == DATASET,
                "native dataset.create identity readback mismatch")
        dataset_owned = True
        require(len(query_dataset()) == 1, "native dataset.create not observed")
        events.append("F2_OWNED_ZFS_CREATE")
        # Official public filesystem.setperm, never private file_receive.
        perms = call("filesystem.setperm", [{"path": MOUNT, "uid": 65532, "gid": 65532,
                                             "mode": "700", "options": {"stripacl": True}}])
        if isinstance(perms, int) and not isinstance(perms, bool):
            job(perms, "dataset_setperm")
        root = file_stat(MOUNT)
        require(root["uid"] == 65532 and (root["mode"] & 0o777) == 0o700
                and not root.get("acl"), "dataset owner/perms/ACL not applied")
        events.append("F2_NATIVE_DATASET_PERMISSION_READBACK")
        # A pinned public fixture container seeds ONLY synthetic data as nonroot.
        seed_job = call("app.create", [{"app_name": SEED_APP, "custom_app": True,
                                        "custom_compose_config": seed_compose()}])
        seed_owned = True  # a submitted native job may fail after creating partial App state
        job(seed_job, "synthetic_seed_create")
        wait_running(SEED_APP)
        until = time.monotonic() + state_timeout
        while time.monotonic() < until:
            try:
                baseline = assert_external()
                break
            except (NativeQualificationError, OSError, RuntimeError):
                time.sleep(2)
        else:
            raise NativeQualificationError("synthetic state seed did not materialize on external ZFS")
        events.append("F2_SYNTHETIC_FILES_NATIVE_STAT_READBACK")
        remove_app(SEED_APP)
        seed_owned = False
        require(assert_external() == baseline, "external files changed after seeder removal")
        events.append("F2_EXTERNAL_STATE_RETAINED_AFTER_SEED_APP_DELETE")

        # Existing Foundry generic target planner owns all materialization choices.
        desired = {"app_name": APP, "materialization_identity": identity(current_compose)}
        p = lifecycle.target.plan(observed(None), desired, registry)
        native["generic_create_plan"] = {
            "status": p.get("status"),
            "action": p.get("action"),
            "blockers": p.get("blockers", [])[:8],
            "missing_public_methods": p.get("missing_methods", []),
            "profile_missing_methods": p.get("target", {}).get("missing_profile_methods", []),
            "target_apply_qualified": p.get("target", {}).get("apply_qualified"),
        }
        require(p["status"] == "READY" and p["action"] == "CREATE",
                "Foundry generic materialization denied CREATE")
        events.append("F3_GENERIC_CREATE_READY")
        events.append("F3_NATIVE_COMPASS_CREATE_SUBMITTED")
        create_job = call("app.create", [{"app_name": APP, "custom_app": True,
                                         "custom_compose_config": current_compose}])
        app_owned = True
        job(create_job, "compass_create")
        events.append("F3_NATIVE_COMPASS_CREATE_JOB_SUCCESS")
        wait_running(APP)
        a = observed(current_compose)
        require(lifecycle.target.verify(a, desired, registry)["status"] == "VERIFIED",
                "Foundry generic verify rejected installed app")
        receipt["guest_compass_app_created"] = True
        events.append("F3_NATIVE_COMPASS_APP_CREATE_FOUNDY_PLAN_VERIFY")
        initial_hash = assert_api()
        events.append("F3_REAL_AUTHENTICATED_GUEST_APP_SNAPSHOT_AND_ADVISORY_UNKNOWN")
        intent, _ = lifecycle_plan("ENSURE_STOPPED", "STOP", current_compose)
        job(call("app.stop", [APP]), "compass_stop")
        wait_state(APP, "STOPPED")
        require(lifecycle.verify(observed(current_compose), intent, registry)["status"] == "VERIFIED",
                "Foundry stopped-state independent verification failed")
        events.append("F4_STOP_VERIFIED")
        intent, _ = lifecycle_plan("ENSURE_RUNNING", "START", current_compose)
        job(call("app.start", [APP]), "compass_start")
        wait_running(APP)
        require(lifecycle.verify(observed(current_compose), intent, registry)["status"] == "VERIFIED",
                "Foundry restarted-state independent verification failed")
        require(assert_api() == initial_hash, "state changed across actual app restart")
        events.append("F4_START_AND_EXTERNAL_ZFS_RETAINED")

        # Mutate only a synthetic environment generation, not image or storage.
        next_compose = compose(guest_ref, 2)
        target_plan = lifecycle.target.plan(
            observed(current_compose),
            {"app_name": APP, "materialization_identity": identity(next_compose)},
            registry,
        )
        require(target_plan["status"] == "READY" and target_plan["action"] == "UPDATE",
                "Foundry generic target planner declined controlled config update")
        job(call("app.update", [APP, {"custom_compose_config": next_compose}]), "compass_update")
        wait_running(APP)
        current_compose = next_compose
        require(lifecycle.target.verify(
            observed(current_compose),
            {"app_name": APP, "materialization_identity": identity(current_compose)},
            registry,
        )["status"] == "VERIFIED", "native UPDATE config/readback mismatch")
        events.append("F5_UPDATE_GENERATION_AND_INDEPENDENT_READBACK")
        intent, _ = lifecycle_plan("REDEPLOY", "REDEPLOY", current_compose, token="synthetic-redeploy-1")
        job(call("app.redeploy", [APP]), "compass_redeploy")
        wait_running(APP)
        require(assert_api() == initial_hash, "state changed on redeploy")
        require(lifecycle.verify(
            observed(current_compose, ["synthetic-redeploy-1"]), intent, registry
        )["status"] == "VERIFIED", "Foundry redeploy verification failed")
        events.append("F5_REDEPLOY_AND_EXTERNAL_ZFS_RETAINED")
        _, no_op = lifecycle_plan("ENSURE_RUNNING", "NOOP", current_compose)
        require(no_op["required_method"] is None, "NOOP should require no native mutation")
        events.append("F5_REPLAN_NOOP")

        token = "synthetic-reinstall-1"
        _, step = lifecycle_plan("REINSTALL", "DELETE_FOR_REINSTALL", current_compose, token=token)
        require(step["required_method"] == "app.delete", "reinstall delete not generic")
        remove_app(APP)
        app_owned = False
        require(assert_external() == baseline, "ZFS files not retained on app uninstall")
        events.append("F6_DELETE_APP_RETAIN_ZFS_NATIVE_STAT")
        _, create_handoff = lifecycle_plan("REINSTALL", "CREATE_HANDOFF", None, token=token)
        require(create_handoff["handoff"] == "truenas_target_profile.plan", "reinstall must hand off to generic materializer")
        desired = {"app_name": APP, "materialization_identity": identity(current_compose)}
        create = lifecycle.target.plan(observed(None), desired, registry)
        require(create["status"] == "READY" and create["action"] == "CREATE",
                "generic create plan rejected reinstall")
        events.append("F6_NATIVE_COMPASS_REINSTALL_SUBMITTED")
        reinstall_job = call("app.create", [{"app_name": APP, "custom_app": True,
                                            "custom_compose_config": current_compose}])
        app_owned = True
        job(reinstall_job, "compass_reinstall")
        wait_running(APP)
        require(assert_api() == initial_hash, "retained ZFS snapshot changed on native reinstall")
        require(lifecycle.verify(
            observed(current_compose, [token]),
            {"schema": lifecycle.SCHEMA, "operation": "REINSTALL",
             "adapter": "foundry-custom", "app_name": APP,
             "materialization_identity": identity(current_compose),
             "delete_policy": "retain-data", "operation_token": token},
            registry,
        )["status"] == "VERIFIED", "native reinstall Foundry verification failed")
        events.append("F6_REINSTALL_RETAINED_DATA_AND_VALID_AUTH")
        receipt["native_F2_F6"] = "GUEST_REAL_PASS"
        native["full_F2_F6"] = "GUEST_REAL_PASS"
        native["status"] = "VERIFIED"
        receipt["evidence"]["native_product_F2_F6"] = "GUEST_REAL_PASS"
    finally:
        # No foreign adoption: this process created all owned resources.
        if app_owned:
            try:
                remove_app(APP)
                app_owned = False
                events.append("CLEANUP_NATIVE_PRODUCT_APP_ABSENT")
            except Exception:
                native["cleanup_error"] = "product_app_residual_or_unknown"
        if seed_owned:
            try:
                remove_app(SEED_APP)
                seed_owned = False
                events.append("CLEANUP_NATIVE_SEED_APP_ABSENT")
            except Exception:
                native["cleanup_error"] = "seed_app_residual_or_unknown"
        if dataset_owned and not app_owned and not seed_owned:
            try:
                require(assert_external() == baseline, "external state drift before final owned cleanup")
                require(not query_app(APP) and not query_app(SEED_APP), "App attached to dataset at cleanup")
                result = call("pool.dataset.delete", [DATASET, {"recursive": False, "force": False}])
                if isinstance(result, int) and not isinstance(result, bool):
                    job(result, "owned_dataset_delete")
                require(not query_dataset(), "owned dataset remained after explicit cleanup")
                events.append("CLEANUP_OWNED_ZFS_DATASET_ABSENT")
            except Exception:
                native["cleanup_error"] = "owned_dataset_residual_or_unknown"
        if "cleanup_error" in native:
            receipt["oracleSatisfied"] = False
            native["status"] = "CLEANUP_FAILURE"
            receipt["native_F2_F6"] = "NOT_ACCEPTED"
            raise NativeQualificationError("native product/ZFS cleanup failed")
