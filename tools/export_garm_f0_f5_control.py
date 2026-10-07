#!/usr/bin/env python3
"""Export an exact-target public-safe GARM controller control for TrueNAS F0-F5 RDTE."""
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
BOOTSTRAP_CONFIG = "garm-initial-config"
TARGETS = ("25.04.1", "25.04.2.6", "25.10.7", "26.0.0-BETA.3")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def git_blob_sha1(path: Path) -> str:
    content = path.read_bytes()
    return hashlib.sha1(
        f"blob {len(content)}\0".encode("ascii") + content
    ).hexdigest()


def target_profile_path(target_version: str) -> Path:
    if target_version not in TARGETS:
        raise ValidationError(f"unsupported exact TrueNAS target {target_version!r}")
    return (
        Path(__file__).resolve().parents[1]
        / ".foundry"
        / "truenas-compatibility"
        / f"{target_version}-materialization.json"
    )


def load_target_profile(target_version: str) -> tuple[dict[str, Any], Path, str]:
    path = target_profile_path(target_version)
    profile = load_json(path)
    if profile.get("truenas_version") != target_version:
        raise ValidationError("materialization profile target version drifted")
    if profile.get("runtime_target") != "truenas-scale-apps":
        raise ValidationError("materialization profile runtime target drifted")
    middleware = profile.get("middleware") or {}
    commit = middleware.get("commit")
    if not isinstance(commit, str) or len(commit) != 40:
        raise ValidationError("materialization profile middleware commit is not exact")
    return profile, path, git_blob_sha1(path)


def lower_for_nested(compose: dict[str, Any]) -> dict[str, Any]:
    lowered = json.loads(json.dumps(compose))
    services = lowered.get("services")
    if not isinstance(services, dict) or set(services) != {"garm", "garm-config-seed"}:
        raise ValidationError("unexpected GARM service inventory")

    for name in ("garm", "garm-config-seed"):
        volumes = services[name].get("volumes") or []
        matches = [
            item
            for item in volumes
            if isinstance(item, dict) and item.get("target") == "/etc/garm"
        ]
        if len(matches) != 1:
            raise ValidationError(f"{name}: expected exactly one /etc/garm mount")
        matches[0]["type"] = "bind"
        matches[0]["source"] = RUNTIME_CONFIG_ROOT

    configs = lowered.get("configs") or {}
    if not TLS_CONFIGS.issubset(configs):
        raise ValidationError("rendered GARM TLS configs missing")
    if BOOTSTRAP_CONFIG not in configs:
        raise ValidationError("rendered GARM bootstrap config missing")

    for config_name in TLS_CONFIGS:
        configs[config_name]["content"] = f"__EPHEMERAL_NESTED_TLS__:{config_name}"
    configs[BOOTSTRAP_CONFIG]["content"] = "__EPHEMERAL_NESTED_GARM_CONFIG__"

    rendered = json.dumps(lowered, sort_keys=True)
    if "docker.sock" in rendered or '"privileged": true' in rendered:
        raise ValidationError("unsafe runtime boundary materialized")
    for forbidden in (
        "PUBLIC-QUALIFICATION-FIXTURE",
        "PRIVATE-QUALIFICATION-FIXTURE",
        "N4vR8xK2mQ7pL5sD9wF3cH6yT1jB0zUa",
        "Y7cD2mQ9vK4sR8pL1xF6nH3wT5jB0zUa",
    ):
        if forbidden in rendered:
            raise ValidationError(
                f"retained control contains fixture secret material: {forbidden}"
            )
    return lowered


def export(foundry_ref: str, target_version: str, output: Path) -> dict[str, Any]:
    if len(foundry_ref) != 40 or any(c not in "0123456789abcdef" for c in foundry_ref):
        raise ValidationError("foundry_ref must be an exact lowercase commit SHA")

    profile, profile_path, profile_blob = load_target_profile(target_version)
    manifest = load_json(CANDIDATE)
    root = Path(tempfile.mkdtemp(prefix="garm-f0-f5-export-"))
    try:
        checkout = checkout_upstream(root, manifest)
        app_dir = install_candidate(checkout, manifest)
        source_compose = render_candidate(checkout, app_dir)
        appliance, _, _, _ = assert_render(source_compose, manifest)
        runtime_compose = lower_for_nested(source_compose)

        source_sha = canonical_sha256(source_compose)
        runtime_sha = canonical_sha256(runtime_compose)
        target_lowering = {
            "persistent_config_root": RUNTIME_CONFIG_ROOT,
            "tls": "replace two placeholders with run-local ephemeral PEM; never retain key material",
            "bootstrap_config": "replace placeholder with run-local disposable JWT/database values",
        }
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
                "target_lowering": target_lowering,
                "source_materializer": manifest["source_materializer"],
                "appliance": manifest["appliance"],
                "target_profile": {
                    "version": target_version,
                    "profile_id": profile["profile_id"],
                    "middleware_commit": profile["middleware"]["commit"],
                    "path": str(profile_path.relative_to(Path(__file__).resolve().parents[1])),
                    "git_blob_sha": profile_blob,
                },
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
            "schema": "semper-supra.garm-truenas-f0-f5-control/1",
            "foundry_ref": foundry_ref,
            "candidate": "garm-controller-app",
            "target": {
                "truenas_version": target_version,
                "expected_system_version": f"TrueNAS-{target_version}",
                "profile_id": profile["profile_id"],
                "profile_path": str(
                    profile_path.relative_to(Path(__file__).resolve().parents[1])
                ),
                "profile_git_blob_sha": profile_blob,
                "middleware_commit": profile["middleware"]["commit"],
            },
            "appliance_reference": appliance,
            "controller_source": manifest["appliance"]["controller_source"],
            "provider_source": manifest["appliance"]["truenas_provider_source"],
            "source_compose_sha256": source_sha,
            "runtime_compose_sha256": runtime_sha,
            "deployment_artifact_sha256": artifact["artifact_sha256"],
            "materialization_identity": artifact["materialization_identity"],
            "target_lowering": target_lowering,
            "runtime": {
                "app_name": APP_NAME,
                "config_root": RUNTIME_CONFIG_ROOT,
                "host_port": 30880,
                "tls_replacement": sorted(TLS_CONFIGS),
                "bootstrap_replacement": BOOTSTRAP_CONFIG,
            },
            "f0_f5_contract": {
                "f0": "exact target/profile/source/capability fingerprint",
                "f1": "exact materialization identity",
                "f2": "create plus independent config/runtime readback",
                "f3": "stop/start/update/redeploy plus product health and persistent config/db",
                "f4": "second-plan NOOP; in-flight WAIT; ambiguous FAIL_CLOSED",
                "f5": "retain external config dataset across App delete; reinstall; post-reinstall NOOP; explicit final fixture cleanup",
            },
            "private_secrets_captured": False,
            "fixture_secret_values_retained": False,
            "github_credentials_present": False,
            "claims": [
                "public Foundry source rendered through the existing qualified GARM controller path",
                "runtime Compose binds only disposable nested config storage",
                "all retained secret-bearing configs are placeholders",
                "control is bound to one exact TrueNAS materialization profile",
            ],
            "non_claims": [
                "export alone does not satisfy F0-F5 runtime qualification",
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
    parser.add_argument("--target-version", choices=TARGETS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        control = export(args.foundry_ref, args.target_version, args.output)
        print(json.dumps(control, indent=2, sort_keys=True))
        return 0
    except (ValidationError, OSError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
