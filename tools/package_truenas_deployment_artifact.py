#!/usr/bin/env python3
"""Package normalized Compose IR as an identity-bound TrueNAS deployment artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


APP_NAME_RE = re.compile(r"^[a-z]([-a-z0-9]*[a-z0-9])?$")


class ArtifactError(RuntimeError):
    pass


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"cannot read JSON {path}: {exc}") from exc


def build_artifact(app_name: str, compose: dict[str, Any], provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    if not APP_NAME_RE.fullmatch(app_name) or len(app_name) > 40:
        raise ArtifactError("app name does not satisfy the TrueNAS App naming contract")
    if not isinstance(compose, dict) or not isinstance(compose.get("services"), dict) or not compose["services"]:
        raise ArtifactError("normalized Compose must contain a non-empty services object")

    compose_sha = canonical_sha256(compose)
    artifact = {
        "schema": "truenas-foundry-deployment-artifact/v1",
        "runtime_target": "truenas-scale-apps",
        "app_name": app_name,
        "compose_sha256": compose_sha,
        "materialization_identity": f"sha256:{compose_sha}",
        "required_methods": [
            "app.query",
            "app.config",
            "app.create",
            "app.update",
        ],
        "create_payload": {
            "custom_app": True,
            "app_name": app_name,
            "custom_compose_config": compose,
        },
        "update_payload": {
            "custom_compose_config": compose,
        },
    }
    if provenance:
        artifact["provenance"] = provenance
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--compose", type=Path, required=True)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    try:
        compose = load_json(args.compose)
        if not isinstance(compose, dict):
            raise ArtifactError("compose document must be an object")
        provenance = None
        if args.provenance:
            provenance = load_json(args.provenance)
            if not isinstance(provenance, dict):
                raise ArtifactError("provenance document must be an object")
        artifact = build_artifact(args.app_name, compose, provenance)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(args.out, 0o600)
        print(json.dumps({
            "status": "PASS",
            "schema": artifact["schema"],
            "app_name": artifact["app_name"],
            "materialization_identity": artifact["materialization_identity"],
            "artifact_sha256": artifact["artifact_sha256"],
            "output_mode": "0600",
        }, sort_keys=True))
        return 0
    except (ArtifactError, OSError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
