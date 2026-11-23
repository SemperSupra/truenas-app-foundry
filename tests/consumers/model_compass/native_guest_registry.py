"""Public-safe *plan only* for an isolated TrueNAS 25.04.2.6 guest OCI rendezvous.

Candidate transport for future native F2-F6: a disposable native TrueNAS
Custom App runs pinned OCI registry inside QEMU guest, its port is forwarded
ONLY to public runner loopback, then host pushes a source-attested image.
The TrueNAS guest pulls via its own localhost registry (Docker's loopback
exception), without editing daemon.json, enabling an external registry, or
publishing any image to GHCR. This module has ZERO network/host effects.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

REGISTRY_REF = (
    "registry@sha256:"
    "a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
)
TARGET = "25.04.2.6"
HOST_PORT = 15431
GUEST_PORT = 15431
REGISTRY_APP_NAME = "rdte-compass-registry"
IMAGE_NAMESPACE = "compass-guest-fixture"
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class PlanError(ValueError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise PlanError(message)


def plan(
    *,
    product_commit: str,
    target_version: str,
    isolated_kvm: bool,
    public_source_only: bool,
    host_bind: str = "127.0.0.1",
    host_port: int = HOST_PORT,
    guest_port: int = GUEST_PORT,
) -> dict[str, Any]:
    require(bool(SHA.fullmatch(product_commit)), "exact product Git SHA required")
    require(target_version == TARGET, "target must be exact prequalified TrueNAS version")
    require(isolated_kvm and public_source_only, "disposable isolated public-source KVM is mandatory")
    require(host_bind == "127.0.0.1", "QEMU port must be visible on runner loopback only")
    require(host_port == HOST_PORT and guest_port == GUEST_PORT, "fixed bound registry port contract")
    require(DIGEST.fullmatch(REGISTRY_REF.partition("@")[2]) is not None, "registry image must be immutable")
    require(REGISTRY_APP_NAME.startswith("rdte-"), "app cannot overlap actual site names")

    host_ref = f"{host_bind}:{host_port}/{IMAGE_NAMESPACE}:{product_commit[:12]}"
    guest_ref = f"127.0.0.1:{guest_port}/{IMAGE_NAMESPACE}:{product_commit[:12]}"
    # The app fixture gets its own *guest-only* registry address. No host mount
    # or Docker socket is passed to it. The QEMU user-net hostfwd is bound to
    # the disposable runner's loopback, so no public ingress exists.
    guest_registry_compose = {
        "services": {
            "registry": {
                "image": REGISTRY_REF,
                "restart": "unless-stopped",
                "ports": [f"0.0.0.0:{guest_port}:5000"],
                "read_only": True,
                "security_opt": ["no-new-privileges:true"],
                "cap_drop": ["ALL"],
                "pids_limit": 64,
                "mem_limit": 268435456,
                "tmpfs": ["/tmp:rw,noexec,nosuid,size=128m"],
                # Fixture push data is throwaway, not a production dataset.
                "environment": {"REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY": "/tmp/registry"},
            }
        }
    }
    result = {
        "schema": "truenas-compass-guest-registry-plan/v1",
        "classification": "CANDIDATE_NOT_HIL",
        "target_version": target_version,
        "scope": "disposable_public_kvm_only",
        "product_source_commit": product_commit,
        "registry_source_digest": REGISTRY_REF.partition("@")[2],
        "guest_registry_native_app": REGISTRY_APP_NAME,
        "qemu_hostfwd": f"hostfwd=tcp:{host_bind}:{host_port}-:{guest_port}",
        "host_push_tag": host_ref,
        "guest_pull_tag": guest_ref,
        "guest_registry_compose": guest_registry_compose,
        "native_app_mutation_authority": "existing_foundry_lifecycle_only",
        "requires_digest_rebinding": True,
        "source_oci_image": "HOST_BUILD_FROM_EXACT_SOURCE",
        "image_published_external": False,
        "requires_guest_snapshot_and_token_fixture": True,
        "requires_independent_app_query_config_and_state_readbacks": True,
        "requires_guest_registry_app_cleanup": True,
        "requires_zero_qemu_residue": True,
        "native_F2_F6": "NOT_RUN",
        "never_edit_docker_daemon": True,
        "never_create_site_registry_record": True,
    }
    result["plan_sha256"] = hashlib.sha256(
        json.dumps(result, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return result


def bind_guest_pull_digest(plan_doc: dict[str, Any], pushed_digest: str) -> str:
    """Bound image name selection; does not prove the digest was actually pushed."""
    require(plan_doc.get("schema") == "truenas-compass-guest-registry-plan/v1", "unknown plan")
    require(plan_doc.get("classification") == "CANDIDATE_NOT_HIL", "unexpected admission")
    require(bool(DIGEST.fullmatch(pushed_digest)), "unverified registry digest syntax")
    path = plan_doc.get("guest_pull_tag", "")
    require(bool(re.fullmatch(
        rf"127[.]0[.]0[.]1:{GUEST_PORT}/{IMAGE_NAMESPACE}:[0-9a-f]{{12}}", path
    )), "guest image registry target changed")
    return path.partition(":")[0] + ":" + str(GUEST_PORT) + "/" + IMAGE_NAMESPACE + "@" + pushed_digest


def verify_plan_contract(result: dict[str, Any]) -> None:
    """Fail closed on post-plan mutation before any future guest execution."""
    require(result.get("schema") == "truenas-compass-guest-registry-plan/v1", "unknown plan schema")
    sha = result.get("product_source_commit", "")
    expected = plan(
        product_commit=sha,
        target_version=result.get("target_version", ""),
        isolated_kvm=True,
        public_source_only=True,
    )
    require(expected == result, "plan changed after source/type/port binding")


if __name__ == "__main__":
    # Public default is the exact synthetic *integrated* product candidate.
    source = "6e88ccbe09f7f0989a8db4e75967654d409f8f64"
    print(json.dumps(plan(
        product_commit=source,
        target_version=TARGET,
        isolated_kvm=True,
        public_source_only=True,
    ), indent=2, sort_keys=True))
