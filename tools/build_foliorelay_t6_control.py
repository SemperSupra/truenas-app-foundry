#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
from pathlib import Path

SCHEMA = "semper-supra.foliorelay-truenas-t6-control/1"
PUBLICATION_SCHEMA = "semper-supra.foliorelay-rdte-publication/1"
APP_NAME = "rdte-t6-foliorelay"

CONTROL_ROOT = "/mnt/rdtepool/foliorelay-t6/control"
ARTIFACT_ROOT = "/mnt/rdtepool/foliorelay-t6/artifacts"
CUPS_STATE_ROOT = "/mnt/rdtepool/foliorelay-t6/cups-state"
CUPS_SPOOL_ROOT = "/mnt/rdtepool/foliorelay-t6/cups-spool"
TOKEN_PATH = "/mnt/rdtepool/foliorelay-t6/secrets/control.token"

CONTROL_TARGET = "/var/lib/foliorelay"
ARTIFACT_TARGET = "/var/lib/foliorelay/artifacts"
CUPS_CONTROL_TARGET = "/var/lib/foliorelay-control"
CUPS_ARTIFACT_TARGET = "/var/lib/foliorelay-artifacts"
TOKEN_TARGET = "/run/secrets/foliorelay.token"

REQUIRED_CUPS_TMPFS = {"/etc/cups", "/var/cache/cups", "/var/log/cups"}

DBUS_SOCKET = "/run/dbus/system_bus_socket"
AVAHI_TARGETS = {"25.04.1", "25.04.2.6", "25.10.7"}
DIRECT_TARGETS = {"26.0.0-BETA.3"}
DISCOVERY_IDENTITY_FILE = "/var/lib/foliorelay-control/config/printer.json"
AVAHI_DISCOVERY_COMMAND = [
    "-identity-file", DISCOVERY_IDENTITY_FILE,
    "-backend", "avahi",
    "-dbus-address", "unix:path=/run/dbus/system_bus_socket",
]


class ControlError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ControlError(f"{path} must contain an object")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def exact_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ControlError(f"{label} must be an exact sha256 digest")
    return value


def _services(compose: dict) -> dict:
    services = compose.get("services")
    if not isinstance(services, dict):
        raise ControlError("rendered compose services must be an object")
    required = {"control", "cups", "discovery"}
    missing = required - set(services)
    if missing:
        raise ControlError(f"missing required services: {sorted(missing)}")
    for name in required:
        if not isinstance(services[name], dict):
            raise ControlError(f"service {name} must be an object")
    return services


def _mount(service: dict, target: str) -> dict:
    matches = [
        v for v in (service.get("volumes") or [])
        if isinstance(v, dict) and v.get("target") == target
    ]
    if len(matches) != 1:
        raise ControlError(f"expected exactly one mount for {target}")
    return matches[0]


def _require_mount(service: dict, target: str, source: str, read_only: bool) -> None:
    mount = _mount(service, target)
    if mount.get("source") != source:
        raise ControlError(f"{target} source path drifted")
    if bool(mount.get("read_only", False)) is not read_only:
        raise ControlError(f"{target} read_only drifted")


def _port(service: dict, target: int, published: int) -> bool:
    for p in service.get("ports") or []:
        if not isinstance(p, dict):
            continue
        try:
            if int(p.get("target", -1)) == target and int(str(p.get("published"))) == published:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _tmpfs_targets(service: dict) -> set[str]:
    found: set[str] = set()
    for item in service.get("tmpfs") or []:
        if isinstance(item, str):
            found.add(item.split(":", 1)[0])
        elif isinstance(item, dict):
            target = item.get("target")
            if isinstance(target, str):
                found.add(target)
    for item in service.get("volumes") or []:
        if isinstance(item, dict) and item.get("type") == "tmpfs" and isinstance(item.get("target"), str):
            found.add(item["target"])
    return found


def _hardened(service: dict, name: str) -> None:
    if service.get("privileged") is True:
        raise ControlError(f"{name} must not be privileged")
    if service.get("read_only") is not True:
        raise ControlError(f"{name} root filesystem must be read-only")
    caps = service.get("cap_drop") or []
    if "ALL" not in caps:
        raise ControlError(f"{name} must drop all capabilities")


