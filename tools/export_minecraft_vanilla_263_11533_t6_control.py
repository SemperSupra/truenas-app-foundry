#!/usr/bin/env python3
"""Export NEW 1.15.33 immutable-source TrueNAS 25.04.2.6 vanilla26.3/Java25 T6 candidate.

Consumes a *real* independently rendered upstream source receipt. The exported
control is canonical digest-bound and useful to the existing Agent Dispatch
guest consumer, but has NO guest-runtime or physical qualification itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIN = ROOT / ".foundry/controls/minecraft-vanilla-263-11533-upstream.json"
VALUES = ROOT / ".foundry/controls/minecraft-vanilla-263-world-hostpath-values.yaml"
PROFILE = ROOT / ".foundry/truenas-compatibility/25.04.2.6-materialization.json"
SOURCE = "0f586ab56437cd5e29bf1b16d603ec1c48bbbd4e"
IMAGE = ("ghcr.io/itzg/minecraft-server:2026.10.0-java25@sha256:"
         "5a2ab74ae179c11e2dbbce67f307cdcf2c1257b3abb0f654d3a310b3d8ea57da")
BLOB = "631467044411c96a0fe6d361688b99a794f07c80"
MIDDLEWARE = "244b717370fe35fb9eefc3096acfbc25f12b57b6"
SCHEMA = "semper-supra.minecraft-vanilla-263-truenas-t6-control/1"
IDENTITY = {
    "SUPRACRAFT_COLLAGE_MANAGED": "true",
    "SUPRACRAFT_COLLAGE_SCHEMA": "1",
    "SUPRACRAFT_COLLAGE_MANAGER_ID": "manager-rdte",
    "SUPRACRAFT_COLLAGE_FLEET_ID": "rdte",
    "SUPRACRAFT_COLLAGE_SERVICE_ID": "11111111-1111-4111-8111-111111111111",
    "SUPRACRAFT_COLLAGE_WORLD_ID": "lantern-rdte",
}


class ExportRefused(RuntimeError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ExportRefused(code)


def canonical_sha256(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()


def produce(ref: str, evidence: dict, pin: dict, values: dict,
            profile: dict, blob: str) -> dict:
    require(isinstance(ref, str) and re.fullmatch("[0-9a-f]{40}", ref),
            "FOUNDRY_SOURCE_REF_NOT_IMMUTABLE")
    require(type(evidence) is dict and evidence.get("result") == "PASS" and
            evidence.get("truenas_target") == "25.04.2.6" and
            evidence.get("runtime_qualification") is False,
            "SOURCE_RENDER_NOT_ACCEPTED")
    require(type(pin) is dict and
            pin.get("ref") == SOURCE and pin.get("catalog_version") == "1.15.33" and
            pin.get("image") == IMAGE and pin.get("library_version") == "2.3.17",
            "PINNED_NATIVE_APP_SOURCE_DRIFT")
    upstream = evidence.get("upstream") or {}
    server = evidence.get("server") or {}
    require(upstream.get("ref") == SOURCE and
            upstream.get("app") == "community/minecraft" and
            server.get("catalog_version") == "1.15.33" and
            server.get("type") == "VANILLA" and
            server.get("minecraft_version") == "26.3" and
            server.get("image_selector") == "j25_image" and
            server.get("image_ref") == IMAGE,
            "REAL_SOURCE_RENDER_BACKEND_IMAGE_DRIFT")
    compose_sha = evidence.get("compose_sha256")
    require(isinstance(compose_sha, str) and
            re.fullmatch("[0-9a-f]{64}", compose_sha),
            "SOURCE_COMPOSE_SHA256_MISSING")
    require(profile.get("truenas_version") == "25.04.2.6" and
            profile.get("middleware", {}).get("commit") == MIDDLEWARE and
            blob == BLOB, "TRUENAS_EXACT_TARGET_PROFILE_DRIFT")
    require(type(values) is dict, "NATIVE_VALUES_UNEXPECTED")
    mc = values.get("minecraft") or {}
    require(mc.get("image_selector") == "j25_image" and
            mc.get("type") == "VANILLA" and mc.get("version") == "26.3" and
            mc.get("eula") is True and mc.get("online_mode") is True and
            mc.get("enable_rcon") is False and mc.get("rcon_password") == "",
            "NATIVE_RUNTIME_INPUT_DRIFT")
    envs = mc.get("additional_envs")
    require(type(envs) is list and
            all(type(x) is dict and set(x) == {"name", "value"} for x in envs) and
            {x["name"]: x["value"] for x in envs} == IDENTITY and
            len(envs) == len(IDENTITY) and
            server.get("ownership_metadata") == IDENTITY,
            "OWNER_METADATA_DRIFT")
    storage = values.get("storage") or {}
    world = [x for x in storage.get("additional_storage", [])
             if type(x) is dict and x.get("mount_path") == "/data/world"]
    require(storage.get("data", {}).get("type") == "ix_volume" and
            len(world) == 1 and world[0].get("type") == "host_path" and
            world[0].get("read_only") is False and
            world[0].get("host_path_config", {}).get("path") ==
            "/opt/tests/collage-vanilla-263-world" and
            server.get("world_mount", {}).get("source") ==
            "/opt/tests/collage-vanilla-263-world",
            "EXTERNAL_WORLD_BOUNDARY_DRIFT")
    net = values.get("network") or {}
    require(net.get("host_network") is False and
            net.get("server_port", {}).get("port_number") == 25565 and
            net.get("server_port", {}).get("bind_mode") == "published",
            "NETWORK_SOURCE_POLICY_DRIFT")
    output = {
        "schema": SCHEMA,
        "foundry_ref": ref,
        "target": {
            "truenas_version": "25.04.2.6",
            "expected_system_version": "TrueNAS-25.04.2.6",
            "middleware_commit": MIDDLEWARE,
            "profile_git_blob_sha": blob,
        },
        "source": {
            "repository": pin["repository"],
            "apps_commit": SOURCE,
            "catalog_app": "community/minecraft",
            "catalog_version": "1.15.33",
            "library_version": pin["library_version"],
            "image_reference": IMAGE,
            "source_compose_sha256": compose_sha,
            "values_raw_sha256": hashlib.sha256(VALUES.read_bytes()).hexdigest(),
        },
        "runtime": {
            "app_name": "rdte-t6-minecraft-vanilla-263",
            "catalog_app": "minecraft",
            "train": "community",
            "catalog_version_candidate": "1.15.33",
            "minecraft_version": "26.3",
            "minecraft_protocol": 777,
            "java_version": 25,
            "image_selector": "j25_image",
            "values_template": values,
            "required_independent_world_dataset": "rdtepool/minecraft-vanilla-263-t6-world",
            "status_oracle": "minecraft-java-status-oracle/v1",
            "site_bindings_required": {
                "world_host_path": "storage.additional_storage[0].host_path_config.path",
                "server_port": "network.server_port.port_number",
            },
        },
        "evidence": {
            "source_render_pass": True,
            "live_catalog_version_verified": False,
            "native_guest_created": False,
            "gameplay_qualified_by_native_guest": False,
            "external_world_retention_qualified_by_native_guest": False,
            "collage_managed_deployment_qualified": False,
            "physical_truenas_qualified": False,
        },
        "operational_selection": False,
        "physical_truenas_apply": "HOLD",
    }
    output["control_sha256"] = canonical_sha256(output)
    return output


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--foundry-ref", required=True)
    a.add_argument("--target-version", required=True)
    a.add_argument("--source-evidence", required=True, type=pathlib.Path)
    a.add_argument("--out", required=True, type=pathlib.Path)
    args = a.parse_args()
    try:
        require(args.target_version == "25.04.2.6", "TARGET_VERSION_NOT_ACCEPTED")
        actual = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        require(actual == args.foundry_ref, "FOUNDRY_CHECKOUT_SHA_MISMATCH")
        blob = subprocess.check_output(
            ["git", "-C", str(ROOT), "hash-object", str(PROFILE)],
            text=True).strip()
        result = produce(args.foundry_ref,
                         json.loads(args.source_evidence.read_text()),
                         json.loads(PIN.read_text()),
                         yaml.safe_load(VALUES.read_text()),
                         json.loads(PROFILE.read_text()), blob)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
        print(json.dumps({"classification":"SOURCE_CANDIDATE",
                          "control_sha256":result["control_sha256"],
                          "guest_qualified":False},sort_keys=True))
        return 0
    except (ExportRefused, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("REFUSED:"+str(exc)[:180], file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
