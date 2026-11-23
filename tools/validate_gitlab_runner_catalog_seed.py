#!/usr/bin/env python3
"""Fail-closed SOURCE-SHAPE smoke for GitLab TrueNAS candidate; not a render/HIL oracle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidates" / "gitlab-runner-app" / "candidate.json"

class SourceContractError(ValueError):
    pass

def check(root: Path = ROOT) -> dict:
    c = root / "candidates" / "gitlab-runner-app"
    m = json.loads((c / "candidate.json").read_text())
    source = c / "ix-dev" / "community" / "gitlab-runner"
    required = ["README.md", "app.yaml", "ix_values.yaml", "questions.yaml",
                "templates/docker-compose.yaml", "templates/test_values/basic-values.yaml"]
    if not all((source / f).is_file() for f in required):
        raise SourceContractError("missing official-shaped candidate source file")
    if m.get("phase") != "SOURCE_SEED_NOT_ADMITTED" or m.get("plugin", {}).get("runtime_ready") is not False:
        raise SourceContractError("source seed misrepresents runner/plugin qualification")
    if m.get("gates", {}).get("official_catalog") != "NOT_ADMITTED":
        raise SourceContractError("source candidate must not claim official catalog admission")
    if m.get("gates", {}).get("physical_host") != "NOT_AUTHORIZED":
        raise SourceContractError("physical host gate unexpectedly opened")
    if m.get("source_path") != source.relative_to(root).as_posix():
        raise SourceContractError("source path identity drift")
    mat = m["source_materializer"]
    if not re.fullmatch(r"[0-9a-f]{40}", mat.get("commit", "")):
        raise SourceContractError("unversioned TrueNAS source")
    app = yaml.safe_load((source / "app.yaml").read_text())
    vals = yaml.safe_load((source / "ix_values.yaml").read_text())
    questions = yaml.safe_load((source / "questions.yaml").read_text())
    fixture = yaml.safe_load((source / "templates/test_values/basic-values.yaml").read_text())
    if app["name"] != "gitlab-runner" or app["train"] != "community":
        raise SourceContractError("incorrect catalog source name/train")
    if app["lib_version"] != mat["lib_version"] or app["lib_version_hash"] != mat["lib_hash"]:
        raise SourceContractError("materializer library fingerprint drift")
    digest = m["manager_image"]["reference"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9/._-]*@sha256:[0-9a-f]{64}", digest):
        raise SourceContractError("manager image is not digest pinned")
    # Fleeting plugin packaging was introduced in 16.11; prevent the prior
    # digest-compatible but obsolete GitLab Runner 14.4 regression.
    from packaging.version import Version
    image_version = m["manager_image"].get("version")
    if not isinstance(image_version, str) or Version(image_version) < Version("16.11.0"):
        raise SourceContractError("manager GitLab Runner predates Fleeting OCI support")
    if m["manager_image"].get("state") != "PUBLIC_GHA_EXACT_DIGEST_PULL_AND_OFFLINE_CLI_PASS_ONLY":
        raise SourceContractError("OCI provenance state is not independently verified")
    vimage = vals["images"]["image"]
    if digest != vimage["repository"] + ":" + vimage["tag"]:
        raise SourceContractError("manager image digest does not match candidate manifest")
    if questions["questions"][0]["variable"] != "runner":
        raise SourceContractError("runner non-secret config missing")
    attrs = questions["questions"][0]["schema"]["attrs"]
    concurrency = next((x["schema"] for x in attrs if x["variable"] == "concurrent"), {})
    if concurrency.get("default") != 1 or concurrency.get("max") != 1:
        raise SourceContractError("source seed permits unqualified capacity > 1")
    if fixture["runner"]["concurrent"] != 1:
        raise SourceContractError("source fixture allows unqualified capacity")
    template = (source / "templates/docker-compose.yaml").read_text()
    for forbidden in ("/var/run/docker.sock", "privileged: true", "host_network: true",
                      "hostNetwork", "auth.login_with_api_key", "glrt-", "TRUENAS_API_KEY"):
        if forbidden.lower() in template.lower():
            raise SourceContractError(f"forbidden template capability: {forbidden}")
    for required_fragment in ("ix_lib.base.render.Render", "tpl.add_container",
                              "seed.setup_as_helper", "seed.add_storage",
                              "runner.add_storage", "runner.depends.add_dependency",
                              "if [ -e", "[ ! -s", "exit 42", "umask 077", "service_completed_successfully"):
        if required_fragment not in template:
            raise SourceContractError(f"source-seed guard missing: {required_fragment}")
    if "setup_as_helper" not in template or "runner.set_user(0, 0)" not in template:
        raise SourceContractError("runtime user/helper envelope drift")
    if app.get("host_mounts") != [] or app.get("capabilities") != []:
        raise SourceContractError("app metadata advertises host mounts/capabilities")
    return {"result":"PASS_SOURCE_SHAPE_ONLY","phase":m["phase"],
            "source_path":m["source_path"],"image":digest,
            "materializer_commit":mat["commit"],
            "runtime_qualified":False,"official_catalog_admitted":False}

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(check(args.root), indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