def _publication(receipt: dict) -> tuple[str, str]:
    if receipt.get("schema") != PUBLICATION_SCHEMA or receipt.get("status") != "PASS":
        raise ControlError("publication receipt is not an admitted FolioRelay RDTE publication")
    control = receipt.get("control") or {}
    cups = receipt.get("cups") or {}
    for label, component in (("control", control), ("cups", cups)):
        if component.get("anonymous_pull") is not True:
            raise ControlError(f"{label} image was not anonymously pull-qualified")
        if component.get("signed_keyless") is not True:
            raise ControlError(f"{label} image was not keyless-sign-qualified")
    control_digest = exact_digest(control.get("digest"), "control digest")
    cups_digest = exact_digest(cups.get("digest"), "cups digest")
    return (
        f"ghcr.io/sempersupra/foliorelay-control@{control_digest}",
        f"ghcr.io/sempersupra/foliorelay-cups@{cups_digest}",
    )


def materialize_target_compose(compose: dict, target: dict) -> dict:
    version = target.get("truenas_version")
    if version not in AVAHI_TARGETS | DIRECT_TARGETS:
        raise ControlError(f"unsupported FolioRelay target version: {version!r}")

    rendered = copy.deepcopy(compose)
    discovery = _services(rendered)["discovery"]
    volumes = list(discovery.get("volumes") or [])

    if version in AVAHI_TARGETS:
        if any(isinstance(v, dict) and v.get("target") == DBUS_SOCKET for v in volumes):
            raise ControlError("source Compose must not predeclare the Avahi system-bus mount")
        volumes.append({
            "type": "bind",
            "source": DBUS_SOCKET,
            "target": DBUS_SOCKET,
            "read_only": True,
        })
        discovery["volumes"] = volumes
        discovery["command"] = list(AVAHI_DISCOVERY_COMMAND)
    else:
        discovery["command"] = [
            "-identity-file",
            DISCOVERY_IDENTITY_FILE,
        ]
    return rendered


def _validate_discovery_transport(discovery: dict, version: str) -> str:
    volumes = discovery.get("volumes") or []
    dbus_mounts = [
        v for v in volumes
        if isinstance(v, dict) and (
            v.get("source") == DBUS_SOCKET or v.get("target") == DBUS_SOCKET
        )
    ]
    command = discovery.get("command") or []

    if version in AVAHI_TARGETS:
        if len(dbus_mounts) != 1:
            raise ControlError("25.x discovery requires exactly one Avahi system-bus mount")
        mount = dbus_mounts[0]
        if (
            mount.get("type") != "bind"
            or mount.get("source") != DBUS_SOCKET
            or mount.get("target") != DBUS_SOCKET
            or mount.get("read_only") is not True
        ):
            raise ControlError("25.x discovery Avahi system-bus mount drifted")
        if command != AVAHI_DISCOVERY_COMMAND:
            raise ControlError("25.x discovery must use the exact Avahi backend command")
        return "avahi"

    if version in DIRECT_TARGETS:
        if dbus_mounts:
            raise ControlError("direct discovery target must not mount the system bus")
        if "-backend" in command or "-dbus-address" in command:
            raise ControlError("direct discovery target must not select Avahi")
        return "direct"

    raise ControlError(f"unsupported FolioRelay target version: {version!r}")


def validate(publication: dict, compose: dict, target: dict) -> dict:
    version = target.get("truenas_version")
    profile_id = target.get("profile_id")
    if not isinstance(version, str) or not version:
        raise ControlError("target profile missing truenas_version")
    if not isinstance(profile_id, str) or not profile_id:
        raise ControlError("target profile missing profile_id")

    control_image, cups_image = _publication(publication)
    services = _services(compose)
    control = services["control"]
    cups = services["cups"]
    discovery = services["discovery"]

    if control.get("image") != control_image:
        raise ControlError("control image does not match admitted digest")
    if cups.get("image") != cups_image:
        raise ControlError("CUPS image does not match admitted digest")
    if discovery.get("image") != control_image:
        raise ControlError("discovery must reuse the exact admitted control image")

    for name, service in (("control", control), ("cups", cups), ("discovery", discovery)):
        _hardened(service, name)

    _require_mount(control, CONTROL_TARGET, CONTROL_ROOT, False)
    _require_mount(control, ARTIFACT_TARGET, ARTIFACT_ROOT, False)
    _require_mount(control, TOKEN_TARGET, TOKEN_PATH, True)

    _require_mount(cups, CUPS_CONTROL_TARGET, CONTROL_ROOT, True)
    _require_mount(cups, CUPS_ARTIFACT_TARGET, ARTIFACT_ROOT, False)
    _require_mount(cups, "/var/lib/cups", CUPS_STATE_ROOT, False)
    _require_mount(cups, "/var/spool/cups", CUPS_SPOOL_ROOT, False)
    _require_mount(cups, TOKEN_TARGET, TOKEN_PATH, True)

    _require_mount(discovery, CUPS_CONTROL_TARGET, CONTROL_ROOT, True)
    discovery_backend = _validate_discovery_transport(discovery, version)

    if not REQUIRED_CUPS_TMPFS.issubset(_tmpfs_targets(cups)):
        raise ControlError("CUPS ephemeral tmpfs contract drifted")

    if not _port(control, 18080, 18080):
        raise ControlError("control portal/API port mapping drifted")
    if not _port(cups, 8634, 8634):
        raise ControlError("CUPS IPP port mapping drifted")
    if discovery.get("network_mode") != "host":
        raise ControlError("discovery must use host networking for same-L2 mDNS")

    rendered = json.dumps(compose, sort_keys=True)
    for forbidden in (
        "/var/run/docker.sock",
        "/run/docker.sock",
        "/var/run/dbus",
        "/etc/avahi",
        ":latest",
        ":main-latest",
    ):
        if forbidden in rendered:
            raise ControlError(f"forbidden rendered content: {forbidden}")
    if version in DIRECT_TARGETS and "/run/dbus" in rendered:
        raise ControlError("direct discovery target must not couple to host D-Bus")
    if version in AVAHI_TARGETS:
        allowed = json.dumps({DBUS_SOCKET: DBUS_SOCKET})
        # Exact mount validation above is authoritative; this catches other D-Bus paths.
        other_dbus = [
            token for token in ("/run/dbus/", "/run/dbus")
            if token in rendered and DBUS_SOCKET not in rendered
        ]
        if other_dbus:
            raise ControlError("25.x discovery contains unexpected host D-Bus coupling")

    return {
        "control_image": control_image,
        "cups_image": cups_image,
        "source_revision": publication.get("source_revision"),
        "truenas_version": version,
        "target_profile_id": profile_id,
        "target_profile_schema": target.get("schema_version"),
        "discovery_backend": discovery_backend,
    }


