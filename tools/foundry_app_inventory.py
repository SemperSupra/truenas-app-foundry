#!/usr/bin/env python3
"""Git-backed inventory and bootstrap admission for Foundry TrueNAS app sources."""
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
ALLOWED_TRAINS = {"test", "community", "stable", "enterprise", "none"}
BOOTSTRAP_SCHEMA = "truenas-foundry-app-bootstrap/v1"
QUALIFICATION_SCHEMA = "truenas-foundry-catalog-candidate-evidence/v1"
INVENTORY_SCHEMA = "truenas-foundry-app-inventory/v1"
CATALOG_SOURCE_SHAPE = "truenas-apps-ix-dev/v1"
REQUIRED_CATALOG_FILES = (
    "README.md",
    "app.yaml",
    "ix_values.yaml",
    "questions.yaml",
    "templates/docker-compose.yaml",
)


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
    require_text(source.get("ref"), f"{prefix}.source.ref")
    source_path = require_text(source.get("path"), f"{prefix}.source.path")
    path = Path(source_path)
    if path.is_absolute() or ".." in path.parts:
        raise InventoryError(f"{prefix}.source.path must be a repository-relative path")


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

    source_contract = entry.get("source_contract")
    if source_contract is not None:
        if not isinstance(source_contract, dict):
            raise InventoryError(f"{prefix}.source_contract must be an object")
        if source_contract.get("catalog_source_shape") != CATALOG_SOURCE_SHAPE:
            raise InventoryError(
                f"{prefix}.source_contract.catalog_source_shape must be {CATALOG_SOURCE_SHAPE!r}"
            )
        require_text(
            source_contract.get("source_tree_sha256"),
            f"{prefix}.source_contract.source_tree_sha256",
        )
        if source_contract.get("structural_preflight") != "PASS":
            raise InventoryError(f"{prefix}.source_contract.structural_preflight must be PASS")
        if source_contract.get("official_validator") not in {"PENDING", "PASS"}:
            raise InventoryError(
                f"{prefix}.source_contract.official_validator must be PENDING or PASS"
            )

    qualification = entry.get("catalog_qualification")
    if qualification is not None:
        if not isinstance(qualification, dict):
            raise InventoryError(f"{prefix}.catalog_qualification must be an object")
        if qualification.get("status") != "PASS":
            raise InventoryError(f"{prefix}.catalog_qualification.status must be PASS")
        require_text(
            qualification.get("source_tree_sha256"),
            f"{prefix}.catalog_qualification.source_tree_sha256",
        )
        require_text(
            qualification.get("evidence_sha256"),
            f"{prefix}.catalog_qualification.evidence_sha256",
        )
        gates = qualification.get("gates")
        if not isinstance(gates, dict):
            raise InventoryError(f"{prefix}.catalog_qualification.gates must be an object")
        if gates.get("native_validator") != "PASS" or gates.get("render_install") != "PASS":
            raise InventoryError(
                f"{prefix}.catalog_qualification requires native_validator=PASS and render_install=PASS"
            )
    return app_id, version


def validate_inventory(doc: Any) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        raise InventoryError("inventory must be an object")
    if doc.get("schema") != INVENTORY_SCHEMA:
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
            "source_contract": entry.get("source_contract"),
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


def _top_level_yaml_scalar(path: Path, key: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}\s*:\s*(.*?)\s*$")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InventoryError(f"cannot read {path}: {exc}") from exc
    values: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t", "#")):
            continue
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values.append(value)
    if len(values) != 1 or not values[0]:
        raise InventoryError(f"{path.name} must contain exactly one top-level {key!r} scalar")
    return values[0]


def _source_files(source_root: Path) -> list[Path]:
    if not source_root.is_dir():
        raise InventoryError(f"source root is not a directory: {source_root}")
    for required in REQUIRED_CATALOG_FILES:
        path = source_root / required
        if not path.is_file() or path.is_symlink():
            raise InventoryError(f"catalog source is missing required regular file: {required}")

    test_dir = source_root / "templates" / "test_values"
    if not test_dir.is_dir() or test_dir.is_symlink():
        raise InventoryError("catalog source requires templates/test_values directory")
    test_values = sorted(
        p
        for p in test_dir.iterdir()
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in {".yaml", ".yml"}
    )
    if not test_values:
        raise InventoryError("catalog source requires at least one YAML test-values file")

    files: list[Path] = []
    for path in sorted(source_root.rglob("*")):
        rel = path.relative_to(source_root)
        if ".git" in rel.parts or rel.parts[:2] == ("templates", "rendered"):
            continue
        if path.is_symlink():
            raise InventoryError(f"catalog source must not contain symlinks: {rel.as_posix()}")
        if path.is_file():
            files.append(path)
    return files


