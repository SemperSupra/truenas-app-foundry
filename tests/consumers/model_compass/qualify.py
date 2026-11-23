#!/usr/bin/env python3
"""Source-bound TrueNAS Foundry consumer rehearsal, no target network or secrets.

SemperSupra/truenas-app-foundry-private#355 owns the private site admission.
This script uses existing Foundry generic packaging rather than a new actuator.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
FOUNDRY = HERE.parents[2]
sys.path.insert(0, str(FOUNDRY / "tools"))
from package_truenas_deployment_artifact import build_artifact  # noqa: E402

PRODUCT = "https://github.com/SemperSupra/model-spelunker.git"
PIN = "ae355f38e51a97bc47428778079f58130735c221"
DIGEST_A = "sha256:" + "a" * 64  # synthetic, NEVER a claimed product OCI digest
DIGEST_B = "sha256:" + "b" * 64
APP_NAME = "model-compass"


def run(args: list[str], cwd: pathlib.Path, env: dict[str, str] | None = None) -> str:
    cp = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=180)
    if cp.returncode:
        raise RuntimeError("public source/render failure: " + (cp.stderr or cp.stdout)[-1000:])
    return cp.stdout.strip()


def checkout_source(root: pathlib.Path, sha: str) -> pathlib.Path:
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("source ref must be an exact commit SHA")
    p = root / "model-spelunker"
    run(["git", "init", "-q", str(p)], root)
    run(["git", "-C", str(p), "remote", "add", "origin", PRODUCT], root)
    run(["git", "-C", str(p), "fetch", "--no-tags", "--depth=1", "origin", sha], root)
    actual = run(["git", "-C", str(p), "rev-parse", "FETCH_HEAD"], root)
    if actual != sha:
        raise RuntimeError("untrusted source checkout/ref drift")
    run(["git", "-C", str(p), "checkout", "-q", "--detach", sha], root)
    return p


def render(source: pathlib.Path, root: pathlib.Path, digest: str) -> dict:
    app = source / "deploy" / "model-compass"
    compose = app / "truenas-compose.yaml"
    verifier = app / "verify_compose.py"
    if not compose.is_file() or not verifier.is_file():
        raise RuntimeError("source-bound app artifact missing")
    env = os.environ.copy()
    env.update({
        "MODEL_COMPASS_IMAGE": "ghcr.io/synthetic/model-compass@" + digest,
        "MODEL_COMPASS_PORT": "18088",
        "MODEL_COMPASS_STATE_DIR": "/tmp/synthetic-zfs-owned-state",
        "MODEL_COMPASS_TOKEN_FILE": "/tmp/synthetic-token-mode-0400",
    })
    raw = run(["docker", "compose", "-f", str(compose), "config", "--format", "json"], root, env)
    data = json.loads(raw)
    if data.get("services") is None:
        raise RuntimeError("no normalized compose services")
    rendered = root / "normalized.json"
    rendered.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    run([sys.executable, str(verifier), str(rendered)], root)
    return data


def verify(source: pathlib.Path, root: pathlib.Path, sha: str) -> dict:
    original = render(source, root, DIGEST_A)
    provenance = {"product_repo": "SemperSupra/model-spelunker", "product_source_commit": sha,
                  "qualification_stage": "public-source-only", "oci_image": "synthetic-not-published"}
    first = build_artifact(APP_NAME, original, provenance)
    duplicate = build_artifact(APP_NAME, copy.deepcopy(original), provenance)
    if first != duplicate:
        raise RuntimeError("identical source/IR produced non-deterministic materialization identity")
    if first.get("schema") != "truenas-foundry-deployment-artifact/v1":
        raise RuntimeError("not the existing generic Foundry deployment schema")
    if first.get("create_payload", {}).get("custom_app") is not True:
        raise RuntimeError("native Custom App source path lost")
    if first["create_payload"]["custom_compose_config"] != original:
        raise RuntimeError("normalized IR altered during packaging")
    if first["create_payload"]["custom_compose_config"]["services"][APP_NAME]["read_only"] is not True:
        raise RuntimeError("stateless rootfs not preserved")
    updated = render(source, root, DIGEST_B)
    replaced = build_artifact(APP_NAME, updated, provenance)
    if replaced["materialization_identity"] == first["materialization_identity"]:
        raise RuntimeError("OCI immutable image digest change did not invalidate artifact")
    # Deliberately use the product's public source validator. No duplicate
    # private or application-specific lifecycle executor is created here.
    validator_file = source / "deploy" / "model-compass" / "verify_compose.py"
    spec = importlib.util.spec_from_file_location("compass_source_validator", validator_file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for variant, poison in [
        ("foreign_privileged", lambda a: a["services"][APP_NAME].update(privileged=True)),
        ("unbound_port", lambda a: a["services"][APP_NAME]["ports"][0].update(host_ip="0.0.0.0")),
        ("writable_state", lambda a: a["services"][APP_NAME]["volumes"][0].update(read_only=False)),
        ("docker_socket", lambda a: a["services"][APP_NAME]["volumes"].append(
            {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock", "read_only": False})),
    ]:
        mutated = copy.deepcopy(original)
        poison(mutated)
        try:
            module.verify(mutated)
        except SystemExit as exc:
            if not str(exc).startswith("REFUSE:"):
                raise RuntimeError("unexpected negative result for " + variant) from exc
        else:
            raise RuntimeError("malicious Compose variant accepted: " + variant)
    return {
        "status": "PASS",
        "profile": "public-Foundry-F0-F1-source-only",
        "product_source_sha": sha,
        "artifact_schema": first["schema"],
        "materialization_identity": first["materialization_identity"],
        "image_digest_change": "DIFFERENT",
        "repeated_plan": "IDENTICAL",
        "negative_oracles": 4,
        "F2_through_F6": "NOT_RUN",
        "actual_oci_image": "NOT_PUBLISHED",
        "truenas_hil": "NOT_RUN",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product-sha", default=PIN)
    args = ap.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="foundry-compass-") as tmp:
            root = pathlib.Path(tmp)
            source = checkout_source(root, args.product_sha)
            result = verify(source, root, args.product_sha)
            print(json.dumps(result, sort_keys=True))
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