def build(publication_path: Path, compose_path: Path, values_path: Path,
          target_path: Path, output: Path, foundry_ref: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", foundry_ref):
        raise ControlError("foundry_ref must be an exact 40-character commit SHA")

    publication = load_json(publication_path)
    source_compose = load_json(compose_path)
    target = load_json(target_path)
    compose = materialize_target_compose(source_compose, target)
    facts = validate(publication, compose, target)

    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(publication_path, output / "publication-receipt.json")
    (output / "compose.json").write_text(
        json.dumps(compose, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(values_path, output / "values.yaml")
    shutil.copy2(target_path, output / "target-profile.json")

    control = {
        "schema": SCHEMA,
        "foundry_ref": foundry_ref,
        "runtime": {
            "app_name": APP_NAME,
            "control_root": CONTROL_ROOT,
            "artifact_root": ARTIFACT_ROOT,
            "cups_state_root": CUPS_STATE_ROOT,
            "cups_spool_root": CUPS_SPOOL_ROOT,
            "token_path": TOKEN_PATH,
            "management_port": 18080,
            "ipp_port": 8634,
            "discovery_network_mode": "host",
            "discovery_backend": facts["discovery_backend"],
        },
        "candidate": facts,
        "artifacts": {
            "publication_receipt_sha256": sha256_file(publication_path),
            "compose_canonical_sha256": canonical_sha256(compose),
            "values_sha256": sha256_file(values_path),
            "target_profile_sha256": sha256_file(target_path),
        },
        "required_oracles": [
            "app-create-running",
            "config-readback-exact-compose",
            "portal-ready",
            "ipp-get-printer-attributes",
            "canonical-uri-coherence",
            "control-cups-dnssd-uuid-coherence",
            "dnssd-universal-visible",
            "pdf-exact-source-inbox",
            "urf-exact-source-inbox",
            "restart-preserves-identity-and-inbox",
            "update-redeploy-preserves-identity-and-inbox",
            "replan-noop",
            "delete-zero-residue",
        ],
        "secrets_captured": False,
    }
    (output / "control.json").write_text(
        json.dumps(control, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return control


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--publication-receipt", type=Path, required=True)
    p.add_argument("--compose", type=Path, required=True)
    p.add_argument("--values", type=Path, required=True)
    p.add_argument("--target-profile", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--foundry-ref", required=True)
    a = p.parse_args()
    try:
        control = build(
            a.publication_receipt,
            a.compose,
            a.values,
            a.target_profile,
            a.output,
            a.foundry_ref,
        )
        print(json.dumps({
            "status": "PASS",
            "schema": control["schema"],
            "foundry_ref": control["foundry_ref"],
            "truenas_version": control["candidate"]["truenas_version"],
            "compose_canonical_sha256": control["artifacts"]["compose_canonical_sha256"],
            "secrets_captured": False,
        }, sort_keys=True))
        return 0
    except (ControlError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
