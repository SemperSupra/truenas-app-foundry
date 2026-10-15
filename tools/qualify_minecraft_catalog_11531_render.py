#!/usr/bin/env python3
"""Two exact upstream renderings; fail closed on any Compose semantic drift.

Calls the real ix-dev renderer in two immutable upstream checkouts and Docker
Compose canonicalizer; no TrueNAS guest, App, credentials, local site or APPLY.
"""
from __future__ import annotations

import json
import sys

try:
    from tools.validate_minecraft_world_control import (
        VANILLA_PIN, VANILLA_11531_PIN, VANILLA_VALUES, validate, ValidationError)
except ModuleNotFoundError:
    from validate_minecraft_world_control import (
        VANILLA_PIN, VANILLA_11531_PIN, VANILLA_VALUES, validate, ValidationError)

OLD = "559b9fe85212c800bc6770f152a65211df137a44"
NEW = "95b0cc78e75fcd4b128f4ef2f8428034d981f7c2"
IMAGE = ("ghcr.io/itzg/minecraft-server:2026.10.0-java25@sha256:"
         "5a2ab74ae179c11e2dbbce67f307cdcf2c1257b3abb0f654d3a310b3d8ea57da")
WORLD = "/opt/tests/collage-vanilla-263-world"
OWNER = {
    "SUPRACRAFT_COLLAGE_MANAGED": "true",
    "SUPRACRAFT_COLLAGE_SCHEMA": "1",
    "SUPRACRAFT_COLLAGE_MANAGER_ID": "manager-rdte",
    "SUPRACRAFT_COLLAGE_FLEET_ID": "rdte",
    "SUPRACRAFT_COLLAGE_SERVICE_ID": "11111111-1111-4111-8111-111111111111",
    "SUPRACRAFT_COLLAGE_WORLD_ID": "lantern-rdte",
}
SCHEMA = "supracraft.minecraft-vanilla263-native-11531-render-parity/1"


def evaluate(old: dict, new: dict) -> dict:
    if type(old) is not dict or type(new) is not dict:
        raise ValueError("RENDER_INPUT_MISSING")
    if old.get("result") != "PASS" or new.get("result") != "PASS":
        raise ValueError("RENDER_SOURCE_NOT_ACCEPTED")
    if old.get("upstream", {}).get("ref") != OLD or new.get("upstream", {}).get("ref") != NEW:
        raise ValueError("UPSTREAM_EXACT_REF_DRIFT")
    if old.get("upstream", {}).get("library_version") != "2.3.4" or new.get("upstream", {}).get("library_version") != "2.3.16":
        raise ValueError("SHARED_LIBRARY_PIN_DRIFT")
    if old.get("server", {}).get("catalog_version") != "1.15.30" or new.get("server", {}).get("catalog_version") != "1.15.31":
        raise ValueError("CATALOG_SOURCE_PIN_DRIFT")
    for o in (old, new):
        srv = o["server"]
        if (srv.get("type") != "VANILLA" or srv.get("minecraft_version") != "26.3" or
            srv.get("image_selector") != "j25_image" or srv.get("image_ref") != IMAGE or
            srv.get("ownership_metadata") != OWNER or
            srv.get("world_mount") != {"source": WORLD, "target": "/data/world", "read_only": False} or
            srv.get("base_data_mount", {}).get("source") == WORLD or
            o.get("runtime_qualification") is not False or
            o.get("truenas_target") != "25.04.2.6"):
            raise ValueError("NATIVE_RENDER_OWNERSHIP_IMAGE_OR_WORLD_DRIFT")
    prior = dict(old["server"])
    next_version = dict(new["server"])
    prior.pop("catalog_version")
    next_version.pop("catalog_version")
    if prior != next_version:
        raise ValueError("SERVER_RUNTIME_PROJECTION_DRIFT")
    if old.get("platform_normalization") != new.get("platform_normalization"):
        raise ValueError("PLATFORM_NORMALIZATION_ACTION_DRIFT")
    digest = old.get("compose_sha256")
    if (type(digest) is not str or len(digest) != 64 or
            digest != new.get("compose_sha256")):
        raise ValueError("RENDERED_COMPOSE_CANONICAL_SHA_DRIFT")
    return {
        "schema": SCHEMA,
        "classification": "SOURCE_RENDER_CANONICAL_COMPOSE_IDENTICAL",
        "old_catalog": "1.15.30",
        "new_catalog": "1.15.31",
        "old_source": OLD, "new_source": NEW,
        "old_library": "2.3.4", "new_library": "2.3.16",
        "canonical_render_sha256": digest,
        "same_java25_image_digest": True,
        "same_native_world_mount": True,
        "same_six_ownership_markers": True,
        "same_platform_resolution_and_actions": True,
        "runtime_guest_qualified": False,
        "signed_foundry_consumer_updated": False,
        "native_backend_world_qualified": False,
        "physical_truenas_apply": "HOLD",
        "next_gate": "VERSIONED_FOUNDRY_11531_SIGNED_EXPORT_AND_INDEPENDENT_CONSUMER",
    }


def actual_render(pin) -> dict:
    x = validate(pin_path=pin, values_path=VANILLA_VALUES,
                 expected_type="VANILLA", expected_version="26.3",
                 expected_selector="j25_image", expected_world_path=WORLD,
                 expected_ownership=OWNER)
    x["runtime_qualification"] = False
    x["truenas_target"] = "25.04.2.6"
    return x


def main() -> int:
    try:
        old = actual_render(VANILLA_PIN)
        new = actual_render(VANILLA_11531_PIN)
        r = evaluate(old, new)
        status = 0
    except (ValidationError, ValueError, OSError, KeyError, TypeError) as error:
        r = {"schema": SCHEMA, "classification": "REFUSED",
             "failure_type": type(error).__name__,
             "canonical_render_semantics_qualified": False,
             "physical_truenas_apply": "HOLD"}
        status = 2
    print(json.dumps(r, sort_keys=True))
    return status


if __name__ == "__main__":
    sys.exit(main())
