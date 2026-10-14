#!/usr/bin/env python3
"""Project a clean, SHA-pinned official truenas/apps source into discovery.

Consumes the same source-tree preflight used by Foundry's canonical inventory.
Requires a real, clean Git checkout at the admitted full SHA. Never downloads,
executes templates, touches middleware, or authorizes installation.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
APP_NAME = re.compile(r"[a-z]([-a-z0-9]*[a-z0-9])?\Z")
MAX_PIN_BYTES = 65536
MAX_APPS = 32


def sibling(name: str):
    path = HERE / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


inventory = sibling("foundry_app_inventory")
federation = sibling("foundry_catalog_federation")


class OfficialCatalogError(ValueError):
    pass


def git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), *args]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=15)
    if proc.returncode:
        raise OfficialCatalogError("official source checkout Git verification failed")
    return proc.stdout.strip()


def verify_checkout(checkout: Path, revision: str, paths: list[str]) -> None:
    if not checkout.is_dir() or checkout.is_symlink():
        raise OfficialCatalogError("source checkout must be a regular directory")
    if not SHA40.fullmatch(revision):
        raise OfficialCatalogError("source checkout ref must be exact lowercase SHA")
    if Path(git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout.resolve():
        raise OfficialCatalogError("source checkout must be the Git worktree root")
    if git(checkout, "rev-parse", "HEAD") != revision:
        raise OfficialCatalogError("source checkout HEAD does not match pinned revision")
    # Sparse checkout must not omit the requested source directories.
    # Confirm that selected files are tracked and no selected tree is dirty.
    for path in paths:
        app_root = checkout / path
        if not app_root.is_dir() or app_root.is_symlink():
            raise OfficialCatalogError("selected official source path is not a directory")
        count = git(checkout, "ls-files", "--", path)
        if not count:
            raise OfficialCatalogError("selected official source path has no tracked files")
        if git(checkout, "status", "--porcelain", "--untracked-files=all", "--", path):
            raise OfficialCatalogError("selected official app source is dirty")


def project(pin: dict[str, Any], checkout: Path, apps: list[str]) -> dict[str, Any]:
    if not isinstance(pin, dict) or pin.get("schema_version") != 1:
        raise OfficialCatalogError("unsupported upstream pin")
    if pin.get("repository") != "https://github.com/truenas/apps.git":
        raise OfficialCatalogError("official source repository identity mismatch")
    revision = pin.get("ref")
    train = pin.get("train")
    if not isinstance(revision, str) or not SHA40.fullmatch(revision):
        raise OfficialCatalogError("official catalog Git revision not pinned")
    if train not in {"community", "stable", "enterprise", "test"}:
        raise OfficialCatalogError("unknown official catalog train")
    if not apps or len(apps) > MAX_APPS or len(apps) != len(set(apps)):
        raise OfficialCatalogError("app selection must be a bounded unique set")
    if not all(isinstance(app, str) and APP_NAME.fullmatch(app) for app in apps):
        raise OfficialCatalogError("invalid official app name")
    paths = [f"ix-dev/{train}/{app}" for app in apps]
    verify_checkout(checkout, revision, paths)
    results: list[dict[str, Any]] = []
    for app, rel in zip(apps, paths):
        root = checkout / rel
        if not root.resolve().is_relative_to(checkout.resolve()):
            raise OfficialCatalogError("official app source escaped checkout")
        try:
            name = inventory._top_level_yaml_scalar(root / "app.yaml", "name")
            version = inventory._top_level_yaml_scalar(root / "app.yaml", "version")
            actual_train = inventory._top_level_yaml_scalar(root / "app.yaml", "train")
            if name != app or actual_train != train:
                raise OfficialCatalogError("app metadata does not match requested train/name")
            source = inventory.structural_source_contract(
                root, app_id=app, version=version, train=train
            )
        except inventory.InventoryError as exc:
            raise OfficialCatalogError("official source structural validation failed") from exc
        if source["structural_preflight"] != "PASS":
            raise OfficialCatalogError("official source preflight did not pass")
        results.append({
            "train": train, "name": app, "version": version, "path": rel,
            "source_tree_sha256": source["source_tree_sha256"],
        })
    manifest = {
        "schema": federation.SCHEMA, "publisher": "github.com",
        "source": "truenas-apps",
        "uri": pin["repository"], "revision": revision,
        "apps": sorted(results, key=lambda row: (row["train"], row["name"], row["version"])),
    }
    federation.normalize(manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--app", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        with args.pin.open("rb") as handle:
            raw = handle.read(MAX_PIN_BYTES + 1)
        if len(raw) > MAX_PIN_BYTES:
            raise OfficialCatalogError("pin file too large")
        pin = json.loads(raw.decode("utf-8"), object_pairs_hook=federation._no_duplicate_json_keys)
        manifest = project(pin, args.checkout, args.app)
    except (OSError, UnicodeError, json.JSONDecodeError, OfficialCatalogError,
            federation.CatalogIdentityError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
