#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^ghcr\.io/sempersupra/wow-sidecar@sha256:[0-9a-f]{64}$")
HELPER_RE = re.compile(r"^ixsystems/container-utils@sha256:[0-9a-f]{64}$")
PRIVATE_REPO_RE = re.compile(r"(?:https://github[.]com/)?(?:SemperSupra/)?[A-Za-z0-9_.-]+-private(?![A-Za-z0-9_.-])", re.IGNORECASE)

class ValidationError(RuntimeError):
    pass

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)

def load_candidate(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("candidate cannot be read") from exc
    require(isinstance(value, dict), "candidate must be an object")
    return value

def validate(value: dict[str, Any]) -> dict[str, Any]:
    require(value.get("schema_version") == 2, "unsupported schema")
    require(value.get("candidate") == "wow-sidecar-truenas-app", "unexpected candidate")
    require(value.get("phase") in {
        "image-published-render-unqualified",
        "render-qualified-private-hil-pending",
        "private-hil-qualified-cutover-pending",
        "cutover-qualified",
    }, "unexpected phase")

    source = value.get("wow_source")
    require(isinstance(source, dict), "wow_source missing")
    require(source.get("repository") == "https://github.com/SemperSupra/wow-sidecar.git", "WOW source must use public authority")
    for key in ("published_revision", "qualified_candidate_revision", "source_tree"):
        require(isinstance(source.get(key), str) and SHA_RE.fullmatch(source[key]) is not None, f"{key} must be a full Git SHA")
    require(source.get("qualified_tree_equivalent_to_published_revision") is True, "published source equivalence is not established")
    runs = source.get("qualification_runs")
    require(isinstance(runs, dict) and isinstance(runs.get("compatibility"), int) and isinstance(runs.get("container_build"), int), "qualification runs missing")

    container = value.get("container")
    require(isinstance(container, dict), "container missing")
    base = container.get("base_image")
    require(isinstance(base, str) and "@sha256:" in base and DIGEST_RE.fullmatch("sha256:" + base.rsplit("@sha256:", 1)[1]) is not None, "base image must be digest pinned")
    require(isinstance(container.get("qualification_image_id"), str) and DIGEST_RE.fullmatch(container["qualification_image_id"]) is not None, "qualification image id invalid")
    require(container.get("publication_state") == "published", "registry image must already be published")
    require(isinstance(container.get("registry_reference"), str) and IMAGE_RE.fullmatch(container["registry_reference"]) is not None, "published image must be exact GHCR digest")
    require(isinstance(container.get("publication_run"), int), "publication run missing")
    require(isinstance(container.get("digest_pin_run"), int), "digest pin run missing")
    require(container.get("revision_file") == "/usr/share/wow-sidecar/source-revision", "revision file drift")
    require(container.get("entrypoint") == "wow-sidecar-worker", "entrypoint drift")
    require(container.get("runtime_user") == "10001:10001", "runtime user drift")
    require(container.get("git_package_version") == "1:2.47.3-0+deb13u1", "Git package drift")
    require(container.get("github_cli_required") is False, "GitHub CLI must not be required")

    tn = value.get("truenas_source")
    require(isinstance(tn, dict), "truenas_source missing")
    require(tn.get("repository") == "https://github.com/truenas/apps.git", "TrueNAS materializer repository drift")
    require(isinstance(tn.get("commit"), str) and SHA_RE.fullmatch(tn["commit"]) is not None, "TrueNAS materializer commit invalid")
    require(tn.get("train") == "community", "TrueNAS train drift")
    require(tn.get("lib_version") == "2.3.4", "TrueNAS library version drift")
    require(tn.get("lib_hash") == "2e3a8847308fb2eb0da046018f287c73822c094b5950a10377c3235794ff1242", "TrueNAS library hash drift")
    require(tn.get("source_path") == "candidates/wow-sidecar-app/ix-dev/community/wow-sidecar", "TrueNAS source path drift")

    helper = value.get("permissions_helper")
    require(isinstance(helper, dict), "permissions helper missing")
    require(helper.get("candidate") == "ixsystems/container-utils:1.0.2", "permissions helper candidate drift")
    helper_ref = helper.get("reference")
    if helper_ref is not None:
        require(isinstance(helper_ref, str) and HELPER_RE.fullmatch(helper_ref) is not None, "permissions helper must use exact digest")

    contract = value.get("truenas_contract")
    require(isinstance(contract, dict), "truenas contract missing")
    expected = {
        "deployment_kind": "custom-app",
        "config_storage": "ix_volume",
        "config_mount": "/etc/wow-sidecar",
        "config_mount_read_only_for_worker": True,
        "state_storage": "ix_volume",
        "state_mount": "/var/lib/wow-sidecar",
        "root_filesystem_read_only": True,
        "temporary_filesystem": "/tmp",
        "runtime_uid": 10001,
        "runtime_gid": 10001,
        "supplemental_groups": [568],
        "cap_drop_all_for_wow_containers": True,
        "no_new_privileges": True,
        "privileged": False,
        "host_network": False,
        "host_paths_allowed": False,
        "container_runtime_socket_allowed": False,
        "config_seed": "create-once; preserve initialized config; fail on partial state",
        "permissions_helper_scope": "ixVolume ownership only",
    }
    for key, expected_value in expected.items():
        require(contract.get(key) == expected_value, f"TrueNAS contract drift: {key}")

    gates = value.get("gates")
    require(isinstance(gates, dict), "gates missing")
    require(gates.get("public_source_qualified") is True, "public source must be qualified")
    require(gates.get("registry_image_published") is True, "registry image must be qualified and published")
    render_qualified = gates.get("public_app_render_qualified") is True
    if render_qualified:
        require(helper_ref is not None, "render qualification requires immutable permissions helper")
        require(value.get("phase") != "image-published-render-unqualified", "render-qualified gate/phase mismatch")
        evidence = value.get("public_render_evidence")
        require(isinstance(evidence, dict), "render qualification requires durable evidence")
        require(evidence.get("result") == "PASS", "render qualification evidence is not PASS")
        require(evidence.get("run") == 36550143870, "render qualification run drift")
        require(evidence.get("qualified_head") == "c5aa14ac85482cc093c1e1283b7c8e969d805f0e", "render qualification head drift")
        require(evidence.get("compose_sha256") == "46ed8d0a3fdd543b5ad359cd73e2b5bf06b69a65ab4f6312fd5c523d2445ab1a", "rendered Compose digest drift")
        require(evidence.get("ghcr_anonymous_pull") is True, "render qualification did not prove anonymous GHCR pull")
        require(evidence.get("seed_behavior") == "PASS:create-once/preserve/fail-partial", "seed qualification drift")
        require(evidence.get("materializer_commit") == tn.get("commit"), "render materializer drift")
        require(evidence.get("wow_image") == container.get("registry_reference"), "render WOW image drift")
        require(evidence.get("permissions_helper") == helper_ref, "render permissions-helper drift")

    computed_hil_eligible = bool(gates.get("public_source_qualified") is True and gates.get("registry_image_published") is True and render_qualified)
    require(gates.get("hil_eligible") is computed_hil_eligible, "hil_eligible does not match pre-HIL gates")
    if gates.get("private_truenas_hil_qualified") is True:
        require(computed_hil_eligible, "private HIL cannot precede image/render gates")
    if gates.get("state_preserving_cutover_qualified") is True:
        require(gates.get("private_truenas_hil_qualified") is True, "cutover cannot precede private HIL")

    rendered = json.dumps(value, sort_keys=True)
    require(PRIVATE_REPO_RE.search(rendered) is None, "private repository identity leaked into public candidate")
    lowered = rendered.lower()
    for forbidden in ("/opt/wow-sidecar", "systemd", "docker.sock"):
        require(forbidden not in lowered, f"legacy/host deployment assumption leaked into public candidate: {forbidden}")

    return {
        "result": "PASS",
        "candidate": value["candidate"],
        "phase": value["phase"],
        "published_revision": source["published_revision"],
        "registry_reference": container["registry_reference"],
        "permissions_helper_pinned": helper_ref is not None,
        "hil_eligible": computed_hil_eligible,
        "private_hil_claimed": gates.get("private_truenas_hil_qualified") is True,
        "cutover_claimed": gates.get("state_preserving_cutover_qualified") is True,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(load_candidate(args.candidate)), sort_keys=True))
        return 0
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
