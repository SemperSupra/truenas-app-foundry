#!/usr/bin/env python3
"""Source-bound, public-safe native Minecraft Paper T6 control exporter.

Provides a *candidate*, not a claim of Minecraft runtime or catalog availability.
TrueNAS runtime independently resolves the installed catalog version, image digest,
site-local dataset and port. Do not reuse a source-render PASS as T6 acceptance.
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
PIN = ROOT / ".foundry/controls/minecraft-paper-upstream.json"
PROFILE = ROOT / ".foundry/truenas-compatibility/25.04.1-materialization.json"
VALUES = ROOT / ".foundry/controls/minecraft-paper-world-hostpath-values.yaml"
TARGET = "25.04.1"
CATALOG_VERSION = "1.15.29"
PAPER_VERSION = "1.21.11"
SCHEMA = "semper-supra.minecraft-paper-truenas-t6-control/1"
OWNERSHIP = {
    "SUPRACRAFT_COLLAGE_MANAGED": "true",
    "SUPRACRAFT_COLLAGE_SCHEMA": "1",
    "SUPRACRAFT_COLLAGE_MANAGER_ID": "manager-rdte",
    "SUPRACRAFT_COLLAGE_FLEET_ID": "rdte",
    "SUPRACRAFT_COLLAGE_SERVICE_ID": "11111111-1111-4111-8111-111111111111",
    "SUPRACRAFT_COLLAGE_WORLD_ID": "world-rdte-001",
}


class ControlError(RuntimeError):
    pass


def digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_json(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ControlError("expected JSON object")
    return value


def source_control(foundry_ref: str, evidence: dict) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", foundry_ref):
        raise ControlError("Foundry ref must be full immutable commit SHA")
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    if head != foundry_ref:
        raise ControlError("Foundry checkout is not exact requested commit")
    pin = load_json(PIN)
    profile = load_json(PROFILE)
    values = yaml.safe_load(VALUES.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ControlError("Minecraft values not an object")
    if (profile.get("truenas_version") != TARGET
        or profile.get("middleware", {}).get("commit") !=
        "74ab5a2d373be4097dece257d00e1086376333ba"):
        raise ControlError("exact target profile drift")
    profile_blob = subprocess.check_output(
        ["git", "-C", str(ROOT), "hash-object", str(PROFILE)], text=True
    ).strip()
    if profile_blob != "800aca038ded29e6a91bfc4c1b1fe2d2199182e8":
        raise ControlError("target profile Git blob drift")
    if pin.get("ref") != "bb96ef6fd8c2708765012a4a3ca3739370a4f92c":
        raise ControlError("upstream TrueNAS Apps source drift")
    if pin.get("library_version") != "2.3.4":
        raise ControlError("upstream library version drift")
    if evidence.get("result") != "PASS":
        raise ControlError("source render did not pass")
    upstream = evidence.get("upstream") or {}
    if upstream.get("ref") != pin["ref"] or upstream.get("app") != "community/minecraft":
        raise ControlError("source render upstream identity drift")
    server = evidence.get("server") or {}
    if (pin.get("catalog_version") != CATALOG_VERSION or
        pin.get("image") != "ghcr.io/itzg/minecraft-server:2026.9.2-java21@sha256:edf50d431ddc6f73929368e82f4334a405796874f7b0ae11f1edcbb267d670aa" or
        server.get("catalog_version") != CATALOG_VERSION or
        server.get("image_ref") != pin["image"]):
        raise ControlError("source-render catalog revision or digest-pinned image drift")
    compose_hash = evidence.get("compose_sha256")
    if not isinstance(compose_hash, str) or not re.fullmatch("[0-9a-f]{64}", compose_hash):
        raise ControlError("missing exact source-render Compose digest")
    minecraft = values.get("minecraft") or {}
    if minecraft.get("type") != "PAPER" or minecraft.get("version") != PAPER_VERSION:
        raise ControlError("Paper source version drift")
    if minecraft.get("eula") is not True or minecraft.get("online_mode") is not True:
        raise ControlError("EULA/online-mode contract drift")
    storage = values.get("storage") or {}
    if (storage.get("data") or {}).get("type") != "ix_volume":
        raise ControlError("base /data must be App-owned")
    world_mounts = [
        v for v in storage.get("additional_storage", [])
        if isinstance(v, dict) and v.get("mount_path") == "/data/world"
    ]
    if len(world_mounts) != 1 or world_mounts[0].get("type") != "host_path":
        raise ControlError("exactly one host-path world mount required")
    if world_mounts[0].get("read_only") is not False:
        raise ControlError("world must be writable")
    world_path = (world_mounts[0].get("host_path_config") or {}).get("path")
    if world_path != "/opt/tests/collage-world-only":
        raise ControlError("source world path drift")
    additions = minecraft.get("additional_envs")
    if not isinstance(additions, list):
        raise ControlError("missing ownership metadata")
    observed = {x.get("name"): x.get("value") for x in additions if isinstance(x, dict)}
    if observed != OWNERSHIP:
        raise ControlError("provider-neutral ownership metadata drift")
    network = values.get("network") or {}
    if network.get("host_network") is not False:
        raise ControlError("host networking not admitted")
    port = (network.get("server_port") or {}).get("port_number")
    if port != 25565 or (network.get("server_port") or {}).get("bind_mode") != "published":
        raise ControlError("published source port drift")
    if minecraft.get("enable_rcon") is not False or minecraft.get("rcon_password") != "":
        raise ControlError("RCON must remain disabled and secret-free")
    if (values.get("resources") or {}).get("limits", {}).get("memory") != 4096:
        raise ControlError("memory budget drift")

    control = {
        "schema": SCHEMA,
        "foundry_ref": foundry_ref,
        "target": {
            "truenas_version": TARGET,
            "expected_system_version": "TrueNAS-" + TARGET,
            "profile_git_blob_sha": profile_blob,
            "middleware_commit": profile["middleware"]["commit"],
        },
        "source": {
            "repository": pin["repository"],
            "apps_commit": pin["ref"],
            "app": "community/minecraft",
            "image_reference": pin["image"],
            "library_version": pin["library_version"],
            "source_compose_sha256": compose_hash,
            "values_raw_sha256": hashlib.sha256(VALUES.read_bytes()).hexdigest(),
        },
        "runtime": {
            "app_name": "rdte-t6-minecraft-paper",
            "catalog_app": "minecraft",
            "train": "community",
            "catalog_version_candidate": CATALOG_VERSION,
            "paper_version": PAPER_VERSION,
            "values_template": values,
            "site_bindings_required": {
                "world_host_path": "storage.additional_storage[0].host_path_config.path",
                "server_port": "network.server_port.port_number",
            },
            "required_owned_world_dataset": "rdtepool/minecraft-paper-t6-world",
            "status_oracle": "minecraft-java-status-oracle/v1",
        },
        "evidence": {
            "source_render_pass": True,
            "live_catalog_version_verified": False,
            "live_minecraft_server_qualified": False,
            "world_retention_qualified": False,
            "physical_truenas_qualified": False,
        },
        "secrets_captured": False,
    }
    control["control_sha256"] = digest(control)
    return control


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--foundry-ref", required=True)
    p.add_argument("--target-version", default=TARGET)
    p.add_argument("--source-evidence", type=pathlib.Path, required=True)
    p.add_argument("--output", type=pathlib.Path, required=True)
    args = p.parse_args()
    try:
        if args.target_version != TARGET:
            raise ControlError("first Minecraft control is 25.04.1 only")
        evidence = load_json(args.source_evidence)
        control = source_control(args.foundry_ref, evidence)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "control.json").write_text(
            json.dumps(control, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({
            "result": "SOURCE_CANDIDATE",
            "control_sha256": control["control_sha256"],
            "target": TARGET,
            "foundry_ref": args.foundry_ref,
            "oracleSatisfied": False,
        }, sort_keys=True))
        return 0
    except (ControlError, OSError, ValueError, json.JSONDecodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
