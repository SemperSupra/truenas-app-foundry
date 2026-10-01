#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "truenas-foundry-catalog-toolchain/v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

class ToolchainError(RuntimeError):
    pass

def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolchainError(f"cannot read toolchain contract: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolchainError("toolchain contract must be an object")
    return data

def require_repo(node: Any, field: str) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise ToolchainError(f"{field} must be an object")
    repo = node.get("repository")
    ref = node.get("ref")
    if not isinstance(repo, str) or not repo.startswith("https://github.com/") or not repo.endswith(".git"):
        raise ToolchainError(f"{field}.repository must be an https GitHub .git URL")
    if not isinstance(ref, str) or not SHA_RE.fullmatch(ref):
        raise ToolchainError(f"{field}.ref must be an exact 40-hex commit")
    return node

def validate(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema") != SCHEMA:
        raise ToolchainError("unsupported toolchain schema")
    apps = require_repo(data.get("apps"), "apps")
    av = require_repo(data.get("apps_validation"), "apps_validation")
    if apps.get("validator_command") != "/usr/local/bin/apps_dev_charts_validate validate --path /work":
        raise ToolchainError("apps.validator_command drifted from the admitted upstream command")
    if av.get("validator_cli") != "/usr/local/bin/apps_dev_charts_validate":
        raise ToolchainError("apps_validation.validator_cli is unexpected")
    if av.get("declared_base") != "ghcr.io/truenas/middleware:master":
        raise ToolchainError("apps_validation.declared_base no longer matches the audited Dockerfile contract")
    admitted = av.get("admitted_base_digest")
    if not isinstance(admitted, str) or not re.fullmatch(
        r"ghcr\.io/truenas/middleware@sha256:[0-9a-f]{64}", admitted
    ):
        raise ToolchainError("apps_validation.admitted_base_digest must be an exact middleware digest")
    policy = data.get("policy")
    if not isinstance(policy, dict):
        raise ToolchainError("policy must be an object")
    for key in (
        "exact_git_refs_required",
        "admitted_base_digest_required",
        "floating_validator_image_forbidden",
        "catalog_ready_requires_native_validator_and_render_install",
    ):
        if policy.get(key) is not True:
            raise ToolchainError(f"policy.{key} must be true")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "apps_ref": apps["ref"],
        "apps_validation_ref": av["ref"],
        "declared_base": av["declared_base"],
        "admitted_base_digest": av["admitted_base_digest"],
    }

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--contract", type=Path, required=True)
    args = p.parse_args()
    try:
        print(json.dumps(validate(load(args.contract)), indent=2, sort_keys=True))
        return 0
    except ToolchainError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
