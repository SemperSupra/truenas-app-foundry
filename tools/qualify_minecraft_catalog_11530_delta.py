#!/usr/bin/env python3
"""Exact-source comparison of two public upstream TrueNAS Minecraft catalog versions.

This is an immutable, public SOURCE DELTA oracle only, not a Foundry export or a
Minecraft/TrueNAS runtime result. It preserves the earlier 1.15.29 acceptance.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request

OLD = "bb96ef6fd8c2708765012a4a3ca3739370a4f92c"
NEW = "559b9fe85212c800bc6770f152a65211df137a44"
OLD_VER = "1.15.29"
NEW_VER = "1.15.30"
OLD_IMAGE = "2026.9.2-java21@sha256:edf50d431ddc6f73929368e82f4334a405796874f7b0ae11f1edcbb267d670aa"
NEW_IMAGE = "2026.10.0-java21@sha256:d4057e7019e9b19f25e039d4a204cc502e1a112d1a2305966a534f3d7079e644"
FILES = ("questions.yaml", "templates/docker-compose.yaml", "app.yaml", "ix_values.yaml")
MAX_SOURCE_BYTES = 128 * 1024


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(commit: str, version: str, name: str) -> bytes:
    url = f"https://raw.githubusercontent.com/truenas/apps/{commit}/trains/community/minecraft/{version}/{name}"
    req = urllib.request.Request(url, headers={"User-Agent": "SupraCraft-pinned-catalog-source-delta"})
    with urllib.request.urlopen(req, timeout=25) as stream:
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if not 0 < len(data) <= MAX_SOURCE_BYTES:
        raise ValueError("catalog file size invalid")
    return data


def compare(old: dict[str, bytes], new: dict[str, bytes]) -> dict:
    if set(old) != set(FILES) or set(new) != set(FILES):
        raise ValueError("exact required upstream source set missing")
    if old["questions.yaml"] != new["questions.yaml"]:
        raise ValueError("questions schema changed; independently qualify")
    if old["templates/docker-compose.yaml"] != new["templates/docker-compose.yaml"]:
        raise ValueError("native Compose template changed; independently qualify")
    old_app, new_app = old["app.yaml"].decode(), new["app.yaml"].decode()
    old_values, new_values = old["ix_values.yaml"].decode(), new["ix_values.yaml"].decode()
    for app, ver in ((old_app, "2026.9.2-java21"),
                     (new_app, "2026.10.0-java21")):
        if f"app_version: {ver}\n" not in app or "lib_version: 2.3.4\n" not in app:
            raise ValueError("unexpected library or image application identity")
    for values, image in ((old_values, OLD_IMAGE), (new_values, NEW_IMAGE)):
        if f'tag: "{image}"' not in values or (
                "repository: ghcr.io/itzg/minecraft-server" not in values):
            raise ValueError("default OCI image pin drift")
    return {
        "schema": "supracraft.minecraft-paper-catalog-source-delta/1",
        "classification": "SOURCE_DELTA_OBSERVED",
        "old_ref": OLD, "new_ref": NEW,
        "old_catalog_version": OLD_VER, "new_catalog_version": NEW_VER,
        "old_default_image": "ghcr.io/itzg/minecraft-server:" + OLD_IMAGE,
        "new_default_image": "ghcr.io/itzg/minecraft-server:" + NEW_IMAGE,
        "questions_bytes_identical": True,
        "compose_template_bytes_identical": True,
        "file_sha256": {name: {"old": sha(old[name]), "new": sha(new[name])}
                        for name in FILES},
        "image_digest_changed": True,
        "source_and_image_qualified_for_new_runtime": False,
        "guest_catalog_verified": False,
        "native_app_materialized": False,
        "paper_gameplay_verified": False,
        "cloudnet_adoption_verified": False,
        "physical_site_mutated": False,
        "next": "EXACT_FOUNDRY_11530_SOURCE_RENDER_AND_NEW_DISPOSABLE_NATIVE_APP_QUALIFICATION",
    }


def main() -> int:
    try:
        old = {name: fetch(OLD, OLD_VER, name) for name in FILES}
        new = {name: fetch(NEW, NEW_VER, name) for name in FILES}
        receipt = compare(old, new)
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"schema": "supracraft.minecraft-paper-catalog-source-delta/1",
                          "classification": "REFUSED", "reason_type": type(exc).__name__,
                          "runtime_qualified": False}, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
