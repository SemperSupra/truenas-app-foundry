#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any

ALLOWED_STATUS = {"OPEN", "PASS", "FAIL", "NOT_APPLICABLE"}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class MatrixError(RuntimeError):
    pass


def load(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MatrixError(f"{path} must contain an object")
    return value


def target_versions(registry: dict[str, Any]) -> list[str]:
    rows = registry.get("targets")
    if not isinstance(rows, list) or not rows:
        raise MatrixError("target registry has no targets")
    versions = [row.get("version") for row in rows if isinstance(row, dict)]
    if any(not isinstance(v, str) or not v for v in versions):
        raise MatrixError("target registry contains invalid versions")
    if len(versions) != len(set(versions)):
        raise MatrixError("target registry contains duplicate versions")
    return versions


def candidate_paths(repo_root: pathlib.Path) -> set[str]:
    root = repo_root / "candidates"
    if not root.is_dir():
        return set()
    return {
        p.relative_to(repo_root).as_posix()
        for p in root.glob("*/candidate.json")
        if p.is_file()
    }


def validate_pass_evidence(entry_id: str, version: str, evidence: Any) -> None:
    if not isinstance(evidence, dict):
        raise MatrixError(f"{entry_id}/{version}: PASS requires evidence object")
    required = {
        "run_id": int,
        "artifact_id": int,
        "artifact_digest": str,
        "profile_identity": str,
        "source_identity": str,
        "classification": str,
        "oracle_satisfied": bool,
        "f0_f5_complete": bool,
    }
    for field, typ in required.items():
        if not isinstance(evidence.get(field), typ):
            raise MatrixError(f"{entry_id}/{version}: PASS evidence missing/invalid {field}")
    if evidence["classification"] != "SUPPORTED":
        raise MatrixError(f"{entry_id}/{version}: PASS classification must be SUPPORTED")
    if evidence["oracle_satisfied"] is not True or evidence["f0_f5_complete"] is not True:
        raise MatrixError(f"{entry_id}/{version}: PASS requires oracle_satisfied + f0_f5_complete")
    if not SHA256.fullmatch(evidence["artifact_digest"]):
        raise MatrixError(f"{entry_id}/{version}: invalid artifact digest")
    if not evidence["profile_identity"] or not evidence["source_identity"]:
        raise MatrixError(f"{entry_id}/{version}: empty profile/source identity")


def validate(matrix: dict[str, Any], registry: dict[str, Any], repo_root: pathlib.Path) -> dict[str, Any]:
    if matrix.get("schema") != "truenas-foundry-product-target-matrix/v1":
        raise MatrixError("unsupported matrix schema")

    required = target_versions(registry)
    declared = matrix.get("required_target_versions")
    if declared != required:
        raise MatrixError(
            f"matrix target list must exactly match target registry: expected={required!r} observed={declared!r}"
        )

    entries = matrix.get("entries")
    if not isinstance(entries, list) or not entries:
        raise MatrixError("matrix requires entries")

    ids: set[str] = set()
    represented_candidates: set[str] = set()
    required_product_passes: list[bool] = []
    summary: list[dict[str, Any]] = []

    for entry in entries:
        if not isinstance(entry, dict):
            raise MatrixError("matrix entry must be object")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id or entry_id in ids:
            raise MatrixError(f"invalid/duplicate entry id: {entry_id!r}")
        ids.add(entry_id)

        classification = entry.get("classification")
        if classification not in {"product", "qualification-control"}:
            raise MatrixError(f"{entry_id}: unsupported classification")

        source = entry.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("kind"), str):
            raise MatrixError(f"{entry_id}: source contract missing")
        candidate_path = source.get("candidate_path")
        if candidate_path is not None:
            if not isinstance(candidate_path, str) or not (repo_root / candidate_path).is_file():
                raise MatrixError(f"{entry_id}: candidate path missing: {candidate_path!r}")
            represented_candidates.add(candidate_path)

        statuses = entry.get("target_status")
        if not isinstance(statuses, dict) or list(statuses) != required:
            raise MatrixError(f"{entry_id}: target_status keys/order must exactly match target registry")

        pass_flags: list[bool] = []
        for version in required:
            cell = statuses[version]
            if not isinstance(cell, dict):
                raise MatrixError(f"{entry_id}/{version}: cell must be object")
            status = cell.get("status")
            if status not in ALLOWED_STATUS:
                raise MatrixError(f"{entry_id}/{version}: invalid status {status!r}")
            if status == "PASS":
                validate_pass_evidence(entry_id, version, cell.get("evidence"))
                pass_flags.append(True)
            else:
                if cell.get("evidence") is not None:
                    raise MatrixError(f"{entry_id}/{version}: non-PASS cell must not carry acceptance evidence")
                pass_flags.append(False)

        all_targets = all(pass_flags)
        if classification == "product" and entry.get("required_for_all_products_claim") is True:
            required_product_passes.append(all_targets)

        summary.append({
            "id": entry_id,
            "classification": classification,
            "all_targets_qualified": all_targets,
            "status": {v: statuses[v]["status"] for v in required},
        })

    discovered = candidate_paths(repo_root)
    missing = sorted(discovered - represented_candidates)
    if missing:
        raise MatrixError(f"Foundry candidates omitted from matrix: {missing}")

    computed_all = bool(required_product_passes) and all(required_product_passes)
    if matrix.get("all_required_product_cells_qualified") is not computed_all:
        raise MatrixError(
            "all_required_product_cells_qualified does not match computed product matrix state"
        )

    return {
        "schema": "truenas-foundry-product-target-matrix-validation/v1",
        "status": "PASS",
        "required_target_versions": required,
        "discovered_candidate_paths": sorted(discovered),
        "entries": summary,
        "all_required_product_cells_qualified": computed_all,
        "claim_boundary": "coverage/receipt contract only; runtime support exists only in PASS cells",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=pathlib.Path, default=pathlib.Path(".foundry/product-app-target-matrix.json"))
    p.add_argument("--targets", type=pathlib.Path, default=pathlib.Path(".foundry/truenas-target-tracks.json"))
    p.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path("."))
    p.add_argument("--out", type=pathlib.Path)
    a = p.parse_args()
    try:
        result = validate(load(a.matrix), load(a.targets), a.repo_root)
    except MatrixError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if a.out:
        a.out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
