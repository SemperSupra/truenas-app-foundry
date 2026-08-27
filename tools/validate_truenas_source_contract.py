#!/usr/bin/env python3
"""Validate a release-pinned TrueNAS middleware source contract.

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        default=".foundry/truenas-compatibility/25.04.1-apps.json",
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--evidence", default="source-contract-evidence.json")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    source_root = Path(args.source_root)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    if profile.get("schema_version") != 1:
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
    required_states = {"CRASHED", "DEPLOYING", "RUNNING", "STOPPED"}
    if set(assumptions.get("app_states", [])) != required_states:
        fail("Apps state contract must explicitly enumerate CRASHED/DEPLOYING/RUNNING/STOPPED")

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

    delete_semantics = assumptions.get("delete_semantics", {})
    if delete_semantics.get("compose_volumes_removed") is not True:
        fail("profile must record Compose volume removal on app deletion")
    if delete_semantics.get("ix_volumes_removed_only_when_requested") is not True:
        fail("profile must record conditional ixVolume dataset deletion")

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
        "scope": profile.get("scope", {}),
    }
    Path(args.evidence).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
