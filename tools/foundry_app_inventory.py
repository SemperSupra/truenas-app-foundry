#!/usr/bin/env python3
"""Read-only Git-backed inventory for Foundry app sources and exact TrueNAS targets."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / ".foundry" / "app-inventory.json"
DEFAULT_TARGETS = REPO_ROOT / ".foundry" / "truenas-target-tracks.json"
APP_ID_RE = re.compile(r"^[a-z]([-a-z0-9]*[a-z0-9])?$")
EXACT_REF_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_TRAINS = {"test", "community", "stable", "enterprise", "none"}


class InventoryError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot read JSON {path}: {exc}") from exc


def require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"{field} must be a non-empty string")
    return value


def validate_source(source: Any, prefix: str) -> None:
    if not isinstance(source, dict):
        raise InventoryError(f"{prefix}.source must be an object")
    kind = require_text(source.get("kind"), f"{prefix}.source.kind")
    if kind not in {"foundry-repository", "truenas-apps-upstream"}:
        raise InventoryError(f"{prefix}.source.kind is unsupported: {kind!r}")
    require_text(source.get("repository"), f"{prefix}.source.repository")
    ref = require_text(source.get("ref"), f"{prefix}.source.ref")
    if not EXACT_REF_RE.fullmatch(ref):
        raise InventoryError(f"{prefix}.source.ref must be an exact 40-hex commit")
    path = require_text(source.get("path"), f"{prefix}.source.path")
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise InventoryError(f"{prefix}.source.path must be repository-relative and non-escaping")


def validate_entry(entry: Any, index: int) -> tuple[str, str]:
    prefix = f"apps[{index}]"
    if not isinstance(entry, dict):
        raise InventoryError(f"{prefix} must be an object")

    app_id = require_text(entry.get("id"), f"{prefix}.id")
    if not APP_ID_RE.fullmatch(app_id) or len(app_id) > 80:
        raise InventoryError(f"{prefix}.id does not satisfy the Foundry app-id contract")
    version = require_text(entry.get("version"), f"{prefix}.version")
    validate_source(entry.get("source"), prefix)

    train = entry.get("catalog_train", "none")
    if train not in ALLOWED_TRAINS:
        raise InventoryError(f"{prefix}.catalog_train must be one of {sorted(ALLOWED_TRAINS)!r}")

    targets = entry.get("target_versions", [])
    if not isinstance(targets, list) or not all(isinstance(v, str) and v for v in targets):
        raise InventoryError(f"{prefix}.target_versions must be an array of exact version strings")
    if len(targets) != len(set(targets)):
        raise InventoryError(f"{prefix}.target_versions contains duplicates")

    export = entry.get("catalog_export", {"status": "not-assessed"})
    if not isinstance(export, dict):
        raise InventoryError(f"{prefix}.catalog_export must be an object")
    require_text(export.get("status"), f"{prefix}.catalog_export.status")
    return app_id, version


def validate_inventory(doc: Any) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        raise InventoryError("inventory must be an object")
    if doc.get("schema") != "truenas-foundry-app-inventory/v1":
        raise InventoryError("unsupported inventory schema")
    apps = doc.get("apps")
    if not isinstance(apps, list):
        raise InventoryError("apps must be an array")

    seen: set[tuple[str, str]] = set()
    validated: list[dict[str, Any]] = []
    for index, entry in enumerate(apps):
        key = validate_entry(entry, index)
        if key in seen:
            raise InventoryError(f"duplicate app/version inventory entry: {key[0]}@{key[1]}")
        seen.add(key)
        validated.append(entry)
    return validated


def load_target_map(doc: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise InventoryError("unsupported TrueNAS target-track schema")
    targets = doc.get("targets")
    if not isinstance(targets, list):
        raise InventoryError("target tracks must contain a targets array")
    result: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict):
            raise InventoryError("target entry must be an object")
        version = require_text(target.get("version"), "target.version")
        if version in result:
            raise InventoryError(f"duplicate exact TrueNAS target version: {version}")
        result[version] = target
    return result


def sorted_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda item: (str(item["id"]), str(item["version"])))


def list_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "truenas-foundry-app-inventory-list/v1",
        "count": len(entries),
        "apps": [
            {
                "id": item["id"],
                "version": item["version"],
                "catalog_train": item.get("catalog_train", "none"),
                "source_kind": item["source"]["kind"],
                "target_versions": item.get("target_versions", []),
            }
            for item in sorted_entries(entries)
        ],
    }


def find_entry(entries: list[dict[str, Any]], app_id: str, version: str) -> dict[str, Any]:
    matches = [item for item in entries if item["id"] == app_id and item["version"] == version]
    if len(matches) != 1:
        raise InventoryError(f"inventory has no unique exact entry for {app_id}@{version}")
    return matches[0]


def show_entry(entries: list[dict[str, Any]], app_id: str, version: str) -> dict[str, Any]:
    return {
        "schema": "truenas-foundry-app-inventory-entry/v1",
        "entry": find_entry(entries, app_id, version),
    }


def resolve_entry(
    entries: list[dict[str, Any]],
    targets: dict[str, dict[str, Any]],
    app_id: str,
    version: str,
    target_version: str,
) -> dict[str, Any]:
    entry = find_entry(entries, app_id, version)
    target = targets.get(target_version)
    if target is None:
        raise InventoryError(f"exact TrueNAS target is not registered: {target_version}")

    allowed_targets = entry.get("target_versions", [])
    if allowed_targets and target_version not in allowed_targets:
        raise InventoryError(
            f"{app_id}@{version} does not admit exact TrueNAS target {target_version}"
        )

    return {
        "schema": "truenas-foundry-app-resolution/v1",
        "app": {
            "id": entry["id"],
            "version": entry["version"],
            "source": entry["source"],
            "catalog_train": entry.get("catalog_train", "none"),
            "catalog_export": entry.get("catalog_export", {"status": "not-assessed"}),
        },
        "target": {
            "version": target_version,
            "channel": target.get("channel"),
            "profile": target.get("profile"),
            "source_qualification": target.get("source_qualification"),
            "runtime_qualification": target.get("runtime_qualification"),
            "accepted_runtime_rung": target.get("accepted_runtime_rung"),
            "apply_qualified": bool(target.get("apply_qualified", False)),
        },
        "mutation_eligible": bool(target.get("apply_qualified", False)),
        "note": (
            "resolution is descriptive only; apply remains gated by exact target qualification "
            "and a separately accepted READY plan"
        ),
    }



def _yaml_scalar(path: Path, key: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InventoryError(f"cannot read bootstrap app metadata {path}: {exc}") from exc
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    if not match:
        raise InventoryError(f"bootstrap app.yaml is missing top-level {key}")
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def _tree_sha256(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\\0")
        digest.update(path.read_bytes())
        digest.update(b"\\0")
        count += 1
    return digest.hexdigest(), count


def bootstrap_entry(entry: Any, source_root: Path) -> dict[str, Any]:
    validate_entry(entry, 0)
    source = entry["source"]
    source_root = source_root.resolve()
    app_root = (source_root / source["path"]).resolve()
    try:
        app_root.relative_to(source_root)
    except ValueError as exc:
        raise InventoryError("bootstrap source path escapes the supplied source root") from exc
    if not app_root.is_dir():
        raise InventoryError(f"bootstrap app source path does not exist: {source['path']}")

    required = [
        app_root / "app.yaml",
        app_root / "questions.yaml",
        app_root / "templates" / "docker-compose.yaml",
    ]
    missing = [p.relative_to(source_root).as_posix() for p in required if not p.is_file()]
    if missing:
        raise InventoryError(f"bootstrap app source is incomplete; missing: {missing}")

    observed = {
        "name": _yaml_scalar(app_root / "app.yaml", "name"),
        "version": _yaml_scalar(app_root / "app.yaml", "version"),
        "app_version": _yaml_scalar(app_root / "app.yaml", "app_version"),
        "train": _yaml_scalar(app_root / "app.yaml", "train"),
    }
    if observed["name"] != entry["id"]:
        raise InventoryError(
            f"bootstrap app id mismatch: inventory {entry['id']!r}, source {observed['name']!r}"
        )
    if observed["version"] != entry["version"]:
        raise InventoryError(
            f"bootstrap app version mismatch: inventory {entry['version']!r}, source {observed['version']!r}"
        )
    if observed["train"] != entry.get("catalog_train", "none"):
        raise InventoryError(
            f"bootstrap train mismatch: inventory {entry.get('catalog_train')!r}, source {observed['train']!r}"
        )

    tree_sha256, file_count = _tree_sha256(app_root)
    return {
        "schema": "truenas-foundry-app-bootstrap/v1",
        "status": "PASS",
        "entry": entry,
        "source_validation": {
            "ref": source["ref"],
            "path": source["path"],
            "app_yaml": observed,
            "required_files": [
                p.relative_to(app_root).as_posix() for p in required
            ],
            "tree_sha256": tree_sha256,
            "file_count": file_count,
        },
        "mutation_performed": False,
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    p.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("validate")
    sub.add_parser("list")

    show = sub.add_parser("show")
    show.add_argument("--app", required=True)
    show.add_argument("--version", required=True)

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--app", required=True)
    resolve.add_argument("--version", required=True)
    resolve.add_argument("--target-version", required=True)

    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--entry-file", type=Path, required=True)
    bootstrap.add_argument("--source-root", type=Path, required=True)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        entries = validate_inventory(load_json(args.inventory))
        if args.command == "validate":
            payload = {
                "status": "PASS",
                "schema": "truenas-foundry-app-inventory/v1",
                "entries": len(entries),
            }
        elif args.command == "list":
            payload = list_entries(entries)
        elif args.command == "show":
            payload = show_entry(entries, args.app, args.version)
        elif args.command == "resolve":
            targets = load_target_map(load_json(args.targets))
            payload = resolve_entry(
                entries, targets, args.app, args.version, args.target_version
            )
        elif args.command == "bootstrap":
            candidate = load_json(args.entry_file)
            payload = bootstrap_entry(candidate, args.source_root)
        else:
            raise InventoryError(f"unsupported command: {args.command}")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except InventoryError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
