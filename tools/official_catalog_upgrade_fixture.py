#!/usr/bin/env python3
"""Validate an exact-source native TrueNAS catalog upgrade fixture."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


class FixtureError(RuntimeError):
    pass


HEX40 = re.compile(r"^[0-9a-f]{40}$")


def load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise FixtureError(f"{label} must be an object")
    return value


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        parts = tuple(int(x) for x in value.split("."))
    except ValueError as exc:
        raise FixtureError(f"catalog version must be numeric dotted form: {value!r}") from exc
    if not parts:
        raise FixtureError("catalog version must not be empty")
    return parts


def target_versions(registry: dict[str, Any]) -> list[str]:
    targets = registry.get("targets")
    if not isinstance(targets, list) or not targets:
        raise FixtureError("target registry has no targets")
    versions = [str(x.get("version", "")) for x in targets if isinstance(x, dict)]
    if any(not x for x in versions) or len(versions) != len(set(versions)):
        raise FixtureError("target registry versions must be non-empty and unique")
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
        raise FixtureError(f"git {' '.join(args)} failed: {exc}") from exc
    return proc.stdout.strip()


def validate_generated_entry(side: dict[str, Any], checkout: Path, app: dict[str, Any]) -> None:
    if git("rev-parse", "HEAD", cwd=checkout) != side["commit"]:
        raise FixtureError(f"{side['catalog_version']}: checkout commit mismatch")
    observed_blob = git("rev-parse", f"HEAD:{side['generated_path']}", cwd=checkout)
    if observed_blob != side["generated_blob_sha"]:
        raise FixtureError(
            f"{side['catalog_version']}: generated catalog blob mismatch: "
            f"expected {side['generated_blob_sha']}, observed {observed_blob}"
        )
    generated = load(checkout / side["generated_path"], "generated app_versions")
    if list(generated) != [side["catalog_version"]]:
        raise FixtureError(
            f"{side['catalog_version']}: generated app_versions keys must be exact singleton"
        )
    row = generated[side["catalog_version"]]
    if not isinstance(row, dict):
        raise FixtureError(f"{side['catalog_version']}: generated version row must be an object")
    metadata = row.get("app_metadata")
    if not isinstance(metadata, dict):
        raise FixtureError(f"{side['catalog_version']}: generated app metadata missing")
    expected = {
        "version": side["catalog_version"],
        "human_version": side["human_version"],
        "app_version": side["app_version"],
        "lib_version": side["lib_version"],
        "lib_version_hash": side["lib_version_hash"],
        "name": app["id"],
        "train": app["train"],
    }
    observed = {
        "version": row.get("version"),
        "human_version": row.get("human_version"),
        "app_version": metadata.get("app_version"),
        "lib_version": metadata.get("lib_version"),
        "lib_version_hash": metadata.get("lib_version_hash"),
        "name": metadata.get("name"),
        "train": metadata.get("train"),
    }
    if observed != expected:
        raise FixtureError(
            f"{side['catalog_version']}: generated identity mismatch: "
            f"expected={expected!r}, observed={observed!r}"
        )
    if row.get("healthy") is not True or row.get("supported") is not True:
        raise FixtureError(f"{side['catalog_version']}: generated version is not healthy+supported")


def validate(manifest: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != "truenas-foundry-official-catalog-upgrade-fixture/v1":
        raise FixtureError("unsupported fixture schema")
    app = manifest.get("app")
    if not isinstance(app, dict) or not app.get("id") or not app.get("train"):
        raise FixtureError("app identity is incomplete")
    before = manifest.get("from")
    after = manifest.get("to")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise FixtureError("from/to fixture sides must be objects")

    required = target_versions(registry)
    declared = manifest.get("target_versions")
    if not isinstance(declared, list) or set(declared) != set(required):
        raise FixtureError("fixture target_versions must exactly match target registry")
    qualified = manifest.get("runtime_qualified_targets")
    if not isinstance(qualified, list) or not set(qualified).issubset(set(declared)):
        raise FixtureError("runtime_qualified_targets must be a subset of target_versions")

    for side in (before, after):
        for field in (
            "repository",
            "commit",
            "generated_path",
            "generated_blob_sha",
            "catalog_version",
            "human_version",
            "app_version",
            "lib_version",
            "lib_version_hash",
        ):
            if not isinstance(side.get(field), str) or not side[field]:
                raise FixtureError(f"{field} must be a non-empty string")
        if not HEX40.fullmatch(side["commit"]) or not HEX40.fullmatch(side["generated_blob_sha"]):
            raise FixtureError("commit/blob identities must be exact 40-hex values")

    if before["repository"] != after["repository"]:
        raise FixtureError("from/to repository lineage differs")
    for field in ("app_version", "lib_version", "lib_version_hash"):
        if before[field] != after[field]:
            raise FixtureError(f"from/to {field} differs; fixture is not same-lineage package upgrade")
    if version_tuple(before["catalog_version"]) >= version_tuple(after["catalog_version"]):
        raise FixtureError("catalog version must strictly increase")

    policy = manifest.get("policy")
    if not isinstance(policy, dict):
        raise FixtureError("policy must be an object")
    required_true = (
        "native_catalog_semantics_required",
        "from_and_to_must_share_app_lineage",
        "generated_catalog_source_required",
        "runtime_claim_requires_observed_upgrade_available",
        "runtime_claim_requires_app_upgrade_execution",
        "runtime_claim_requires_post_upgrade_identity",
    )
    if any(policy.get(k) is not True for k in required_true):
        raise FixtureError("upgrade fixture safety policy is incomplete")
    if policy.get("custom_app_fallback_allowed") is not False:
        raise FixtureError("Custom App fallback must remain prohibited")

    fully = set(qualified) == set(required)
    if bool(manifest.get("executed_upgrade_qualified")) != fully:
        raise FixtureError(
            "executed_upgrade_qualified must exactly reflect all-target runtime qualification"
        )

    return {
        "schema": "truenas-foundry-official-catalog-upgrade-fixture-validation/v1",
        "status": "PASS",
        "app": app,
        "from_catalog_version": before["catalog_version"],
        "to_catalog_version": after["catalog_version"],
        "target_versions": required,
        "runtime_qualified_targets": qualified,
        "executed_upgrade_qualified": fully,
        "claim_boundary": "source fixture only; runtime app.upgrade execution remains unqualified",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--fixture",
        type=Path,
        default=Path(".foundry/official-catalog-upgrade-fixture.json"),
    )
    p.add_argument(
        "--registry",
        type=Path,
        default=Path(".foundry/truenas-target-tracks.json"),
    )
    p.add_argument("--from-dir", type=Path)
    p.add_argument("--to-dir", type=Path)
    p.add_argument("--out", type=Path)
    a = p.parse_args()

    try:
        fixture = load(a.fixture, "fixture")
        registry = load(a.registry, "target registry")
        result = validate(fixture, registry)
        if (a.from_dir is None) != (a.to_dir is None):
            raise FixtureError("--from-dir and --to-dir must be supplied together")
        if a.from_dir and a.to_dir:
            validate_generated_entry(fixture["from"], a.from_dir, fixture["app"])
            validate_generated_entry(fixture["to"], a.to_dir, fixture["app"])
            result["generated_sources_verified"] = True
        else:
            result["generated_sources_verified"] = False
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if a.out:
            a.out.write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0
    except FixtureError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
