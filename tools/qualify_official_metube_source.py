#!/usr/bin/env python3
"""One-shot qualification of the EXISTING official TrueNAS MeTube source, not a new app.

Reuse Foundry's exact upstream source renderer and normalized security helpers.
No TrueNAS host connection, secret, external catalog registration, or mutation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

from validate_truenas_materialization import (
    PIN_FILE, assert_library_security, canonical_sha256,
    checkout_upstream, fingerprint, has_docker_socket, mounts,
    normalize_rendered, service,
)

OFFICIAL = {
    "repository": "https://github.com/truenas/apps.git",
    "ref": "f142a16a1e15da5f8517658f5a9ad34400972fc4",
    "train": "community",
    "library_version": "2.3.18",
    "library_hash": "ed9839f681342ae8ca5f8c4c860ae22d0845a0919f472ba780d6edbc838f2633",
}
CONTROL = {"app": "metube", "test_file": "basic-values.yaml", "primary_service": "metube"}
IMAGE = "ghcr.io/alexta69/metube:2026.11.06@sha256:96dfbf0d5b2944e4ee38f6ce1b34bb0e75a1a3c74eaefd93424ed11284cb72b2"


def require_metube(compose: dict) -> dict:
    primary = service(compose, "metube")
    assert_library_security("official-community/metube", primary)
    if primary.get("image") != IMAGE:
        raise ValueError("image digest is not the exact official catalog release")
    if str(primary.get("user")) != "568:568":
        raise ValueError("nonroot official 568:568 identity was not retained")
    if primary.get("network_mode") == "host":
        raise ValueError("host networking violates default isolated app")
    if has_docker_socket(primary):
        raise ValueError("unexpected Docker socket")
    env = primary.get("environment") or {}
    if env.get("DOWNLOAD_DIR") != "/downloads" or env.get("STATE_DIR") != "/downloads/.metube":
        raise ValueError("persistent downloads and state location changed")
    if not any(m.get("target") == "/downloads" for m in mounts(primary)):
        raise ValueError("downloads storage not mounted")
    if not primary.get("ports"):
        raise ValueError("official UI port not exposed to trusted operator")
    for m in mounts(primary):
        if m["type"] == "bind" and not str(m["source"]).startswith("/opt/tests/mnt/"):
            raise ValueError("unexpected host bind path in a public-safe test fixture")
    return primary


def negative_controls(compose: dict) -> list[str]:
    # Must reject every intentional violation of the accepted official source.
    controls = [
        ("privileged", lambda p: p.update(privileged=True)),
        ("root-user", lambda p: p.update(user="0:0")),
        ("mutable-image", lambda p: p.update(image="ghcr.io/alexta69/metube:latest")),
        ("host-network", lambda p: p.update(network_mode="host")),
        ("state-dir", lambda p: p["environment"].update(STATE_DIR="/tmp/.metube")),
        ("absent-downloads", lambda p: p.update(volumes=[])),
    ]
    passed = []
    for name, mutation in controls:
        altered = copy.deepcopy(compose)
        mutation(service(altered, "metube"))
        try:
            require_metube(altered)
        except (ValueError, RuntimeError):
            passed.append(name)
        else:
            raise AssertionError(f"malicious fixture {name} escaped the guard")
    return passed


def main() -> None:
    baseline = PIN_FILE.read_bytes()
    baseline_sha = hashlib.sha256(baseline).hexdigest()
    current_global = json.loads(baseline)
    if current_global["ref"] == OFFICIAL["ref"]:
        raise AssertionError("unexpected global-pinned ref changed; source guard must stay independent")
    if current_global["library_version"] != "2.3.4":
        raise AssertionError("Foundry baseline changed; reconcile separately, don't mutate here")
    with tempfile.TemporaryDirectory(prefix="foundry-official-metube-") as td:
        checkout = checkout_upstream(Path(td), OFFICIAL)
        compose = normalize_rendered(checkout, OFFICIAL, CONTROL)
        primary = require_metube(compose)
        negatives = negative_controls(compose)
        proof = {
            "schema": "foundry.official_app_render_qualification.v1",
            "app": "community/metube",
            "source_ref": OFFICIAL["ref"],
            "library_version": OFFICIAL["library_version"],
            "library_hash": OFFICIAL["library_hash"],
            "image": primary["image"],
            "normalized_compose_sha256": canonical_sha256(compose),
            "source_security": fingerprint(compose, "metube"),
            "six_negative_controls": negatives,
            "global_pin_sha256": baseline_sha,
            "source_render": "PASS",
            "target_trueNAS_hil": "NOT_RUN",
            "foundry_f2_f5_native_lifecycle": "NOT_RUN",
            "publication": "EXISTING_OFFICIAL_COMMUNITY_CATALOG",
            "new_package": False,
        }
        Path("evidence-metube-official.json").write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")
        print("OFFICIAL_METUBE_FOUNDRY_SOURCE_RENDER=PASS", proof["normalized_compose_sha256"])
    if hashlib.sha256(PIN_FILE.read_bytes()).hexdigest() != baseline_sha:
        raise AssertionError("Foundry baseline source pin was changed")


if __name__ == "__main__":
    main()
