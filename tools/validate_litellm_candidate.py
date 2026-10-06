#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidates" / "litellm-app" / "candidate.json"
APP = ROOT / "candidates" / "litellm-app" / "ix-dev" / "community" / "litellm" / "app.yaml"
IX_VALUES = ROOT / "candidates" / "litellm-app" / "ix-dev" / "community" / "litellm" / "ix_values.yaml"
TEMPLATE = ROOT / "candidates" / "litellm-app" / "ix-dev" / "community" / "litellm" / "templates" / "docker-compose.yaml"
QUESTIONS = ROOT / "candidates" / "litellm-app" / "ix-dev" / "community" / "litellm" / "questions.yaml"
DOCKERFILE = ROOT / "appliances" / "litellm" / "Dockerfile"
SCORE = ROOT / "contracts" / "litellm" / "gateway-minimal.score.yaml"

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ValidationError(RuntimeError):
    pass


def scalar(text: str, key: str) -> str:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*([^#\n]+?)\s*$", text)
    if not m:
        raise ValidationError(f"missing scalar: {key}")
    return m.group(1).strip().strip("'\"")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain an object")
    return value


def validate() -> dict[str, Any]:
    candidate = load_json(CANDIDATE)
    app = APP.read_text(encoding="utf-8")
    ix = IX_VALUES.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    questions = QUESTIONS.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    score = SCORE.read_text(encoding="utf-8")

    upstream = candidate.get("upstream") or {}
    appliance = candidate.get("appliance") or {}
    source = candidate.get("source_materializer") or {}
    invariants = candidate.get("invariants") or {}

    upstream_version = upstream.get("version")
    upstream_digest = upstream.get("image_digest")
    appliance_digest = appliance.get("digest")
    appliance_ref = appliance.get("reference")

    if not isinstance(upstream_version, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", upstream_version):
        raise ValidationError("upstream version must be an exact vX.Y.Z release")
    for label, value in (("upstream digest", upstream_digest), ("appliance digest", appliance_digest)):
        if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
            raise ValidationError(f"{label} is not an exact sha256 digest")
    if appliance_ref != f"ghcr.io/sempersupra/litellm-appliance@{appliance_digest}":
        raise ValidationError("appliance reference/digest mismatch")
    if appliance.get("anonymous_pull") is not True or appliance.get("keyless_signed") is not True:
        raise ValidationError("published appliance lacks anonymous-pull/signing evidence")
    if appliance.get("build_status") != "PUBLIC_GHA_QUALIFIED":
        raise ValidationError("appliance is not public-GHA qualified")

    if source.get("lib_version") != scalar(app, "lib_version"):
        raise ValidationError("candidate/app lib_version mismatch")
    if source.get("lib_hash") != scalar(app, "lib_version_hash"):
        raise ValidationError("candidate/app lib_version_hash mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("lib_hash", ""))):
        raise ValidationError("TrueNAS library hash is not sha256-shaped")

    if upstream_version not in scalar(app, "app_version"):
        raise ValidationError("app_version does not carry upstream version")
    expected_base = f"ARG LITELLM_BASE=ghcr.io/berriai/litellm@{upstream_digest}"
    if expected_base not in dockerfile or "FROM ${LITELLM_BASE}" not in dockerfile:
        raise ValidationError("Dockerfile does not pin/use the candidate upstream digest")
    if f'com.sempersupra.litellm.upstream.version="{upstream_version}"' not in dockerfile:
        raise ValidationError("Dockerfile upstream version label mismatch")

    ix_repo = scalar(ix, "repository")
    ix_tag = scalar(ix, "tag")
    if ix_repo != "ghcr.io/sempersupra/litellm-appliance@sha256":
        raise ValidationError("ix_values repository is not exact-digest form")
    if f"sha256:{ix_tag}" != appliance_digest:
        raise ValidationError("ix_values appliance digest mismatch")

    for required in (
        'SEMPER_SECRET_DIR',
        'values.storage.config',
        'values.storage.provider_secrets',
        '"read_only": true',
        '/health/liveliness',
    ):
        if required not in template:
            raise ValidationError(f"TrueNAS template missing invariant: {required}")

    if "provider-secrets:" not in score or "type: volume" not in score or "class: env-files" not in score or "semper.supra/min-secret-tier: S1" not in score:
        raise ValidationError("Score contract does not preserve portable S1 provider-secret volume semantics")
    if invariants.get("minimum_secret_tier") != "S1":
        raise ValidationError("candidate minimum secret tier mismatch")
    if invariants.get("management_credentials_allowed") is not False:
        raise ValidationError("management credentials must be forbidden")
    if invariants.get("moving_tags_allowed") is not False:
        raise ValidationError("moving tags must be forbidden")

    combined = "\n".join((app, ix, template, questions, dockerfile, score, json.dumps(candidate)))
    for forbidden in (
        "OPENROUTER_MANAGEMENT_KEY=",
        "sk-or-mgmt-",
        ":latest",
        ":main-latest",
    ):
        if forbidden in combined:
            raise ValidationError(f"forbidden candidate content: {forbidden}")

    return {
        "result": "PASS",
        "upstream_version": upstream_version,
        "upstream_digest": upstream_digest,
        "appliance_digest": appliance_digest,
        "truenas_lib_version": source.get("lib_version"),
        "truenas_lib_hash": source.get("lib_hash"),
        "secret_tier": "S1",
        "management_credentials_allowed": False,
        "moving_tags_allowed": False,
    }


def main() -> int:
    try:
        print(json.dumps(validate(), indent=2, sort_keys=True))
        return 0
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
