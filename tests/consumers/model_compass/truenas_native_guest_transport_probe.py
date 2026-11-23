#!/usr/bin/env python3
"""F6-PRE: isolated native TrueNAS 25.04.2.6 registry-to-image-pull probe.

Only this disposable QEMU guest may receive changes. Test an exact-source
Model-Compass image without GHCR publication or TrueNAS Docker daemon patches.
This is a transport gate and NEVER a claim of installed model-compass F2-F6.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from truenas_middleware_ddp_probe import WebSocket, ddp_call, wait_for

HERE = pathlib.Path(__file__).resolve()
REPO_ROOT = pathlib.Path(os.environ["FOUNDRY_SOURCE_ROOT"]).resolve(strict=True)
sys.path.insert(0, str(REPO_ROOT / "tests" / "consumers" / "model_compass"))
from native_guest_registry import (  # noqa: E402
    GUEST_PORT,
    HOST_PORT,
    PRODUCT_SOURCE_SHA,
    REGISTRY_APP_NAME,
    REGISTRY_REF,
    TARGET,
    verify_plan_contract,
)

EXPECTED_SYSTEM = "TrueNAS-" + TARGET
EXPECTED_REGISTRY_DIGEST = REGISTRY_REF.split("@", 1)[1]
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def run(command: list[str], *, cwd: pathlib.Path | None = None, timeout: int = 360) -> str:
    result = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        # No need to expose stderr or authentication/probe transport details.
        raise RuntimeError(f"bounded public source command failed: {command[0]} (exit={result.returncode})")
    return result.stdout.strip()


def read_plan(path: pathlib.Path) -> dict:
    require(path.is_file() and path.stat().st_size < 32768, "missing/oversized exact guest plan")
    p = json.loads(path.read_text(encoding="utf-8"))
    verify_plan_contract(p)
    require(p["product_source_commit"] == PRODUCT_SOURCE_SHA, "product source identity changed")
    require(p["target_version"] == TARGET and p["native_F2_F6"] == "NOT_RUN", "guest target/acceptance drift")
    require(p["guest_registry_native_app"] == REGISTRY_APP_NAME, "registry app identity drift")
    require(p["registry_source_digest"] == EXPECTED_REGISTRY_DIGEST, "registry OCI source drift")
    return p


def require(test: bool, message: str) -> None:
    if not test:
        raise RuntimeError(message)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--password-file", type=pathlib.Path, required=True)
    ap.add_argument("--plan-file", type=pathlib.Path, required=True)
    ap.add_argument("--product-source-dir", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--timeout", type=float, default=8)
    ap.add_argument("--job-timeout", type=float, default=360)
    ap.add_argument("--state-timeout", type=float, default=240)
    args = ap.parse_args()

    receipt = {
        "contract": "truenas-model-compass-guest-image-transport/v1",
        "classification": "ORACLE_FAILURE",
        "oracleSatisfied": False,
        "native_F2_F6": "NOT_RUN",
        "target_version": TARGET,
        "product_source_sha": PRODUCT_SOURCE_SHA,
        "registry_image": REGISTRY_REF,
        "registry_app": REGISTRY_APP_NAME,
        "guest_compass_app_created": False,
        "guest_registry_app_created": False,
        "guest_registry_cleanup": "NOT_RUN",
        "docker_daemon_modified": False,
        "image_published_external": False,
        "evidence": {},
    }
    ws = None
    owns_app = False
    request_id = 1

    try:
        plan = read_plan(args.plan_file)
        source = args.product_source_dir.resolve(strict=True)
        require(source.is_dir(), "exact product source missing")
        require(run(["git", "rev-parse", "HEAD"], cwd=source) == PRODUCT_SOURCE_SHA, "product checkout identity drift")
        require((source / "deploy/model-compass/Dockerfile").is_file(), "product Dockerfile missing")
        require(args.host == "127.0.0.1" and args.port > 0, "middleware must be runner-local")
        require(HOST_PORT == GUEST_PORT == 15431, "test-only registry port drift")
        passfile = args.password_file
        require(passfile.is_file(), "disposable installer credential file missing")
        password = passfile.read_text(encoding="utf-8").strip()

        ws = WebSocket(args.host, args.port, timeout=args.timeout, tls=args.tls)
        ws.send_json({"msg": "connect", "version": "1", "support": ["1"]})
        hello = wait_for(ws, lambda m: m.get("msg") in {"connected", "failed"})
        require(hello.get("msg") == "connected", "TrueNAS guest DDP connection failed")

        def call(method: str, params: list):
            nonlocal request_id
            response = ddp_call(ws, str(request_id), method, params)
            request_id += 1
            return response

        def job(job_id: int, label: str):
            require(isinstance(job_id, int), f"{label} missing native job id")
            limit = time.monotonic() + args.job_timeout
            while time.monotonic() < limit:
                observed = call("core.get_jobs", [[[ "id", "=", job_id ]], {"get": True}])
                state = observed.get("state") if isinstance(observed, dict) else None
                if state == "SUCCESS":
                    receipt["evidence"][label] = "SUCCESS"
                    return
                if state in {"FAILED", "ABORTED"}:
                    raise RuntimeError(f"guest middleware {label} failed: {state}")
                time.sleep(2)
            raise RuntimeError(f"guest middleware {label} timed out")

        login = call("auth.login_ex", [{
            "mechanism": "PASSWORD_PLAIN", "username": "truenas_admin", "password": password,
        }])
        require(isinstance(login, dict) and login.get("response_type") == "SUCCESS", "guest auth denied")
        del password

        version = call("system.version", [])
        require(version == EXPECTED_SYSTEM, "guest TrueNAS exact-version mismatch")
        receipt["evidence"]["system.version"] = version
        status = call("docker.status", [])
        require(isinstance(status, dict) and status.get("status") == "RUNNING", "guest native Docker/App not READY")

        def app_query():
            return call("app.query", [[[ "id", "=", REGISTRY_APP_NAME ]]])

        require(not app_query(), "foreign/previous registry instance present: refusing adoption")

        job(call("app.create", [{
            "app_name": REGISTRY_APP_NAME,
            "custom_app": True,
            "custom_compose_config": plan["guest_registry_compose"],
        }]), "registry_app_create")
        owns_app = True
        receipt["guest_registry_app_created"] = True
        until = time.monotonic() + args.state_timeout
        while time.monotonic() < until:
            apps = app_query()
            if len(apps) == 1 and apps[0].get("state") == "RUNNING" and apps[0].get("custom_app") is True:
                break
            if apps and apps[0].get("state") in {"CRASHED", "ERROR"}:
                raise RuntimeError("guest registry app entered failure state")
            time.sleep(2)
        else:
            raise RuntimeError("guest registry did not reach native RUNNING")
        config = call("app.config", [REGISTRY_APP_NAME])
        require(isinstance(config, dict) and config.get("services", {}).get("registry", {}).get("image") == REGISTRY_REF,
                "native TrueNAS registry Compose exact-source readback mismatch")
        receipt["evidence"]["registry_app_readback"] = "EXACT_SOURCE_MATCH"

        health_url = f"http://127.0.0.1:{HOST_PORT}/v2/"
        until = time.monotonic() + 60
        while time.monotonic() < until:
            try:
                with urllib.request.urlopen(health_url, timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(2)
        else:
            raise RuntimeError("runner-local QEMU hostfwd to guest-native registry unreachable")
        receipt["evidence"]["qemu_guest_registry_hostfwd"] = "HTTP_200"

        name = f"127.0.0.1:{HOST_PORT}/compass-guest-fixture:{PRODUCT_SOURCE_SHA[:12]}"
        run(["docker", "build", "-f", "deploy/model-compass/Dockerfile",
             "--build-arg", f"SOURCE_REVISION={PRODUCT_SOURCE_SHA}", "-t", name, "."],
            cwd=source)
        run(["docker", "push", name])
        inspected = run(["docker", "image", "inspect", name, "--format", "{{index .RepoDigests 0}}"])
        require(inspected.startswith(f"127.0.0.1:{HOST_PORT}/compass-guest-fixture@"), "unexpected registry receipt")
        digest = inspected.rsplit("@", 1)[1]
        require(DIGEST_RE.fullmatch(digest) is not None, "nonimmutable model-compass image digest")
        guest_ref = f"127.0.0.1:{GUEST_PORT}/compass-guest-fixture@{digest}"
        receipt["evidence"]["image_manifest_digest"] = digest

        # This is the supported TrueNAS v25.04.2.6 middleware contract,
        # not a privileged 'docker load', daemon.json edit or unmanaged install.
        job(call("app.image.pull", [{"image": guest_ref}]), "native_app_image_pull")
        images = call("app.image.query", [])
        require(isinstance(images, list), "guest image inventory result invalid")
        matches = [image for image in images if isinstance(image, dict) and guest_ref in (image.get("repo_digests") or [])]
        require(matches, "guest-native image pull lacked immutable digest readback")
        receipt["evidence"]["image_repo_digest_readback"] = "EXACT_IMMUTABLE_DIGEST"
        receipt["evidence"]["guest_image_present"] = True
        receipt["classification"] = "SUPPORTED"
        receipt["oracleSatisfied"] = True
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, urllib.error.URLError) as ex:
        receipt["failure_type"] = type(ex).__name__
        receipt["failure_phase"] = "guest_transport"
        receipt["classification"] = "ORACLE_FAILURE"
        receipt["oracleSatisfied"] = False
        # Do not log source, credentials, large stderr, private host paths or token.
    finally:
        if ws is not None:
            if owns_app:
                try:
                    current = ddp_call(ws, str(request_id), "app.query", [[[ "id", "=", REGISTRY_APP_NAME ]]])
                    request_id += 1
                    if current:
                        remove_job = ddp_call(ws, str(request_id), "app.delete", [REGISTRY_APP_NAME])
                        request_id += 1
                        if isinstance(remove_job, int):
                            limit = time.monotonic() + args.job_timeout
                            while time.monotonic() < limit:
                                observation = ddp_call(ws, str(request_id), "core.get_jobs", [[[ "id", "=", remove_job ]], {"get": True}])
                                request_id += 1
                                if observation.get("state") == "SUCCESS": break
                                if observation.get("state") in {"FAILED", "ABORTED"}: break
                                time.sleep(2)
                        current = ddp_call(ws, str(request_id), "app.query", [[[ "id", "=", REGISTRY_APP_NAME ]]])
                        request_id += 1
                    receipt["guest_registry_cleanup"] = "ABSENT" if not current else "RESIDUAL"
                except Exception:
                    receipt["guest_registry_cleanup"] = "UNKNOWN"
                if receipt["guest_registry_cleanup"] != "ABSENT":
                    receipt["classification"] = "ORACLE_FAILURE"
                    receipt["oracleSatisfied"] = False
            try:
                ws.sock.close()
            except Exception:
                pass
        # Owned guest registry and QEMU must be gone for supported acceptance.
        if receipt["oracleSatisfied"] and receipt["guest_registry_cleanup"] != "ABSENT":
            receipt["oracleSatisfied"] = False
            receipt["classification"] = "ORACLE_FAILURE"
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return 0 if receipt["oracleSatisfied"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
