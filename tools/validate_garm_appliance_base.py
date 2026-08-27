#!/usr/bin/env python3
"""Validate a pinned upstream GARM image/provider-bundle profile.

The workflow copies /opt/garm/providers.d from the selected image into a host
folder, then this validator records and (once pinned) verifies the exact bundle.
It deliberately does not execute GARM or any provider binary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--provider-dir", required=True)
    parser.add_argument("--resolved-image", required=True,
                        help="immutable image reference, repository@sha256:...")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    profile_path = Path(args.profile)
    provider_dir = Path(args.provider_dir)
    evidence_path = Path(args.evidence)

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("schema_version") != 1:
        fail("unsupported profile schema_version")

    image = profile.get("image", {})
    image_ref = image.get("reference")
    if not isinstance(image_ref, str) or not image_ref:
        fail("profile image.reference is missing")

    resolved = args.resolved_image.strip()
    if "@" not in resolved:
        fail("resolved image must be repository@sha256:...")
    resolved_repo, resolved_digest = resolved.rsplit("@", 1)
    if not DIGEST_RE.match(resolved_digest):
        fail(f"resolved image digest is malformed: {resolved_digest!r}")

    expected_repo = image_ref.split(":", 1)[0]
    if resolved_repo != expected_repo:
        fail(f"resolved repository mismatch: {resolved_repo!r} != {expected_repo!r}")

    if not provider_dir.is_dir():
        fail(f"provider directory does not exist: {provider_dir}")

    entries = sorted(p for p in provider_dir.iterdir() if p.is_file())
    observed_names = [p.name for p in entries]
    observed_hashes = {p.name: sha256_file(p) for p in entries}

    providers = profile.get("providers", {})
    expected_names = providers.get("expected_names")
    if not isinstance(expected_names, list) or not all(isinstance(x, str) for x in expected_names):
        fail("providers.expected_names must be a list of strings")
    expected_names = sorted(expected_names)

    if observed_names != expected_names:
        fail(
            "provider filename set mismatch: "
            f"observed={observed_names!r} expected={expected_names!r}"
        )

    pinned_digest = image.get("digest")
    pinned_hashes = providers.get("sha256", {})
    discovery = pinned_digest is None or pinned_hashes == {}

    if not discovery:
        if not isinstance(pinned_digest, str) or not DIGEST_RE.match(pinned_digest):
            fail("profile image.digest is not a sha256 digest")
        if pinned_digest != resolved_digest:
            fail(f"image digest drift: observed={resolved_digest} expected={pinned_digest}")
        if set(pinned_hashes) != set(expected_names):
            fail("pinned provider hash keys do not exactly match expected_names")
        for name in expected_names:
            expected_hash = pinned_hashes[name]
            observed_hash = observed_hashes[name]
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash or ""):
                fail(f"invalid pinned hash for {name}")
            if expected_hash != observed_hash:
                fail(
                    f"provider byte drift for {name}: "
                    f"observed={observed_hash} expected={expected_hash}"
                )

    evidence = {
        "schema_version": 1,
        "status": "DISCOVERY" if discovery else "PASS",
        "source": profile.get("source"),
        "image": {
            "configured_reference": image_ref,
            "platform": image.get("platform"),
            "resolved_repository": resolved_repo,
            "resolved_digest": resolved_digest,
            "immutable_reference": resolved,
        },
        "providers": {
            "count": len(observed_names),
            "names": observed_names,
            "sha256": observed_hashes,
        },
        "known_upstream_seams": profile.get("known_upstream_seams", []),
        "claim_boundary": profile.get("claim_boundary"),
    }
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
