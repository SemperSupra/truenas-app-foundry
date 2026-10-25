#!/usr/bin/env python3
"""Materialize a normalized Document Gateway Compose target for qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import validate_document_gateway_app as dg

PROFILES = {
    "published_ipp": "basic-values.yaml",
    "host_mdns": "host-mdns-values.yaml",
    "external_lan": "external-lan-values.yaml",
    "cifs_fax": "cifs-fax-values.yaml",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(PROFILES), default="host_mdns")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--prepare-state", action="store_true")
    args = parser.parse_args()

    if args.prepare_state:
        shutil.rmtree(dg.CI_STATE, ignore_errors=True)
        for name in ("config", "spool", "documents"):
            (dg.CI_STATE / name).mkdir(parents=True, exist_ok=True)

    manifest = dg.load_json(dg.CANDIDATE)
    root = Path(tempfile.mkdtemp(prefix="foundry-document-gateway-materialize-"))
    network_created = False
    try:
        checkout = dg.checkout_upstream(root, manifest)
        app_dir = dg.install_candidate(checkout, manifest)
        if args.profile == "external_lan":
            cp = dg.run([
                "docker", "network", "create", "--subnet", "172.30.80.0/24",
                "document-gateway-ci-lan",
            ], check=False)
            network_created = cp.returncode == 0
        compose = dg.render(checkout, app_dir, PROFILES[args.profile])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(compose, indent=2, sort_keys=True) + "\n"
        args.output.write_text(payload, encoding="utf-8")
        if args.evidence:
            evidence = {
                "candidate": "document-gateway-app",
                "profile": args.profile,
                "fixture": PROFILES[args.profile],
                "compose_sha256": hashlib.sha256(
                    json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "materializer": manifest["source_materializer"],
            }
            args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    finally:
        if network_created:
            dg.run(["docker", "network", "rm", "document-gateway-ci-lan"], check=False)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