def structural_source_contract(
    source_root: Path,
    *,
    app_id: str,
    version: str,
    train: str,
) -> dict[str, Any]:
    files = _source_files(source_root)
    app_yaml = source_root / "app.yaml"
    observed = {
        "name": _top_level_yaml_scalar(app_yaml, "name"),
        "version": _top_level_yaml_scalar(app_yaml, "version"),
        "train": _top_level_yaml_scalar(app_yaml, "train"),
    }
    expected = {"name": app_id, "version": version, "train": train}
    if observed != expected:
        raise InventoryError(
            f"app.yaml identity mismatch: expected {expected!r}, observed {observed!r}"
        )

    digest = hashlib.sha256()
    file_records: list[dict[str, Any]] = []
    for path in files:
        rel = path.relative_to(source_root).as_posix()
        data = path.read_bytes()
        file_sha = hashlib.sha256(data).hexdigest()
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(data)
        digest.update(b"\0")
        file_records.append({"path": rel, "sha256": file_sha})

    test_values = [
        item["path"]
        for item in file_records
        if item["path"].startswith("templates/test_values/")
        and item["path"].lower().endswith((".yaml", ".yml"))
    ]
    return {
        "catalog_source_shape": CATALOG_SOURCE_SHAPE,
        "structural_preflight": "PASS",
        "source_tree_sha256": "sha256:" + digest.hexdigest(),
        "required_files": list(REQUIRED_CATALOG_FILES),
        "test_values": test_values,
        "file_count": len(file_records),
        "official_validator": "PENDING",
        "non_claim": (
            "structural preflight does not replace TrueNAS apps_dev_charts_validate "
            "or the upstream render/install test suite"
        ),
    }


