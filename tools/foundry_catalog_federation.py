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
MAX_CATALOG_SOURCES = 128
MAX_FEDERATED_APPS = 32768
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_URI_LENGTH = 2048
MAX_PATH_LENGTH = 512


class CatalogIdentityError(ValueError):
    """Source catalog has ambiguous, mutable, or unsafe identity."""


def _no_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject JSON object-member ambiguity instead of silently using last-wins."""
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise CatalogIdentityError(f"duplicate JSON member {key!r}")
        parsed[key] = value
    return parsed


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


def _path(path: Any) -> str:
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_LENGTH or "\\" in path or "%" in path:
        raise CatalogIdentityError("app.path: invalid path")
    parts = path.split("/")
    if any(not SLUG.fullmatch(x) or x in {".", ".."} for x in parts):
        raise CatalogIdentityError("app.path: unsafe path segment")
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
            {"train", "name", "version", "path", "source_tree_sha256"},
        )
        train = _str(app["train"], SLUG, "app.train")
        if train not in ALLOWED_TRAINS:
            raise CatalogIdentityError("app.train: unknown train")
        name = _str(app["name"], SLUG, "app.name")
        version = _str(app["version"], VERSION, "app.version")
        path = _path(app["path"])
        digest = _str(app["source_tree_sha256"], DIGEST, "app.source_tree_sha256")
        provider_id = f"{publisher}/{source_id}"
        package_id = f"{provider_id}/{train}/{name}"
        rows.append({
            "provider_id": provider_id,
            "package_id": package_id,
            "version": version,
            "source_revision": revision,
            "source_uri": uri,
            "path": path,
            "source_tree_sha256": digest,
            "admission": "DISCOVERED_ONLY",
        })
    return rows


def federate(catalogs: list[Any]) -> list[dict[str, Any]]:
    """Preserve different providers; refuse conflicting duplicates from one."""
    if not isinstance(catalogs, list) or len(catalogs) > MAX_CATALOG_SOURCES:
        raise CatalogIdentityError("catalogs must be a bounded array")
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
    if len(entries) > MAX_FEDERATED_APPS:
        raise CatalogIdentityError("federated catalog exceeds total app limit")
    return sorted(entries.values(), key=lambda row: (
        row["package_id"], row["version"], row["source_revision"]
    ))


def resolve(
    rows: list[dict[str, Any]], package_id: str, version: str,
    source_revision: str, source_tree_sha256: str,
) -> dict[str, Any]:
    """Require exact publisher-qualified package AND immutable revision/digest."""
    matches = [
        row for row in rows
        if row["package_id"] == package_id and row["version"] == version
        and row["source_revision"] == source_revision
        and row["source_tree_sha256"] == source_tree_sha256
    ]
    if len(matches) != 1:
        raise CatalogIdentityError("source selection missing or ambiguous")
    return dict(matches[0])


def show(rows: list[dict[str, Any]], package_id: str) -> list[dict[str, Any]]:
    """Return all pinned versions for one exact publisher-scoped package."""
    if not isinstance(package_id, str) or not package_id:
        raise CatalogIdentityError("show requires exact package identity")
    matches = [row for row in rows if row["package_id"] == package_id]
    if not matches:
        raise CatalogIdentityError("package not found in registered sources")
    return sorted((dict(x) for x in matches), key=lambda r: (r["version"], r["source_revision"]))


def query(
    rows: list[dict[str, Any]], operation: str, *,
    package_id: str | None = None, version: str | None = None,
    revision: str | None = None, digest: str | None = None,
) -> dict[str, Any]:
    """One read-only contract for thin CLI/API/agent clients.

    Qualified source resolution is *not* target resolution or apply authorization.
    This function cannot claim installation compatibility.
    """
    if operation == "list":
        if any(x is not None for x in (package_id, version, revision, digest)):
            raise CatalogIdentityError("list does not accept selection parameters")
        return {"schema": "truenas-foundry-catalog-query/v0", "operation": "list",
                "count": len(rows), "apps": [dict(row) for row in rows]}
    if operation == "show":
        if package_id is None or any(x is not None for x in (version, revision, digest)):
            raise CatalogIdentityError("show requires only --package-id")
        matches = show(rows, package_id)
        return {"schema": "truenas-foundry-catalog-query/v0", "operation": "show",
                "count": len(matches), "apps": matches}
    if operation == "resolve":
        if not all(isinstance(x, str) and x for x in (package_id, version, revision, digest)):
            raise CatalogIdentityError(
                "resolve requires --package-id, --version, --revision, --digest"
            )
        result = resolve(rows, package_id, version, revision, digest)
        return {"schema": "truenas-foundry-catalog-query/v0", "operation": "resolve",
                "app": result, "mutation_eligible": False,
                "note": "source identity selection only; requires independent target and ownership gates"}
    raise CatalogIdentityError("unsupported read-only catalog operation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="+", help="local pinned index JSON")
    parser.add_argument("--operation", choices=("list", "show", "resolve"), default="list")
    parser.add_argument("--package-id")
    parser.add_argument("--version")
    parser.add_argument("--revision")
    parser.add_argument("--digest")
    args = parser.parse_args(argv)
    try:
        indexes = []
        for path in args.source:
            with path.open("rb") as handle:
                payload = handle.read(MAX_INDEX_BYTES + 1)
            if len(payload) > MAX_INDEX_BYTES:
                raise CatalogIdentityError("source index exceeds size limit")
            indexes.append(json.loads(payload.decode("utf-8"), object_pairs_hook=_no_duplicate_json_keys))
        rows = federate(indexes)
        result = query(rows, args.operation, package_id=args.package_id,
                       version=args.version, revision=args.revision, digest=args.digest)
    except (CatalogIdentityError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"catalog federation blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
