#!/usr/bin/env python3
"""Materialize a lean Foundry candidate into an official-shaped TrueNAS dev app.

Public-safe source-rendering/target-lowering primitive. It does not contact a
TrueNAS host or consume credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


class MaterializationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def truenas_directory_hash(path: Path) -> str:
    if not path.is_dir():
        raise MaterializationError(f"not a directory: {path}")
    digests = sorted(sha256_file(p) for p in path.rglob("*") if p.is_file())
    payload = "".join(f"{digest}\n" for digest in digests).encode()
    return hashlib.sha256(payload).hexdigest()


def tree_fingerprint(path: Path) -> str:
    records: list[str] = []
    if not path.exists():
        return ""
    for p in sorted(path.rglob("*")):
        rel = p.relative_to(path).as_posix()
        if p.is_symlink():
            records.append(f"L {rel} {os.readlink(p)}")
        elif p.is_file():
            mode = p.stat().st_mode & 0o777
            records.append(f"F {mode:03o} {rel} {sha256_file(p)}")
        elif p.is_dir():
            records.append(f"D {rel}")
    return hashlib.sha256(("\n".join(records) + "\n").encode()).hexdigest()


def read_top_level_scalar(path: Path, key: str) -> str:
    prefix = f"{key}:"
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith(prefix):
            value = raw[len(prefix):].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if value:
                return value
    raise MaterializationError(f"{path}: missing top-level scalar {key}")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"cannot read candidate manifest {path}: {exc}") from exc
    for key in ("source_path", "source_materializer"):
        if not data.get(key):
            raise MaterializationError(f"candidate manifest missing {key}")
    materializer = data["source_materializer"]
    for key in ("repository", "commit", "train", "lib_version", "lib_hash"):
        if not materializer.get(key):
            raise MaterializationError(f"source_materializer missing {key}")
    commit = str(materializer["commit"])
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise MaterializationError("source_materializer.commit must be a full lowercase SHA")
    return data


def resolve_library(
    checkout: Path,
    *,
    train: str,
    version: str,
    expected_hash: str,
    destination: Path,
) -> tuple[Path, str]:
    base = f"base_v{version.replace('.', '_')}"
    candidates: list[Path] = []

    canonical = checkout / "library" / version
    if canonical.is_dir():
        candidates.append(canonical)

    ix_root = checkout / "ix-dev" / train
    if ix_root.is_dir():
        candidates.extend(sorted(ix_root.glob(f"*/templates/library/{base}")))

    seen: set[Path] = set()
    examined: list[tuple[str, str]] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen or candidate == destination.resolve():
            continue
        seen.add(candidate)
        actual = truenas_directory_hash(candidate)
        examined.append((str(candidate.relative_to(checkout.resolve())), actual))
        if actual == expected_hash:
            return candidate, actual

    detail = ", ".join(f"{p}={h}" for p, h in examined[:12])
    raise MaterializationError(
        f"no library tree matched version={version} hash={expected_hash}; examined: {detail}"
    )


def build_desired(repo_root: Path, manifest_path: Path, checkout: Path, root: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    materializer = manifest["source_materializer"]
    source = (repo_root / str(manifest["source_path"])).resolve()
    if not source.is_dir():
        raise MaterializationError(f"candidate source does not exist: {source}")

    app_yaml = source / "app.yaml"
    version = read_top_level_scalar(app_yaml, "lib_version")
    declared_hash = read_top_level_scalar(app_yaml, "lib_version_hash")
    if version != str(materializer["lib_version"]):
        raise MaterializationError(
            f"app lib_version {version} != manifest {materializer['lib_version']}"
        )
    if declared_hash != str(materializer["lib_hash"]):
        raise MaterializationError(
            f"app lib_version_hash {declared_hash} != manifest {materializer['lib_hash']}"
        )

    desired = root / "desired"
    shutil.copytree(source, desired)
    base = f"base_v{version.replace('.', '_')}"
    destination_library = desired / "templates" / "library" / base
    source_library, actual_hash = resolve_library(
        checkout,
        train=str(materializer["train"]),
        version=version,
        expected_hash=declared_hash,
        destination=destination_library,
    )
    destination_library.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_library, destination_library)

    copied_hash = truenas_directory_hash(destination_library)
    if copied_hash != declared_hash:
        raise MaterializationError(
            f"copied library hash mismatch: expected={declared_hash} actual={copied_hash}"
        )

    return {
        "manifest": manifest,
        "desired": desired,
        "source_library": source_library,
        "library_hash": copied_hash,
        "desired_fingerprint": tree_fingerprint(desired),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--upstream-checkout", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--mode", choices=("plan", "apply"), default="apply")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    manifest_path = args.manifest.resolve()
    checkout = args.upstream_checkout.resolve()
    destination = args.destination.resolve()

    try:
        manifest = load_manifest(manifest_path)
        expected_commit = str(manifest["source_materializer"]["commit"])
        if not (checkout / ".git").exists():
            raise MaterializationError(f"upstream checkout is not a git repository: {checkout}")

        import subprocess
        cp = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
        )
        if cp.returncode:
            raise MaterializationError(f"cannot resolve upstream HEAD: {cp.stderr.strip()}")
        actual_commit = cp.stdout.strip()
        if actual_commit != expected_commit:
            raise MaterializationError(
                f"upstream checkout mismatch: expected={expected_commit} actual={actual_commit}"
            )

        with tempfile.TemporaryDirectory(prefix="foundry-truenas-candidate-") as tmp:
            built = build_desired(repo_root, manifest_path, checkout, Path(tmp))
            desired = built["desired"]
            desired_fp = built["desired_fingerprint"]
            observed_fp = tree_fingerprint(destination)

            if not destination.exists():
                action = "CREATE"
            elif observed_fp == desired_fp:
                action = "NOOP"
            else:
                action = "DRIFT_REFUSE"

            receipt = {
                "schema": "semper-supra.truenas-candidate-materialization/1",
                "status": "PLANNED" if args.mode == "plan" else "PENDING",
                "action": action,
                "candidate": manifest.get("candidate"),
                "candidate_manifest_sha256": sha256_file(manifest_path),
                "upstream": {
                    "repository": manifest["source_materializer"]["repository"],
                    "commit": actual_commit,
                    "train": manifest["source_materializer"]["train"],
                    "library_version": manifest["source_materializer"]["lib_version"],
                    "library_hash": built["library_hash"],
                    "library_source": str(built["source_library"].relative_to(checkout)),
                },
                "desired_fingerprint": desired_fp,
                "observed_fingerprint": observed_fp or None,
                "secrets_captured": False,
            }

            if args.mode == "apply":
                if action == "CREATE":
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(desired, destination)
                    if tree_fingerprint(destination) != desired_fp:
                        raise MaterializationError("post-copy fingerprint verification failed")
                    receipt["status"] = "APPLIED"
                elif action == "NOOP":
                    receipt["status"] = "NOOP"
                else:
                    receipt["status"] = "REFUSED"
            payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            if args.evidence:
                args.evidence.write_text(payload, encoding="utf-8")
            print(payload, end="")
            return 0 if receipt["status"] != "REFUSED" else 3
    except MaterializationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
