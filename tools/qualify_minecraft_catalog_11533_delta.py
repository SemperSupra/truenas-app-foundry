#!/usr/bin/env python3
"""Read-only, immutable upstream 1.15.31 -> 1.15.33 Minecraft App delta.

A source delta is NOT proof of TrueNAS shared-lib (2.3.17) rendered semantics,
an approved Foundry control, a native guest, or physical APPLY.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request

OLD = "95b0cc78e75fcd4b128f4ef2f8428034d981f7c2"
NEW = "0f586ab56437cd5e29bf1b16d603ec1c48bbbd4e"
OLD_VERSION, NEW_VERSION = "1.15.31", "1.15.33"
OLD_LIBRARY, NEW_LIBRARY = "2.3.16", "2.3.17"
OLD_LIB_HASH = "724ad72dada54c4b4fc478e8545dc6023d5c16a4aee09d3d5ef67f1f02c418ff"
NEW_LIB_HASH = "b02a8040f1971a601638300b595bbd5b72f0664ba13fdf7759c212867caeed24"
FILES = ("app.yaml", "questions.yaml", "ix_values.yaml",
         "templates/docker-compose.yaml", "app_migrations.yaml")
MAX_SOURCE_BYTES = 128 * 1024


def fetch(source: str, version: str, filename: str) -> bytes:
    if (source, version) not in {(OLD, OLD_VERSION), (NEW, NEW_VERSION)} or filename not in FILES:
        raise ValueError("UNPINNED_UPSTREAM_FILE")
    uri = (f"https://raw.githubusercontent.com/truenas/apps/{source}/"
           f"trains/community/minecraft/{version}/{filename}")
    req = urllib.request.Request(uri, headers={
        "User-Agent": "SupraCraft-immutable-catalog-source-delta"})
    with urllib.request.urlopen(req, timeout=25) as stream:
        body = stream.read(MAX_SOURCE_BYTES + 1)
    if not 0 < len(body) <= MAX_SOURCE_BYTES:
        raise ValueError("CATALOG_SOURCE_FILE_BOUNDS")
    return body


def scrub_app(body: bytes, version: str, lib: str, libhash: str) -> bytes:
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("INVALID_APP_ENCODING") from None
    expected = {"version": version, "lib_version": lib, "lib_version_hash": libhash}
    seen = set()
    out = []
    for line in text.splitlines(keepends=True):
        label = line.split(":", 1)[0]
        if label in expected:
            if label in seen or line.rstrip("\r\n") != f"{label}: {expected[label]}":
                raise ValueError("UPSTREAM_APP_METADATA_DRIFT")
            seen.add(label)
            out.append(f"{label}: <exact-pin>\n")
        else:
            out.append(line)
    if seen != set(expected):
        raise ValueError("UPSTREAM_APP_METADATA_INCOMPLETE")
    return "".join(out).encode("utf-8")


def compare(old: dict[str, bytes], new: dict[str, bytes]) -> dict:
    if set(old) != set(FILES) or set(new) != set(FILES):
        raise ValueError("EXACT_FILE_SET_REQUIRED")
    matched = {}
    for k in FILES:
        if type(old[k]) is not bytes or type(new[k]) is not bytes:
            raise ValueError("UNTRUSTED_FILE_BYTES")
        if not 0 < len(old[k]) <= MAX_SOURCE_BYTES or not 0 < len(new[k]) <= MAX_SOURCE_BYTES:
            raise ValueError("CATALOG_SOURCE_FILE_BOUNDS")
        matched[k] = old[k] == new[k]
    if any(not matched[k] for k in FILES if k != "app.yaml"):
        raise ValueError("UPSTREAM_RUNTIME_INPUT_OR_TEMPLATE_DRIFT")
    if (scrub_app(old["app.yaml"], OLD_VERSION, OLD_LIBRARY, OLD_LIB_HASH) !=
            scrub_app(new["app.yaml"], NEW_VERSION, NEW_LIBRARY, NEW_LIB_HASH)):
        raise ValueError("UPSTREAM_APP_UNDECLARED_DELTA")
    if old["app.yaml"] == new["app.yaml"]:
        raise ValueError("UPSTREAM_APP_VERSION_NOT_UPDATED")
    return {
        "schema": "supracraft.minecraft-native-catalog-11533-delta/1",
        "classification": "EXACT_UPSTREAM_SOURCE_DELTA_ONLY",
        "old_source": OLD, "new_source": NEW,
        "old_version": OLD_VERSION, "new_version": NEW_VERSION,
        "old_library": OLD_LIBRARY, "new_library": NEW_LIBRARY,
        "unchanged_runtime_input_and_compose_source": True,
        "changed_shared_library_requires_render_qualification": True,
        "source_files_sha256": {
            k: {"old": hashlib.sha256(old[k]).hexdigest(),
                "new": hashlib.sha256(new[k]).hexdigest()} for k in FILES
        },
        "rendered_compose_semantics_qualified": False,
        "signed_foundry_11533_control_qualified": False,
        "native_guest_catalog_verified": False,
        "backend_world_qualified": False,
        "physical_true_nas_apply": "HOLD",
        "next_gate": "FOUNDRY_SHARED_LIB_2317_EXACT_RENDER_AND_INDEPENDENT_SOURCE_CONTROL",
    }


def main() -> int:
    try:
        before = {k: fetch(OLD, OLD_VERSION, k) for k in FILES}
        after = {k: fetch(NEW, NEW_VERSION, k) for k in FILES}
        result = compare(before, after)
        code = 0
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        result = {
            "schema": "supracraft.minecraft-native-catalog-11533-delta/1",
            "classification": "REFUSED",
            "reason_type": type(error).__name__,
            "rendered_compose_semantics_qualified": False,
            "physical_true_nas_apply": "HOLD",
        }
        code = 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
