#!/usr/bin/env python3
"""Prepare TrueNAS-equivalent platform values before pinned catalog rendering.

This tool is intentionally transport-agnostic. It never contacts a TrueNAS host.
A site adapter supplies locally resolved API objects/paths in --resolved. The tool
injects the reserved ix_* values that native catalog middleware would add and
emits a separate sanitized dependency/action plan suitable for evidence.

Sensitive normalized values (for example certificate private keys) are written
only to --output-values with mode 0600 and are never printed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml


RESERVED_NAMES = {
    "ix_certificates": dict,
    "ix_certificate_authorities": dict,
    "ix_volumes": dict,
    "ix_context": dict,
}


class MaterializationError(RuntimeError):
    pass


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MaterializationError(f"cannot read YAML {path}: {exc}") from exc


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"cannot read JSON {path}: {exc}") from exc


def refs(schema: dict[str, Any]) -> list[str]:
    value = schema.get("$ref", [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    if value:
        raise MaterializationError(f"invalid $ref value: {value!r}")
    return []


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MaterializationError(f"{label} must be an object")
    return value


def value_is_active(value: Any) -> bool:
    if value is None or value is False or value == "":
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    return True


def normalize_certificate(
    value: Any,
    normalized: dict[str, Any],
    resolved: dict[str, Any],
    plan: dict[str, Any],
    path: str,
) -> None:
    if not value_is_active(value):
        return
    cert_id = str(value)
    certs = require_mapping(resolved.get("certificates", {}), "resolved.certificates")
    if cert_id not in certs:
        raise MaterializationError(f"{path}: certificate {cert_id!r} was not resolved")
    cert = require_mapping(certs[cert_id], f"resolved.certificates[{cert_id!r}]")
    certificate = cert.get("certificate")
    privatekey = cert.get("privatekey")
    if not isinstance(certificate, str) or not certificate.strip():
        raise MaterializationError(f"{path}: resolved certificate {cert_id!r} has no certificate PEM")
    if not isinstance(privatekey, str) or not privatekey.strip():
        raise MaterializationError(f"{path}: resolved certificate {cert_id!r} has no private key PEM")

    normalized["ix_certificates"][value] = copy.deepcopy(cert)
    dependency = {
        "feature": "definitions/certificate",
        "id": cert_id,
        "public_certificate_sha256": sha256_text(certificate),
    }
    # Name is useful, public-safe metadata when supplied by the site adapter.
    if isinstance(cert.get("name"), str) and cert["name"]:
        dependency["name"] = cert["name"]
    plan["dependencies"].append(dependency)


def normalize_ix_volume(
    value: Any,
    normalized: dict[str, Any],
    resolved: dict[str, Any],
    plan: dict[str, Any],
    path: str,
) -> None:
    if not value_is_active(value):
        return
    volume = require_mapping(value, path)
    dataset_name = volume.get("dataset_name")
    if not isinstance(dataset_name, str) or not dataset_name:
        raise MaterializationError(f"{path}: ixVolume dataset_name is required")

    resolutions = require_mapping(resolved.get("ix_volumes", {}), "resolved.ix_volumes")
    if dataset_name not in resolutions:
        raise MaterializationError(f"{path}: ixVolume {dataset_name!r} was not resolved")
    resolution = require_mapping(
        resolutions[dataset_name], f"resolved.ix_volumes[{dataset_name!r}]"
    )
    host_path = resolution.get("host_path")
    if not isinstance(host_path, str) or not host_path.startswith("/"):
        raise MaterializationError(f"{path}: ixVolume host_path must be absolute")

    normalized["ix_volumes"][dataset_name] = host_path
    properties = resolution.get("properties") or volume.get("properties") or {}
    if not isinstance(properties, dict):
        raise MaterializationError(f"{path}: ixVolume properties must be an object")

    plan["actions"].append(
        {
            "action": "ensure-ix-volume",
            "dataset_name": dataset_name,
            "host_path_sha256": sha256_text(host_path),
            "properties_sha256": canonical_sha256(properties),
        }
    )


def apply_ref(
    ref: str,
    value: Any,
    normalized: dict[str, Any],
    resolved: dict[str, Any],
    plan: dict[str, Any],
    path: str,
) -> None:
    if ref == "definitions/certificate":
        normalize_certificate(value, normalized, resolved, plan, path)
        return
    if ref == "normalize/ix_volume":
        normalize_ix_volume(value, normalized, resolved, plan, path)
        return
    if ref == "normalize/acl":
        if value_is_active(value):
            raise MaterializationError(
                f"{path}: active normalize/acl is not qualified by the MVP profile"
            )
        return
    if ref == "definitions/node_bind_ip":
        if value_is_active(value):
            raise MaterializationError(
                f"{path}: active node_bind_ip requires normalized question-context validation"
            )
        return
    if ref in {
        "definitions/certificate_authority",
        "definitions/gpu_configuration",
    }:
        if value_is_active(value):
            raise MaterializationError(f"{path}: active {ref} is deferred and must fail closed")
        return

    if value_is_active(value):
        raise MaterializationError(f"{path}: unknown active TrueNAS feature ref {ref!r}")


def walk_schema_value(
    schema: dict[str, Any],
    value: Any,
    normalized: dict[str, Any],
    resolved: dict[str, Any],
    plan: dict[str, Any],
    path: str,
) -> None:
    for ref in refs(schema):
        apply_ref(ref, value, normalized, resolved, plan, path)

    schema_type = schema.get("type")
    if schema_type == "dict" and isinstance(value, dict):
        for child in schema.get("attrs", []) or []:
            if not isinstance(child, dict) or not isinstance(child.get("variable"), str):
                continue
            variable = child["variable"]
            if variable not in value:
                continue
            walk_schema_value(
                require_mapping(child.get("schema", {}), f"schema for {path}.{variable}"),
                value[variable],
                normalized,
                resolved,
                plan,
                f"{path}.{variable}",
            )
    elif schema_type == "list" and isinstance(value, list):
        item_schemas = schema.get("items", []) or []
        for index, item in enumerate(value):
            if not item_schemas:
                continue
            matched = False
            errors: list[str] = []
            for item_def in item_schemas:
                if not isinstance(item_def, dict):
                    continue
                item_schema = require_mapping(item_def.get("schema", {}), f"list schema at {path}")
                try:
                    walk_schema_value(
                        item_schema,
                        item,
                        normalized,
                        resolved,
                        plan,
                        f"{path}[{index}]",
                    )
                    matched = True
                    break
                except MaterializationError as exc:
                    errors.append(str(exc))
            if not matched and errors:
                raise MaterializationError(errors[0])


def prepare_values(
    questions: dict[str, Any], values: dict[str, Any], resolved: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = copy.deepcopy(require_mapping(values, "values"))
    # Match middleware behavior: caller-provided reserved names never win.
    for name, factory in RESERVED_NAMES.items():
        normalized[name] = factory()

    plan: dict[str, Any] = {
        "schema_version": 1,
        "dependencies": [],
        "actions": [],
        "policy": {
            "unknown_active_ref": "fail-closed",
            "sensitive_normalized_values_in_plan": False,
        },
    }

    for question in questions.get("questions", []) or []:
        if not isinstance(question, dict) or not isinstance(question.get("variable"), str):
            continue
        variable = question["variable"]
        if variable not in normalized:
            continue
        walk_schema_value(
            require_mapping(question.get("schema", {}), f"schema for {variable}"),
            normalized[variable],
            normalized,
            resolved,
            plan,
            variable,
        )

    plan["dependencies"] = sorted(
        plan["dependencies"], key=lambda item: (item["feature"], item.get("id", ""))
    )
    plan["actions"] = sorted(
        plan["actions"], key=lambda item: (item["action"], item.get("dataset_name", ""))
    )
    plan["dependency_identity_sha256"] = canonical_sha256(
        {"dependencies": plan["dependencies"], "actions": plan["actions"]}
    )
    return normalized, plan


def write_private_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    os.chmod(path, 0o600)


def write_plan(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--values", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--output-values", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()

    try:
        questions = require_mapping(load_yaml(args.questions) or {}, "questions document")
        values = require_mapping(load_yaml(args.values) or {}, "values document")
        resolved = require_mapping(load_json(args.resolved) or {}, "resolved document")
        normalized, plan = prepare_values(questions, values, resolved)
        write_private_yaml(args.output_values, normalized)
        write_plan(args.plan, plan)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "dependency_identity_sha256": plan["dependency_identity_sha256"],
                    "dependencies": len(plan["dependencies"]),
                    "actions": len(plan["actions"]),
                    "normalized_values_mode": "0600",
                },
                sort_keys=True,
            )
        )
        return 0
    except (MaterializationError, OSError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
