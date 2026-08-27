#!/usr/bin/env python3
"""Validate the public GARM appliance image against its Foundry lock/profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def fail(message: str) -> None:
    raise SystemExit(f"garm-appliance validation failed: {message}")


def run(*args: str) -> str:
    proc = subprocess.run(args, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        fail(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot load {path}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True, type=pathlib.Path)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    lock = load_json(args.lock)
    if lock.get("schema_version") != 1:
        fail("unsupported lock schema")

    controller_sha = lock.get("controller", {}).get("sha", "")
    provider_sha = lock.get("truenas_provider", {}).get("sha", "")
    if not SHA_RE.fullmatch(controller_sha):
        fail("controller SHA is not an exact 40-character lowercase commit SHA")
    if not SHA_RE.fullmatch(provider_sha):
        fail("TrueNAS provider SHA is not an exact 40-character lowercase commit SHA")

    profile_path = pathlib.Path(lock["stock_provider_artifact"]["profile"])
    stock = load_json(profile_path)
    expected_stock = sorted(stock["providers"]["expected_names"])
    expected_all = sorted(expected_stock + ["garm-provider-truenas"])

    inspect = json.loads(run("docker", "image", "inspect", args.image))[0]
    config = inspect.get("Config") or {}
    labels = config.get("Labels") or {}

    expected_labels = {
        "io.sempersupra.garm.source-revision": controller_sha,
        "io.sempersupra.garm-provider-truenas.source-revision": provider_sha,
        "org.opencontainers.image.source": "https://github.com/SemperSupra/truenas-app-foundry",
    }
    for key, expected in expected_labels.items():
        if labels.get(key) != expected:
            fail(f"label {key!r} expected {expected!r}, got {labels.get(key)!r}")

    entrypoint = config.get("Entrypoint")
    expected_entrypoint = ["/bin/garm", "-config", "/etc/garm/config.toml"]
    if entrypoint != expected_entrypoint:
        fail(f"unexpected entrypoint: {entrypoint!r}")

    if config.get("Volumes") not in (None, {}):
        fail(f"runtime image must not declare Docker volumes: {config.get('Volumes')!r}")

    run(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "/bin/sh",
        args.image,
        "-ec",
        "test -x /bin/garm; test -x /bin/garm-cli; "
        "test -x /opt/garm/providers.d/garm-provider-truenas",
    )

    providers = run(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "/bin/sh",
        args.image,
        "-ec",
        "for f in /opt/garm/providers.d/*; do basename \"$f\"; done | sort",
    ).splitlines()
    if providers != expected_all:
        fail(f"provider inventory drift: expected {expected_all!r}, got {providers!r}")

    # During the MVP the eight stock providers are copied from one immutable upstream
    # artifact. Verify assembly integrity, but do not turn these hashes into a permanent
    # product requirement: the lock explicitly allows later source-pinned replacements.
    expected_hashes = stock["providers"]["sha256"]
    for name in expected_stock:
        actual_line = run(
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            args.image,
            "-ec",
            f"sha256sum /opt/garm/providers.d/{name}",
        )
        actual = actual_line.split()[0]
        expected = expected_hashes[name]
        if actual != expected:
            fail(f"stock provider {name} hash drift: expected {expected}, got {actual}")

    # Print useful public evidence without dumping environment or config/secrets.
    truenas_hash = run(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "/bin/sh",
        args.image,
        "-ec",
        "sha256sum /opt/garm/providers.d/garm-provider-truenas",
    ).split()[0]
    garm_hash = run(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "/bin/sh",
        args.image,
        "-ec",
        "sha256sum /bin/garm",
    ).split()[0]

    print("GARM appliance validation: PASS")
    print(f"controller_source={controller_sha}")
    print(f"truenas_provider_source={provider_sha}")
    print(f"controller_binary_sha256={garm_hash}")
    print(f"truenas_provider_binary_sha256={truenas_hash}")
    print("providers=" + ",".join(providers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
