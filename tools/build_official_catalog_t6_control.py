#!/usr/bin/env python3
"""Build a public-safe native official-catalog TrueNAS T6 control bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class BuildError(RuntimeError):
    pass


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"{path} must contain an object")
    return value


def build(manifest: dict[str, Any], foundry_ref: str, control_id: str) -> dict[str, Any]:
    if len(foundry_ref) != 40 or any(c not in "0123456789abcdef" for c in foundry_ref):
        raise BuildError("foundry_ref must be an exact 40-hex commit")
    controls = manifest.get("controls")
    if not isinstance(controls, list):
        raise BuildError("controls must be an array")
    control = next((x for x in controls if isinstance(x, dict) and x.get("id") == control_id), None)
    if not control:
        raise BuildError(f"unknown control: {control_id}")
    if control.get("role") not in {"universal-candidate-primary", "universal-candidate-secondary"}:
        raise BuildError("T6 native-catalog control must be a universal candidate")
    if control.get("native_catalog_semantics") is not True or control.get("custom_app_fallback") is not False:
        raise BuildError("native catalog semantics are not fail-closed")
    source = manifest.get("catalog_source")
    if not isinstance(source, dict):
        raise BuildError("catalog_source is missing")

    app_name = f"rdte-t6-catalog-{control_id}"
    create_payload = {
        "custom_app": False,
        "catalog_app": control_id,
        "app_name": app_name,
        "train": control["train"],
        "version": control["catalog_version"],
        "values": {"TZ": "Etc/UTC"},
    }
    update_payload = {"values": {"TZ": "Europe/Berlin"}}
    result = {
        "schema": "semper-supra.official-catalog-truenas-t6-control/1",
        "foundry_ref": foundry_ref,
        "catalog_source": {
            "repository": source["repository"],
            "commit": source["commit"],
        },
        "control": {
            "id": control_id,
            "role": control["role"],
            "train": control["train"],
            "catalog_version": control["catalog_version"],
            "app_version": control["app_version"],
            "lib_version": control["lib_version"],
            "source_path": control["source_path"],
            "source_blob_sha": control["source_blob_sha"],
        },
        "runtime": {
            "app_name": app_name,
            "create_payload": create_payload,
            "config_update_payload": update_payload,
            "config_oracle": {
                "initial": {"TZ": "Etc/UTC"},
                "updated": {"TZ": "Europe/Berlin"},
            },
            "delete_options": {
                "remove_ix_volumes": False,
                "remove_images": False,
            },
            "upgrade": {
                "method": "app.upgrade",
                "mode": "conditional-observed-capability",
                "execute_when": "custom_app=false and upgrade_available=true",
                "not_applicable_requires_receipt": True,
            },
        },
        "lifecycle": {
            "required": [
                "absent",
                "native-catalog-create",
                "running-health-verify",
                "stop",
                "start",
                "config-update",
                "config-readback",
                "redeploy",
                "replan-noop",
                "retain-data-delete",
                "absence-verify",
                "reinstall",
                "running-health-verify",
                "replan-noop",
            ],
            "conditional": ["native-upgrade-if-observed-available"],
            "ambiguous_operation_policy": "reobserve-before-retry",
        },
        "target_versions": control["target_versions"],
        "runtime_qualified_targets": control["runtime_qualified_targets"],
        "universal_qualified": control["universal_qualified"],
        "claim_boundary": "control input only; no target runtime qualification implied",
        "secrets_captured": False,
    }
    result["control_sha256"] = canonical_sha256(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path(".foundry/official-catalog-controls.json"))
    parser.add_argument("--foundry-ref", required=True)
    parser.add_argument("--control-id", default="ntfy")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(load(args.manifest), args.foundry_ref, args.control_id)
        args.output.mkdir(parents=True, exist_ok=True)
        path = args.output / "control.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "PASS",
            "control": result["control"]["id"],
            "control_sha256": result["control_sha256"],
            "output": str(path),
        }, sort_keys=True))
        return 0
    except (BuildError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
