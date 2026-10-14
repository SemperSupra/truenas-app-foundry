#!/usr/bin/env python3
"""Registered external TrueNAS Apps source projection (offline, read-only).

A registered HTTPS Git source at one immutable full commit is checked against
its local clean checkout; Foundry's existing native source preflight produces
the tree identity. This cannot install apps or grant trust/ownership.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
SCHEMA = "truenas-foundry-external-source/v0"
APP_ID = re.compile(r"[a-z]([-a-z0-9]*[a-z0-9])?\Z")
GH_PART = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,60}[a-z0-9])?\Z")


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


official = sibling("foundry_catalog_official_adapter")
federation = official.federation
inventory = official.inventory


class ExternalSourceError(ValueError):
    pass


def project(registration: dict, checkout: Path) -> dict:
    required = {"schema", "uri", "revision", "train", "apps"}
    if not isinstance(registration, dict) or set(registration) != required:
        raise ExternalSourceError("external source registration has unexpected fields")
    if registration["schema"] != SCHEMA:
        raise ExternalSourceError("unsupported external source registration")
    uri = federation._source_uri(registration["uri"])
    parsed = urlsplit(uri)
    if parsed.hostname != "github.com":
        raise ExternalSourceError("v0 external source supports only explicit GitHub HTTPS repos")
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if len(parts) != 2 or not all(GH_PART.fullmatch(p) for p in parts):
        raise ExternalSourceError("external repo needs unambiguous owner/repo identity")
    provider = "github.com"
    source_id = ".".join(parts)
    if not federation.SLUG.fullmatch(source_id):
        raise ExternalSourceError("external repo namespace exceeds source identity limits")
    if uri.removesuffix(".git") == "https://github.com/truenas/apps":
        raise ExternalSourceError("official source must use official adapter")
    rev = registration["revision"]
    train = registration["train"]
    apps = registration["apps"]
    if not isinstance(rev, str) or not official.SHA40.fullmatch(rev):
        raise ExternalSourceError("external source requires immutable Git SHA")
    if train not in {"community", "stable", "enterprise", "test"}:
        raise ExternalSourceError("unknown TrueNAS app train")
    if (not isinstance(apps, list) or not apps or len(apps) > official.MAX_APPS
            or not all(isinstance(a, str) and APP_ID.fullmatch(a) for a in apps)
            or len(set(apps)) != len(apps)):
        raise ExternalSourceError("external app selection is invalid or unbounded")
    # The remote URL check prevents labeling an arbitrary local checkout as a
    # different publisher. Git object IDs still bind exact content.
    expected = uri.removesuffix(".git")
    try:
        origin = official.git(checkout, "remote", "get-url", "origin").removesuffix(".git")
    except official.OfficialCatalogError as exc:
        raise ExternalSourceError("external source checkout has no verifiable remote") from exc
    if origin != expected:
        raise ExternalSourceError("external checkout Git origin does not match registration")
    paths = [f"ix-dev/{train}/{name}" for name in apps]
    official.verify_checkout(checkout, rev, paths)
    entries = []
    for name, path in zip(apps, paths):
        root = checkout / path
        if not root.resolve().is_relative_to(checkout.resolve()):
            raise ExternalSourceError("external source escaped checkout")
        try:
            version = inventory._top_level_yaml_scalar(root / "app.yaml", "version")
            source = inventory.structural_source_contract(
                root, app_id=name, version=version, train=train
            )
        except inventory.InventoryError as exc:
            raise ExternalSourceError("external source failed native catalog shape validation") from exc
        entries.append({"train": train, "name": name, "version": version,
                        "path": path, "source_tree_sha256": source["source_tree_sha256"]})
    manifest = {"schema": federation.SCHEMA, "publisher": provider,
                "source": source_id, "uri": uri, "revision": rev,
                "apps": sorted(entries, key=lambda x: (x["train"], x["name"], x["version"]))}
    federation.normalize(manifest)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.registration.open("rb") as f:
            raw = f.read(official.MAX_PIN_BYTES + 1)
        if len(raw) > official.MAX_PIN_BYTES:
            raise ExternalSourceError("registration too large")
        registration = json.loads(raw.decode("utf-8"),
                                  object_pairs_hook=federation._no_duplicate_json_keys)
        result = project(registration, args.checkout)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            official.OfficialCatalogError, federation.CatalogIdentityError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
