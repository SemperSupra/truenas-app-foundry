#!/usr/bin/env python3
"""Validate a release-pinned TrueNAS middleware source/materialization contract.

This intentionally does not emulate TrueNAS. It verifies that an exact upstream
checkout still contains the source identities and semantics recorded by a
Foundry compatibility profile. Live appliance behavior remains a HIL concern.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def git_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


def fail(message: str) -> None:
    raise SystemExit(f"source-contract validation failed: {message}")


def validate_materialization_profile(profile: dict) -> dict:
    features = profile.get("platform_features")
    if not isinstance(features, dict):
        fail("schema v2 profile must define platform_features")

    required = {
        "definitions/certificate",
        "normalize/ix_volume",
        "normalize/acl",
        "definitions/node_bind_ip",
        "definitions/certificate_authority",
        "definitions/gpu_configuration",
    }
    missing = required - set(features)
    if missing:
        fail(f"materialization feature matrix missing {sorted(missing)!r}")

    certificate = features["definitions/certificate"]
    if certificate.get("mvp_status") != "supported":
        fail("certificate normalization must be explicitly supported for the MVP")
    if certificate.get("resolver_method") != "certificate.get_instance":
        fail("certificate resolver must match middleware certificate.get_instance")
    if certificate.get("reserved_target") != "ix_certificates":
        fail("certificate resolver must target ix_certificates")
    if "post-render-lifecycle-shim" not in certificate.get("parity_class", []):
        fail("certificate feature must record the Custom App lifecycle shim")

    volume = features["normalize/ix_volume"]
    if volume.get("mvp_status") != "supported" or volume.get("reserved_target") != "ix_volumes":
        fail("ixVolume normalization must be an explicit MVP-supported ix_volumes feature")

    policies = profile.get("policies", {})
    if policies.get("unknown_active_ref") != "fail-closed":
        fail("materialization profile must fail closed on unknown active refs")
    if policies.get("desired_state_authority") != "foundry":
        fail("Foundry must remain desired-state authority")
    if policies.get("private_material_in_public_evidence") != "prohibited":
        fail("public evidence policy must prohibit private material")

    return {
        name: {
            "mvp_status": value.get("mvp_status"),
            "parity_class": value.get("parity_class", []),
        }
        for name, value in sorted(features.items())
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        default=".foundry/truenas-compatibility/25.04.2.6-materialization.json",
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--evidence", default="source-contract-evidence.json")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    source_root = Path(args.source_root)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    schema_version = profile.get("schema_version")
    if schema_version not in {1, 2}:
        fail("unsupported profile schema_version")

    middleware = profile.get("middleware", {})
    expected_commit = middleware.get("commit", "").strip()
    if len(expected_commit) != 40:
        fail("middleware.commit must be a full 40-character SHA")

    actual_commit = git_head(source_root)
    if actual_commit != expected_commit:
        fail(f"checkout HEAD {actual_commit} != pinned commit {expected_commit}")

    checked_files = []
    for entry in profile.get("source_contract", []):
        rel = entry.get("path", "")
        expected_blob = entry.get("blob_sha", "")
        if not rel or len(expected_blob) != 40:
            fail(f"invalid source contract entry: {entry!r}")

        path = source_root / rel
        if not path.is_file():
            fail(f"missing upstream source file {rel}")

        data = path.read_bytes()
        actual_blob = git_blob_sha(data)
        if actual_blob != expected_blob:
            fail(f"blob drift for {rel}: {actual_blob} != {expected_blob}")

        text = data.decode("utf-8")
        missing = [needle for needle in entry.get("contains", []) if needle not in text]
        if missing:
            fail(f"semantic markers missing from {rel}: {missing!r}")

        checked_files.append(
            {
                "path": rel,
                "blob_sha": actual_blob,
                "semantic_markers": len(entry.get("contains", [])),
            }
        )

    assumptions = profile.get("provider_assumptions", {})
    app_states = assumptions.get("app_states", [])
    if not isinstance(app_states, list) or not all(isinstance(x, str) for x in app_states):
        fail("provider_assumptions.app_states must be an array of strings")
    if len(app_states) != len(set(app_states)):
        fail("provider_assumptions.app_states must not contain duplicates")
    required_states = {"CRASHED", "DEPLOYING", "RUNNING", "STOPPED"}
    missing_states = required_states - set(app_states)
    if missing_states:
        fail(f"Apps state contract is missing required core states: {sorted(missing_states)!r}")

    required_workload_fields = {
        "containers",
        "used_ports",
        "container_details",
        "volumes",
        "images",
        "networks",
    }
    if set(assumptions.get("active_workload_fields", [])) != required_workload_fields:
        fail("active_workload_fields do not match the recorded Apps query contract")

    if assumptions.get("compose_action_timeout_seconds") != 1200:
        fail("Apps profile must record the observed 1200-second compose action timeout")

    delete_semantics = assumptions.get("delete_semantics", {})
    if delete_semantics.get("compose_volumes_removed") is not True:
        fail("profile must record Compose volume removal on app deletion")
    if delete_semantics.get("ix_volumes_removed_only_when_requested") is not True:
        fail("profile must record conditional ixVolume dataset deletion")

    runtime_api = profile.get("runtime_api")
    if not isinstance(runtime_api, dict):
        fail("materialization profile must define runtime_api")
    if runtime_api.get("transport") != "middleware-json-rpc":
        fail("runtime_api.transport must be middleware-json-rpc")
    if runtime_api.get("version_probe") != "system.version":
        fail("runtime_api.version_probe must be system.version")
    if runtime_api.get("capability_probe") != "core.get_methods":
        fail("runtime_api.capability_probe must be core.get_methods")
    for key, method, job_backed in (
        ("app_query", "app.query", None),
        ("app_config", "app.config", None),
        ("app_create", "app.create", True),
        ("app_update", "app.update", True),
        ("app_stop", "app.stop", True),
        ("app_start", "app.start", True),
        ("app_redeploy", "app.redeploy", True),
        ("app_delete", "app.delete", True),
    ):
        contract = runtime_api.get(key)
        if not isinstance(contract, dict) or contract.get("method") != method:
            fail(f"runtime_api.{key} must bind {method}")
        if job_backed is not None and contract.get("job_backed") is not job_backed:
            fail(f"runtime_api.{key}.job_backed must be {job_backed}")
    if runtime_api["app_create"].get("arguments") != "single-dictionary":
        fail("current qualified releases require app.create single-dictionary payload")
    if runtime_api["app_update"].get("arguments") != "app_name-plus-update-dictionary":
        fail("current qualified releases require app.update app_name + update dictionary")
    for key in ("app_stop", "app_start", "app_redeploy"):
        if runtime_api[key].get("arguments") != "app_name":
            fail(f"current qualified releases require runtime_api.{key} app_name argument")
    if runtime_api["app_delete"].get("arguments") != "app_name-plus-options":
        fail("current qualified releases require app.delete app_name + options")

    feature_summary = validate_materialization_profile(profile) if schema_version >= 2 else None

    evidence = {
        "status": "PASS",
        "profile_id": profile.get("profile_id"),
        "runtime_target": profile.get("runtime_target"),
        "truenas_version": profile.get("truenas_version"),
        "middleware_repository": middleware.get("repository"),
        "middleware_release_ref": middleware.get("release_ref"),
        "middleware_commit": actual_commit,
        "checked_files": checked_files,
        "provider_assumptions": assumptions,
        "runtime_api": runtime_api,
        "platform_features": feature_summary,
        "scope": profile.get("scope", {}),
    }
    Path(args.evidence).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
