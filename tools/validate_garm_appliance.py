#!/usr/bin/env python3
"""Validate the public GARM appliance image against its Foundry lock/profile."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_REF_RE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
DUMMY_CONTROLLER_CONFIG = """[default]
enable_webhook_management = true

[logging]
log_level = "info"

[metrics]
disable_auth = false

[jwt_auth]
secret = "N4vR8xK2mQ7pL5sD9wF3cH6yT1jB0zUa"
time_to_live = "8760h"

[apiserver]
bind = "0.0.0.0"
port = 8080
use_tls = false

[apiserver.webui]
enable = true

[database]
backend = "sqlite3"
passphrase = "Y7cD2mQ9vK4sR8pL1xF6nH3wT5jB0zUa"

[database.sqlite3]
db_file = "/etc/garm/garm.db"
"""


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


def controller_smoke(image: str) -> None:
    """Prove the image entrypoint can boot the qualified controller and serve /ui/."""
    suffix = f"{os.getpid()}-{int(time.time())}"
    volume = f"foundry-garm-appliance-smoke-{suffix}"
    name = f"foundry-garm-appliance-smoke-{suffix}"
    try:
        run("docker", "volume", "create", volume)
        run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--entrypoint",
            "/bin/sh",
            "--env",
            f"GARM_BOOTSTRAP_CONFIG={DUMMY_CONTROLLER_CONFIG}",
            "-v",
            f"{volume}:/etc/garm",
            image,
            "-ec",
            'umask 077; printf "%s" "$GARM_BOOTSTRAP_CONFIG" > /etc/garm/config.toml; test -s /etc/garm/config.toml',
        )
        run(
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--user",
            "0:0",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "-v",
            f"{volume}:/etc/garm",
            image,
        )

        deadline = time.time() + 30
        last_probe = ""
        while time.time() < deadline:
            status_proc = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", name],
                check=False,
                text=True,
                capture_output=True,
            )
            status = status_proc.stdout.strip()
            if status != "running":
                logs = subprocess.run(
                    ["docker", "logs", "--tail", "120", name],
                    check=False,
                    text=True,
                    capture_output=True,
                )
                detail = (logs.stdout + logs.stderr)[-5000:]
                fail(f"controller exited before /ui/ became ready: status={status!r}\n{detail}")

            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "wget",
                    "--quiet",
                    "-O",
                    "/dev/null",
                    "http://127.0.0.1:8080/ui/",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            if probe.returncode == 0:
                return
            last_probe = (probe.stderr or probe.stdout or "")[-1000:]
            time.sleep(1)

        logs = subprocess.run(
            ["docker", "logs", "--tail", "120", name],
            check=False,
            text=True,
            capture_output=True,
        )
        detail = (logs.stdout + logs.stderr)[-5000:]
        fail(f"controller /ui/ did not become ready: {last_probe}\n{detail}")
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            check=False,
            text=True,
            capture_output=True,
        )
        subprocess.run(
            ["docker", "volume", "rm", "-f", volume],
            check=False,
            text=True,
            capture_output=True,
        )


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

    for builder_name in ("node", "golang"):
        builder_ref = (lock.get("build_images") or {}).get(builder_name, "")
        if not DIGEST_REF_RE.fullmatch(builder_ref):
            fail(f"build image {builder_name!r} must be pinned by sha256 digest")

    stock_ref = (lock.get("stock_provider_artifact") or {}).get("reference", "")
    if not DIGEST_REF_RE.fullmatch(stock_ref):
        fail("stock provider artifact must be pinned by sha256 digest")

    expected_binaries = lock.get("expected_binaries") or {}
    expected_truenas_hash = expected_binaries.get("garm_provider_truenas_sha256", "")
    if not SHA256_RE.fullmatch(expected_truenas_hash):
        fail("expected TrueNAS provider binary SHA-256 is missing or invalid")

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
    expected_entrypoint = ["/bin/garm", "--config", "/etc/garm/config.toml"]
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

    if truenas_hash != expected_truenas_hash:
        fail(
            "TrueNAS provider binary is not reproducible: "
            f"expected {expected_truenas_hash}, got {truenas_hash}"
        )

    controller_smoke(args.image)

    print("GARM appliance validation: PASS")
    print(f"controller_source={controller_sha}")
    print(f"truenas_provider_source={provider_sha}")
    print(f"controller_binary_sha256={garm_hash}")
    print("controller_binary_reproduction=DEFERRED_FOUNDARY_18")
    print(f"truenas_provider_binary_sha256={truenas_hash}")
    print("truenas_provider_binary_reproduction=PASS")
    print("controller_smoke=PASS:wget http://127.0.0.1:8080/ui/")
    print("providers=" + ",".join(providers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
