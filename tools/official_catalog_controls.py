#!/usr/bin/env python3
"""Validate exact-source official-catalog controls for the TrueNAS Foundry matrix.

This is a source/discovery gate only. It does not contact or mutate TrueNAS.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


class ControlError(RuntimeError):
    pass


HEX40 = re.compile(r"^[0-9a-f]{40}$")
UNIVERSAL_ROLES = {"universal-candidate-primary", "universal-candidate-secondary"}
ROLES = UNIVERSAL_ROLES | {"specialized-control"}


def load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ControlError(f"{label} must be an object")
    return value


def required_targets(registry: dict[str, Any]) -> list[str]:
    targets = registry.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ControlError("target registry has no targets")
    versions = [str(item.get("version", "")) for item in targets if isinstance(item, dict)]
    if any(not value for value in versions) or len(versions) != len(set(versions)):
        raise ControlError("target registry versions must be non-empty and unique")
    return versions


def git(*args: str, cwd: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ControlError(f"git {' '.join(args)} failed: {exc}") from exc
    return proc.stdout.strip()


def validate_catalog_checkout(manifest: dict[str, Any], catalog_dir: Path) -> None:
    source = manifest.get("catalog_source")
    if not isinstance(source, dict):
        raise ControlError("catalog_source must be an object")
    expected_commit = str(source.get("commit", ""))
    observed_commit = git("rev-parse", "HEAD", cwd=catalog_dir)
    if observed_commit != expected_commit:
        raise ControlError(
            f"catalog checkout commit mismatch: expected {expected_commit}, observed {observed_commit}"
        )

    for control in manifest.get("controls", []):
        if not isinstance(control, dict):
            raise ControlError("controls entries must be objects")
        path = str(control.get("source_path", ""))
        expected_blob = str(control.get("source_blob_sha", ""))
        observed_blob = git("rev-parse", f"HEAD:{path}", cwd=catalog_dir)
        if observed_blob != expected_blob:
            raise ControlError(
                f"{control.get('id')} source blob mismatch: expected {expected_blob}, observed {observed_blob}"
            )
        fixture = control.get("runtime_fixture_source")
        if fixture is not None:
            if not isinstance(fixture, dict):
                raise ControlError(f"{control.get('id')}: runtime_fixture_source must be an object")
            fixture_path = str(fixture.get("path", ""))
            fixture_blob = str(fixture.get("blob_sha", ""))
            if not fixture_path or not HEX40.fullmatch(fixture_blob):
                raise ControlError(f"{control.get('id')}: runtime fixture source identity is invalid")
            observed_fixture_blob = git("rev-parse", f"HEAD:{fixture_path}", cwd=catalog_dir)
            if observed_fixture_blob != fixture_blob:
                raise ControlError(
                    f"{control.get('id')} runtime fixture blob mismatch: "
                    f"expected {fixture_blob}, observed {observed_fixture_blob}"
                )


def validate(manifest: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != "truenas-foundry-official-catalog-controls/v1":
        raise ControlError("unsupported controls schema")

    source = manifest.get("catalog_source")
    if not isinstance(source, dict):
        raise ControlError("catalog_source must be an object")
    commit = str(source.get("commit", ""))
    if not HEX40.fullmatch(commit):
        raise ControlError("catalog_source.commit must be an exact 40-hex commit")

    policy = manifest.get("policy")
    if not isinstance(policy, dict):
        raise ControlError("policy must be an object")
    if policy.get("native_catalog_semantics_required") is not True:
        raise ControlError("native catalog semantics must be required")
    if policy.get("custom_app_fallback_allowed") is not False:
        raise ControlError("Custom App fallback must remain prohibited")

    required = required_targets(registry)
    required_set = set(required)
    controls = manifest.get("controls")
    if not isinstance(controls, list) or not controls:
        raise ControlError("controls must be a non-empty array")

    seen: set[str] = set()
    summaries: list[dict[str, Any]] = []
    primary_count = 0
    for item in controls:
        if not isinstance(item, dict):
            raise ControlError("controls entries must be objects")
        cid = str(item.get("id", ""))
        if not cid or cid in seen:
            raise ControlError("control ids must be non-empty and unique")
        seen.add(cid)

        role = str(item.get("role", ""))
        if role not in ROLES:
            raise ControlError(f"{cid}: unsupported role {role!r}")
        if role == "universal-candidate-primary":
            primary_count += 1
        if item.get("native_catalog_semantics") is not True:
            raise ControlError(f"{cid}: native catalog semantics must remain enabled")
        if item.get("custom_app_fallback") is not False:
            raise ControlError(f"{cid}: Custom App fallback is prohibited")

        for field in ("source_path", "source_blob_sha", "catalog_version", "app_version", "lib_version", "lib_version_hash"):
            if not isinstance(item.get(field), str) or not item[field]:
                raise ControlError(f"{cid}: {field} must be a non-empty string")
        if role in UNIVERSAL_ROLES:
            fixture = item.get("runtime_fixture_source")
            values = item.get("runtime_create_values")
            if not isinstance(fixture, dict):
                raise ControlError(f"{cid}: universal candidate requires runtime_fixture_source")
            if not isinstance(fixture.get("path"), str) or not fixture["path"]:
                raise ControlError(f"{cid}: runtime fixture path must be non-empty")
            if not isinstance(fixture.get("blob_sha"), str) or not HEX40.fullmatch(fixture["blob_sha"]):
                raise ControlError(f"{cid}: runtime fixture blob must be exact Git identity")
            if not isinstance(values, dict) or not values:
                raise ControlError(f"{cid}: universal candidate requires runtime_create_values")
        if not HEX40.fullmatch(item["source_blob_sha"]):
            raise ControlError(f"{cid}: source_blob_sha must be exact Git blob identity")
        if not re.fullmatch(r"[0-9a-f]{64}", item["lib_version_hash"]):
            raise ControlError(f"{cid}: lib_version_hash must be exact SHA256 identity")

        declared = item.get("target_versions", [])
        qualified = item.get("runtime_qualified_targets", [])
        if not isinstance(declared, list) or not all(isinstance(x, str) for x in declared):
            raise ControlError(f"{cid}: target_versions must be an array of strings")
        if not isinstance(qualified, list) or not all(isinstance(x, str) for x in qualified):
            raise ControlError(f"{cid}: runtime_qualified_targets must be an array of strings")
        if len(declared) != len(set(declared)) or len(qualified) != len(set(qualified)):
            raise ControlError(f"{cid}: target lists must not contain duplicates")
        if not set(qualified).issubset(set(declared)):
            raise ControlError(f"{cid}: runtime-qualified targets must be declared targets")

        if role in UNIVERSAL_ROLES:
            if set(declared) != required_set:
                missing = sorted(required_set - set(declared))
                extra = sorted(set(declared) - required_set)
                raise ControlError(
                    f"{cid}: universal candidate matrix coverage mismatch; missing={missing}, extra={extra}"
                )
            fully_runtime_qualified = set(qualified) == required_set
            if bool(item.get("universal_qualified")) != fully_runtime_qualified:
                raise ControlError(
                    f"{cid}: universal_qualified must exactly reflect all-target runtime qualification"
                )
        else:
            if item.get("universal_qualified") is not False:
                raise ControlError(f"{cid}: specialized control cannot claim universal qualification")
            fully_runtime_qualified = False

        summaries.append(
            {
                "id": cid,
                "role": role,
                "declared_targets": declared,
                "runtime_qualified_targets": qualified,
                "pending_targets": sorted(set(declared) - set(qualified)),
                "universal_qualified": fully_runtime_qualified,
            }
        )

    if primary_count != 1:
        raise ControlError("exactly one primary universal candidate is required")

    return {
        "schema": "truenas-foundry-official-catalog-controls-validation/v1",
        "status": "PASS",
        "catalog_commit": commit,
        "required_targets": required,
        "controls": summaries,
        "claim_boundary": "source/discovery only; no target runtime or lifecycle qualification implied",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--controls",
        type=Path,
        default=Path(".foundry/official-catalog-controls.json"),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(".foundry/truenas-target-tracks.json"),
    )
    parser.add_argument("--catalog-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    try:
        manifest = load(args.controls, "controls")
        registry = load(args.registry, "target registry")
        result = validate(manifest, registry)
        if args.catalog_dir:
            validate_catalog_checkout(manifest, args.catalog_dir)
            result["catalog_source_verified"] = True
        else:
            result["catalog_source_verified"] = False
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0
    except ControlError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
