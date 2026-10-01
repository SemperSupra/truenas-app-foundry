#!/usr/bin/env python3
"""Patch the pinned TrueNAS Apps ci.py to use one prebuilt exact validator image."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path


EXPECTED_IMAGE_LINE = 'CONTAINER_IMAGE = "ghcr.io/truenas/apps_validation:latest"'
EXPECTED_PULL_FUNCTION = '''def pull_app_catalog_container():
    print_stderr(f"Pulling container image [{CONTAINER_IMAGE}]")
    res = subprocess.run(
        f"docker pull --platform {PLATFORM} --quiet {CONTAINER_IMAGE}",
        shell=True,
        capture_output=True,
    )
    if res.returncode != 0:
        print_stderr(f"Failed to pull container image [{CONTAINER_IMAGE}]")
        sys.exit(1)
    print_stderr(f"Done pulling container image [{CONTAINER_IMAGE}]")
'''
IMAGE_RE = re.compile(r"^foundry/apps-validation:[0-9a-f]{12,40}$")


class PatchError(RuntimeError):
    pass


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def patch_ci(source: str, image: str) -> str:
    if not IMAGE_RE.fullmatch(image):
        raise PatchError("image must be a local foundry/apps-validation tag derived from an exact commit")
    if source.count(EXPECTED_IMAGE_LINE) != 1:
        raise PatchError("upstream ci.py validator image constant drifted")
    if source.count(EXPECTED_PULL_FUNCTION) != 1:
        raise PatchError("upstream ci.py pull_app_catalog_container implementation drifted")

    replacement_line = f'CONTAINER_IMAGE = "{image}"'
    replacement_function = '''def pull_app_catalog_container():
    print_stderr(f"Using prebuilt exact container image [{CONTAINER_IMAGE}]")
    res = subprocess.run(
        ["docker", "image", "inspect", CONTAINER_IMAGE],
        capture_output=True,
    )
    if res.returncode != 0:
        print_stderr(f"Exact prebuilt container image is missing [{CONTAINER_IMAGE}]")
        sys.exit(1)
    print_stderr(f"Found exact prebuilt container image [{CONTAINER_IMAGE}]")
'''
    patched = source.replace(EXPECTED_IMAGE_LINE, replacement_line, 1)
    patched = patched.replace(EXPECTED_PULL_FUNCTION, replacement_function, 1)
    if "ghcr.io/truenas/apps_validation:latest" in patched:
        raise PatchError("floating validator image remained after patch")
    if "docker pull --platform" in patched:
        raise PatchError("validator pull path remained after patch")
    return patched


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--image", required=True)
    args = p.parse_args()
    try:
        source = args.input.read_text(encoding="utf-8")
        patched = patch_ci(source, args.image)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(patched, encoding="utf-8")
        print(
            f"source_sha256={sha256_text(source)}\n"
            f"patched_sha256={sha256_text(patched)}\n"
            f"image={args.image}"
        )
        return 0
    except (OSError, PatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
