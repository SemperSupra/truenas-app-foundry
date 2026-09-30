#!/usr/bin/env python3
"""Export a public-safe GARM controller control bundle for nested TrueNAS T6."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_truenas_deployment_artifact import build_artifact
from validate_garm_controller_app import (
    CANDIDATE,
    ValidationError,
    assert_render,
    checkout_upstream,
    install_candidate,
    load_json,
    render_candidate,
)

APP_NAME = "rdte-t6-garm"
RUNTIME_CONFIG_ROOT = "/mnt/rdtepool/garm-t6/config"
TLS_CONFIGS = {"garm-tls-certificate", "garm-tls-private-key"}


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def lower_for_nested(compose: dict[str, Any]) -> dict[str, Any]:
    lowered = json.loads(json.dumps(compose))
    services = lowered.get("services")
    if not isinstance(services, dict) or set(services) != {"garm", "garm-config-seed"}:
        raise ValidationError("unexpected GARM service inventory")

    for name in ("garm", "garm-config-seed"):
        volumes = services[name].get("volumes") or []
        matches = [
            item for item in volumes
            if isinstance(item, dict) and item.get("target") == "/etc/garm"
        ]
        if len(matches) != 1:
            raise ValidationError(f"{name}: expected exactly one /etc/garm mount")
        matches[0]["type"] = "bind"
        matches[0]["source"] = RUNTIME_CONFIG_ROOT

    configs = lowered.get("configs") or {}
    if not TLS_CONFIGS.issubset(configs):
        raise ValidationError("rendered GARM TLS configs missing")
    for config_name in TLS_CONFIGS:
        configs[config_name]["content"] = f"__EPHEMERAL_NESTED_TLS__:{config_name}"

    rendered = json.dumps(lowered, sort_keys=True)
    if "docker.sock" in rendered or '"privileged": true' in rendered:
        raise ValidationError("unsafe runtime boundary materialized")
    return lowered


def export(foundry_ref: str, output: Path) -> dict[str, Any]:
    if len(foundry_ref) != 40 or any(c not in "0123456789abcdef" for c in foundry_ref):
        raise ValidationError("foundry_ref must be an exact lowercase commit SHA")

    manifest = load_json(CANDIDATE)
    root = Path(tempfile.mkdtemp(prefix="garm-t6-export-"))
    try:
        checkout = checkout_upstream(root, manifest)
        app_dir = install_candidate(checkout, manifest)
        source_compose = render_candidate(checkout, app_dir)
        appliance, _, _, _ = assert_render(source_compose, manifest)
        runtime_compose = lower_for_nested(source_compose)

        source_sha = canonical_sha256(source_compose)
        runtime_sha = canonical_sha256(runtime_compose)
        artifact = build_artifact(
            APP_NAME,
            runtime_compose,
            provenance={
                "foundry_ref": foundry_ref,
                "candidate": "garm-controller-app",
                "candidate_manifest_sha256": hashlib.sha256(
                    CANDIDATE.read_bytes()
                ).hexdigest(),
                "source_compose_sha256": source_sha,
                "target_lowering": {
                    "persistent_config_root": RUNTIME_CONFIG_ROOT,
                    "tls": "replace two public placeholder configs with run-local ephemeral PEM; never retain key material",
                },
                "source_materializer": manifest["source_materializer"],
                "appliance": manifest["appliance"],
            },
        )

        output.mkdir(parents=True, exist_ok=True)
        (output / "compose.json").write_text(
            json.dumps(runtime_compose, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (output / "deployment.json").write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        control = {
            "schema": "semper-supra.garm-truenas-t6-control/1",
            "foundry_ref": foundry_ref,
            "candidate": "garm-controller-app",
            "appliance_reference": appliance,
            "controller_source": manifest["appliance"]["controller_source"],
            "provider_source": manifest["appliance"]["truenas_provider_source"],
            "source_compose_sha256": source_sha,
            "runtime_compose_sha256": runtime_sha,
            "deployment_artifact_sha256": artifact["artifact_sha256"],
            "materialization_identity": artifact["materialization_identity"],
            "runtime": {
                "app_name": APP_NAME,
                "config_root": RUNTIME_CONFIG_ROOT,
                "host_port": 30880,
                "tls_replacement": sorted(TLS_CONFIGS),
            },
            "private_secrets_captured": False,
            "fixture_bootstrap_values_only": True,
            "github_credentials_present": False,
            "claims": [
                "public Foundry source rendered through the existing qualified GARM controller path",
                "runtime Compose binds only disposable nested config storage",
                "TLS private key is deliberately absent from the exported bundle",
            ],
            "non_claims": [
                "no GitHub credential/JIT runner registration",
                "no physical TrueNAS qualification",
                "no capacity promotion",
            ],
        }
        (output / "control.json").write_text(
            json.dumps(control, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return control
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--foundry-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        control = export(args.foundry_ref, args.output)
        print(json.dumps(control, indent=2, sort_keys=True))
        return 0
    except (ValidationError, OSError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