def bootstrap_candidate(
    inventory_doc: dict[str, Any],
    target_doc: dict[str, Any],
    spec: dict[str, Any],
    source_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entries = validate_inventory(inventory_doc)
    targets = load_target_map(target_doc)
    if not isinstance(spec, dict) or spec.get("schema") != BOOTSTRAP_SCHEMA:
        raise InventoryError("unsupported bootstrap specification schema")
    raw_entry = spec.get("entry")
    if not isinstance(raw_entry, dict):
        raise InventoryError("bootstrap specification requires an entry object")

    entry = json.loads(json.dumps(raw_entry))
    validate_entry(entry, len(entries))
    app_id = entry["id"]
    version = entry["version"]
    if any(item["id"] == app_id and item["version"] == version for item in entries):
        raise InventoryError(f"inventory already contains exact app/version {app_id}@{version}")
    if entry["source"]["kind"] != "foundry-repository":
        raise InventoryError("bootstrap admits only foundry-repository sources")
    admitted_targets = entry.get("target_versions", [])
    if not admitted_targets:
        raise InventoryError("bootstrap requires at least one exact target version")
    unknown = sorted(set(admitted_targets) - set(targets))
    if unknown:
        raise InventoryError(f"bootstrap references unregistered exact target versions: {unknown!r}")
    train = entry.get("catalog_train", "none")
    if train == "none":
        raise InventoryError("bootstrap requires an explicit catalog train")

    entry["source_contract"] = structural_source_contract(
        source_root,
        app_id=app_id,
        version=version,
        train=train,
    )
    entry.setdefault("catalog_export", {"status": "not-assessed"})
    proposed = {
        "schema": INVENTORY_SCHEMA,
        "apps": sorted_entries(entries + [entry]),
    }
    receipt = {
        "schema": "truenas-foundry-app-bootstrap-receipt/v1",
        "status": "READY_FOR_GIT_REVIEW",
        "app": app_id,
        "version": version,
        "catalog_train": train,
        "source": entry["source"],
        "source_contract": entry["source_contract"],
        "target_versions": admitted_targets,
        "proposal_entries": len(proposed["apps"]),
        "mutation_performed": False,
        "catalog_ready": False,
        "next_gate": "official TrueNAS dev-catalog validation and render/install tests",
    }
    return receipt, proposed


def qualify_candidate(
    inventory_doc: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    entries = validate_inventory(inventory_doc)
    if not isinstance(evidence, dict) or evidence.get("schema") != QUALIFICATION_SCHEMA:
        raise InventoryError("unsupported catalog qualification evidence schema")

    app_id = require_text(evidence.get("app"), "evidence.app")
    version = require_text(evidence.get("version"), "evidence.version")
    source_tree_sha = require_text(
        evidence.get("source_tree_sha256"),
        "evidence.source_tree_sha256",
    )
    gates = evidence.get("gates")
    if not isinstance(gates, dict):
        raise InventoryError("evidence.gates must be an object")
    if gates.get("native_validator") != "PASS":
        raise InventoryError("catalog qualification requires native_validator=PASS")
    if gates.get("render_install") != "PASS":
        raise InventoryError("catalog qualification requires render_install=PASS")

    entry = find_entry(entries, app_id, version)
    source_contract = entry.get("source_contract")
    if not isinstance(source_contract, dict):
        raise InventoryError("inventory entry has no bootstrap source contract")
    if source_contract.get("source_tree_sha256") != source_tree_sha:
        raise InventoryError("catalog qualification source-tree identity mismatch")
    if source_contract.get("structural_preflight") != "PASS":
        raise InventoryError("catalog qualification requires structural preflight PASS")

    toolchain = evidence.get("toolchain")
    if not isinstance(toolchain, dict):
        raise InventoryError("evidence.toolchain must be an object")
    for field in ("apps_ref", "apps_validation_ref", "middleware_base"):
        require_text(toolchain.get(field), f"evidence.toolchain.{field}")

    evidence_sha = "sha256:" + hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    qualified = json.loads(json.dumps(inventory_doc))
    qualified_entries = validate_inventory(qualified)
    qualified_entry = find_entry(qualified_entries, app_id, version)
    qualified_entry["source_contract"]["official_validator"] = "PASS"
    qualified_entry["catalog_export"] = {
        "status": "catalog-ready-candidate",
        "publication_performed": False,
    }
    qualified_entry["catalog_qualification"] = {
        "status": "PASS",
        "source_tree_sha256": source_tree_sha,
        "gates": {
            "native_validator": "PASS",
            "render_install": "PASS",
        },
        "toolchain": toolchain,
        "evidence_sha256": evidence_sha,
    }
    validate_inventory(qualified)

    receipt = {
        "schema": "truenas-foundry-catalog-qualification-receipt/v1",
        "status": "CATALOG_READY_CANDIDATE",
        "app": app_id,
        "version": version,
        "source_tree_sha256": source_tree_sha,
        "official_validator": "PASS",
        "catalog_export_status": "catalog-ready-candidate",
        "evidence_sha256": evidence_sha,
        "publication_performed": False,
        "mutation_performed": False,
    }
    return receipt, qualified


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
    bootstrap.add_argument("--spec", type=Path, required=True)
    bootstrap.add_argument("--source-root", type=Path, required=True)
    bootstrap.add_argument("--proposal-out", type=Path, required=True)
    bootstrap.add_argument("--receipt-out", type=Path)

    qualify = sub.add_parser("qualify")
    qualify.add_argument("--evidence", type=Path, required=True)
    qualify.add_argument("--qualified-out", type=Path, required=True)
    qualify.add_argument("--receipt-out", type=Path)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        inventory_doc = load_json(args.inventory)
        entries = validate_inventory(inventory_doc)
        if args.command == "validate":
            payload = {
                "status": "PASS",
                "schema": INVENTORY_SCHEMA,
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
            receipt, proposed = bootstrap_candidate(
                inventory_doc,
                load_json(args.targets),
                load_json(args.spec),
                args.source_root,
            )
            args.proposal_out.parent.mkdir(parents=True, exist_ok=True)
            args.proposal_out.write_text(
                json.dumps(proposed, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if args.receipt_out:
                args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
                args.receipt_out.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            payload = receipt
        elif args.command == "qualify":
            receipt, qualified = qualify_candidate(
                inventory_doc,
                load_json(args.evidence),
            )
            args.qualified_out.parent.mkdir(parents=True, exist_ok=True)
            args.qualified_out.write_text(
                json.dumps(qualified, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if args.receipt_out:
                args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
                args.receipt_out.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            payload = receipt
        else:
            raise InventoryError(f"unsupported command: {args.command}")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (InventoryError, OSError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
