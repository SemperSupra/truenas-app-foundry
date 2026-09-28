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
PRIVATE_REPO_RE = re.compile(r"(?:https://github\.com/)?(?:SemperSupra/)?[A-Za-z0-9_.-]+-private\b", re.IGNORECASE)


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
    require(value.get("schema_version") == 1, "unsupported schema")
    require(value.get("candidate") == "wow-sidecar-truenas-app", "unexpected candidate")
    require(value.get("phase") in {
        "source-qualified-image-unpublished",
        "image-published-render-unqualified",
        "render-qualified-private-hil-pending",
        "private-hil-qualified-cutover-pending",
        "cutover-qualified",
    }, "unexpected phase")

    source = value.get("wow_source")
    require(isinstance(source, dict), "wow_source missing")
    require(
        source.get("repository") == "https://github.com/SemperSupra/wow-sidecar.git",
        "WOW source must use public authority",
    )
    for key in ("published_revision", "qualified_candidate_revision"):
        require(
            isinstance(source.get(key), str) and SHA_RE.fullmatch(source[key]) is not None,
            f"{key} must be a full Git SHA",
        )
    require(
        source.get("qualified_container_files_byte_equivalent_to_published_revision") is True,
        "published source equivalence is not established",
    )
    runs = source.get("qualification_runs")
    require(
        isinstance(runs, dict)
        and isinstance(runs.get("compatibility"), int)
        and isinstance(runs.get("container_build"), int),
        "qualification runs missing",
    )

    container = value.get("container")
    require(isinstance(container, dict), "container missing")
    base = container.get("base_image")
    require(
        isinstance(base, str)
        and "@sha256:" in base
        and len(base.rsplit("@sha256:", 1)[1]) == 64
        and all(ch in "0123456789abcdef" for ch in base.rsplit("@sha256:", 1)[1]),
        "base image must be digest pinned",
    )
    require(
        isinstance(container.get("qualification_image_id"), str)
        and DIGEST_RE.fullmatch(container["qualification_image_id"]) is not None,
        "qualification image id invalid",
    )
    require(container.get("revision_file") == "/usr/share/wow-sidecar/source-revision", "revision file drift")
    require(container.get("entrypoint") == "wow-sidecar-worker", "entrypoint drift")
    require(container.get("runtime_user") == "wow-sidecar:wow-sidecar", "runtime must be non-root WOW user")

    published = container.get("publication_state") == "published"
    reference = container.get("registry_reference")
    if published:
        require(isinstance(reference, str) and IMAGE_RE.fullmatch(reference) is not None, "published image must be exact GHCR digest")
    else:
        require(reference is None, "unpublished image must not claim a registry reference")

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
        "cap_drop_all": True,
        "no_new_privileges": True,
        "privileged": False,
        "host_network": False,
        "host_paths_allowed": False,
        "container_runtime_socket_allowed": False,
    }
    for key, expected_value in expected.items():
        require(contract.get(key) == expected_value, f"TrueNAS contract drift: {key}")

    gates = value.get("gates")
    require(isinstance(gates, dict), "gates missing")
    require(gates.get("public_source_qualified") is True, "public source must be qualified")
    computed_hil_eligible = all(
        gates.get(key) is True
        for key in (
            "registry_image_published",
            "public_app_render_qualified",
        )
    )
    require(
        gates.get("hil_eligible") is computed_hil_eligible,
        "hil_eligible does not match pre-HIL gates",
    )
    if gates.get("private_truenas_hil_qualified") is True:
        require(computed_hil_eligible, "private HIL cannot precede image/render gates")
    if gates.get("state_preserving_cutover_qualified") is True:
        require(gates.get("private_truenas_hil_qualified") is True, "cutover cannot precede private HIL")

    rendered = json.dumps(value, sort_keys=True)
    require(
        PRIVATE_REPO_RE.search(rendered) is None,
        "private repository identity leaked into public candidate",
    )
    lowered = rendered.lower()
    for forbidden in ("/opt/wow-sidecar", "systemd"):
        require(forbidden not in lowered, f"legacy deployment assumption leaked into public candidate: {forbidden}")

    return {
        "result": "PASS",
        "candidate": value["candidate"],
        "phase": value["phase"],
        "published_revision": source["published_revision"],
        "registry_image_published": published,
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
