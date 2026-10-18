#!/usr/bin/env python3
"""Pinned upstream TrueNAS Apps native source-render check; NEVER deploys anything."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import validate_garm_controller_app as shared
from validate_gitlab_runner_catalog_seed import check as check_source

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "candidates/gitlab-runner-app/candidate.json"
SOURCE = ROOT / "candidates/gitlab-runner-app/ix-dev/community/gitlab-runner"

def qualify() -> dict:
    check_source(ROOT)
    manifest = json.loads(MANIFEST.read_text())
    with tempfile.TemporaryDirectory(prefix="foundry-gitlab-render-") as tmp:
        scratch = Path(tmp)
        checkout = shared.checkout_upstream(scratch, manifest)
        appdir = checkout / "ix-dev/community/gitlab-runner"
        if appdir.exists():
            raise shared.ValidationError("the pinned upstream catalog already contains gitlab-runner; refuse overlay")
        shutil.copytree(SOURCE, appdir)
        lib = f"base_v{manifest['source_materializer']['lib_version'].replace('.', '_')}"
        src = checkout / "ix-dev/community/ntfy/templates/library" / lib
        if not src.is_dir():
            raise shared.ValidationError(f"pinned library missing: {src}")
        shutil.copytree(src, appdir / "templates/library" / lib)
        shared.run([
            "python3", ".github/scripts/ci.py", "--app", "gitlab-runner",
            "--train", "community", "--test-file", "basic-values.yaml",
            "--render-only=true",
        ], cwd=checkout)
        rendered = appdir / "templates/rendered/docker-compose.yaml"
        if not rendered.is_file():
            raise shared.ValidationError("pinned catalog source did not render Compose")
        cp = shared.run(["docker", "compose", "-p", "foundry-gitlab-runner",
                         "-f", str(rendered), "config", "--format", "json"], cwd=checkout)
        compose = json.loads(cp.stdout)
        compose.pop("name", None)
        services = compose.get("services") or {}
        if set(services) != {"gitlab-runner", "gitlab-runner-config-seed"}:
            raise shared.ValidationError(f"unrecognized service inventory: {sorted(services)}")
        image = manifest["manager_image"]["reference"]
        for name, service in services.items():
            if service.get("image") != image:
                raise shared.ValidationError(f"{name}: immutable image identity drift")
            shared.assert_security(name, service)
            mounted = shared.mounts(service)
            if len(mounted) != 1 or mounted[0]["target"] != "/etc/gitlab-runner":
                raise shared.ValidationError(f"{name}: unexpected mount targets {mounted}")
            if service.get("network_mode") == "host" or service.get("privileged"):
                raise shared.ValidationError(f"{name}: forbidden privileged/host network")
            if service.get("ports"):
                raise shared.ValidationError(f"{name}: unexpected host-published port")
        seed = services["gitlab-runner-config-seed"]
        runner = services["gitlab-runner"]
        if seed.get("network_mode") != "none":
            raise shared.ValidationError("seed helper must be offline")
        if (runner.get("depends_on") or {}).get("gitlab-runner-config-seed", {}).get("condition") != "service_completed_successfully":
            raise shared.ValidationError("runner must wait for successful seed")
        script = shared.extract_seed_script(seed)
        for x in ("if [ -e", "[ ! -s", "exit 42", "umask 077", "chmod 0600"):
            if x not in script:
                raise shared.ValidationError(f"missing seed guard {x!r}")
        config = str((compose.get("configs") or {}).get("gitlab-initial-config", {}).get("content") or "")
        if "concurrent = 1" not in config or "[[runners]]" in config or "token =" in config:
            raise shared.ValidationError("controller bootstrap configured runners or leaked credentials")
        digest = hashlib.sha256(json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {
            "result":"PASS_PINNED_SOURCE_RENDER_ONLY",
            "rendered_compose_sha256":digest,
            "pinned_trueNAS_source":manifest["source_materializer"]["commit"],
            "image_identity":image,
            "services":sorted(services),
            "worker_enabled":False,
            "gitlab_runner_registered":False,
            "image_runtime_qualified":False,
            "foundry_lifecycle_qualified":False,
            "official_catalog_admitted":False
        }

def main() -> int:
    try:
        print(json.dumps(qualify(), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, shared.ValidationError) as ex:
        print("RENDER QUALIFICATION FAIL: " + str(ex), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
