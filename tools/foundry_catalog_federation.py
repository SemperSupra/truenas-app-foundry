#!/usr/bin/env python3
"""Read-only, offline catalog-source federation identity contract (experimental v0).

No network, materialization, authentication, credential handling or TrueNAS mutation.
This is the source collision/provenance primitive for the Foundry Catalog MVP;
it is NOT a deployment authorization, image attestation or trust verdict.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "truenas-foundry-catalog-source/v0"
SLUG = re.compile(r"[a-z0-9](?:[a-z0-9_.-]{0,62}[a-z0-9])?\Z")
PUBLISHER = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\Z"
)
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,95}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
ALLOWED_TRAINS = {"test", "community", "stable", "enterprise"}
MAX_SOURCE_APPS = 4096
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_URI_LENGTH = 2048
MAX_PATH_LENGTH = 512


class CatalogIdentityError(ValueError):
    """Source catalog has ambiguous, mutable, or unsafe identity."""


def _obj(value: Any, where: str, required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise CatalogIdentityError(f"{where}: expected exactly {sorted(required)}")
    return value


def _str(value: Any, pattern: re.Pattern[str], where: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise CatalogIdentityError(f"{where}: invalid format")
    return value


def _source_uri(uri: Any) -> str:
    if not isinstance(uri, str) or len(uri) > MAX_URI_LENGTH:
        raise CatalogIdentityError("source.uri must be a bounded HTTPS URL")
    try:
        parsed = urlsplit(uri)
        # Forbid credentials, parameters, fragments, ambiguous backslashes,
        # and %-escaped ambiguity. A separate trusted fetcher controls redirects.
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port is not None
            or "\\" in uri
            or "%" in uri
            or any(c.isspace() for c in uri)
            or parsed.path.endswith("/")
            or any(segment in {".", ".."} for segment in parsed.path.split("/"))
        ):
            raise CatalogIdentityError("source.uri: untrusted or ambiguous URL")
        host = parsed.hostname
        if not host.isascii() or host.lower() != host:
            raise CatalogIdentityError("source.uri: hostname must be canonical ASCII")
    except ValueError as exc:
        raise CatalogIdentityError("source.uri: invalid URL") from exc
    return uri


def _path(path: Any, train: str, name: str) -> str:
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_LENGTH or "\\" in path or "%" in path:
        raise CatalogIdentityError("app.path: invalid path")
    parts = path.split("/")
    if any(not SLUG.fullmatch(x) or x in {".", ".."} for x in parts):
        raise CatalogIdentityError("app.path: unsafe path segment")
    if len(parts) < 2 or parts[0] != train or parts[1] != name:
        raise CatalogIdentityError("app.path: must start train/app")
    return path


def normalize(catalog: Any) -> list[dict[str, Any]]:
    """Validate a pinned provider's declarative discovery index.

    The returned rows are intentionally DISCOVERED_ONLY. Neither a successful
    validation nor a digest string authorizes source fetching or deployment.
    """
    source = _obj(
        catalog, "source",
        {"schema", "publisher", "source", "uri", "revision", "apps"},
    )
    if source["schema"] != SCHEMA:
        raise CatalogIdentityError("unsupported source schema")
    publisher = _str(source["publisher"], PUBLISHER, "publisher")
    source_id = _str(source["source"], SLUG, "source")
    revision = _str(source["revision"], SHA40, "revision")
    uri = _source_uri(source["uri"])
    if not isinstance(source["apps"], list) or len(source["apps"]) > MAX_SOURCE_APPS:
        raise CatalogIdentityError("source.apps must be a bounded array")
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(source["apps"]):
        app = _obj(
            entry, f"apps[{index}]",
            {"train", "name", "version", "path", "manifest_sha256"},
        )
        train = _str(app["train"], SLUG, "app.train")
        if train not in ALLOWED_TRAINS:
            raise CatalogIdentityError("app.train: unknown train")
        name = _str(app["name"], SLUG, "app.name")
        version = _str(app["version"], VERSION, "app.version")
        path = _path(app["path"], train, name)
        digest = _str(app["manifest_sha256"], DIGEST, "app.manifest_sha256")
        provider_id = f"{publisher}/{source_id}"
        package_id = f"{provider_id}/{train}/{name}"
        rows.append({
            "provider_id": provider_id,
            "package_id": package_id,
            "version": version,
            "source_revision": revision,
            "source_uri": uri,
            "path": path,
            "manifest_sha256": digest,
            "admission": "DISCOVERED_ONLY",
        })
    return rows


def federate(catalogs: list[Any]) -> list[dict[str, Any]]:
    """Preserve different providers; refuse conflicting duplicates from one."""
    if not isinstance(catalogs, list):
        raise CatalogIdentityError("catalogs must be an array")
    providers: dict[str, tuple[str, str]] = {}
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for catalog in catalogs:
        rows = normalize(catalog)
        # The identity of empty sources must also be protected.
        provider = f"{catalog['publisher']}/{catalog['source']}"
        origin = (catalog["uri"], catalog["revision"])
        previous_origin = providers.setdefault(provider, origin)
        if previous_origin != origin:
            raise CatalogIdentityError(f"provider {provider}: conflicting revisions/URI")
        for row in rows:
            key = (row["package_id"], row["version"])
            previous = entries.setdefault(key, row)
            if previous != row:
                raise CatalogIdentityError(
                    f"{row['package_id']}@{row['version']}: conflicting release identity"
                )
    return sorted(entries.values(), key=lambda row: (
        row["package_id"], row["version"], row["source_revision"]
    ))


def resolve(
    rows: list[dict[str, Any]], package_id: str, version: str,
    source_revision: str, manifest_sha256: str,
) -> dict[str, Any]:
    """Require exact publisher-qualified package AND immutable revision/digest."""
    matches = [
        row for row in rows
        if row["package_id"] == package_id and row["version"] == version
        and row["source_revision"] == source_revision
        and row["manifest_sha256"] == manifest_sha256
    ]
    if len(matches) != 1:
        raise CatalogIdentityError("source selection missing or ambiguous")
    return dict(matches[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="+", help="local pinned index JSON")
    args = parser.parse_args(argv)
    try:
        indexes = []
        for path in args.source:
            with path.open("rb") as handle:
                payload = handle.read(MAX_INDEX_BYTES + 1)
            if len(payload) > MAX_INDEX_BYTES:
                raise CatalogIdentityError("source index exceeds size limit")
            indexes.append(json.loads(payload.decode("utf-8")))
        rows = federate(indexes)
    except (CatalogIdentityError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"catalog federation blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": "truenas-foundry-catalog-discovery/v0", "apps": rows},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
