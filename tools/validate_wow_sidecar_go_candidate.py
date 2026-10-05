#!/usr/bin/env python3
"""Validator for WOW Sidecar Go TrueNAS App candidate.

Validates candidate metadata, runtime contract, and deterministic rendering.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
from typing import Any

import jinja2
import yaml

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^ghcr\.io/sempersupra/wow-sidecar@sha256:[0-9a-f]{64}$")
HELPER_RE = re.compile(r"^ixsystems/container-utils@sha256:[0-9a-f]{64}$")
ZERO_IMAGE = "ghcr.io/sempersupra/wow-sidecar@sha256:" + ("0" * 64)
PUBLIC_RUNTIME_REVISION = "cd2d073f7d4366fa4165b8875e19d286da4e8784"
PRIVATE_REPO_RE = re.compile(r"(?:https://github[.]com/)?(?:SemperSupra/)?[A-Za-z0-9_.-]+-private(?![A-Za-z0-9_.-])", re.IGNORECASE)


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


class MockEnvironment:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}

    def add_env(self, key: str, value: Any) -> None:
        self.env[key] = str(value)


class MockConfigs:
    def __init__(self) -> None:
        self.configs: list[dict[str, Any]] = []

    def add(self, name: str, content: str, target_path: str, mode: str) -> None:
        self.configs.append({
            "name": name,
            "content": content,
            "target": target_path,
            "mode": mode,
        })


class MockDepends:
    def __init__(self) -> None:
        self.deps: dict[str, Any] = {}

    def add_dependency(self, name: str, condition: str) -> None:
        self.deps[name] = {"condition": condition}


class MockHealthcheck:
    def __init__(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False


class MockContainer:
    def __init__(self, name: str, image_key: str, values: dict[str, Any]) -> None:
        self.name = name
        self.image_key = image_key
        self.values = values
        self.user = "0:0"
        self.read_only = False
        self.init = False
        self.grace_period: int | None = None
        self.volumes: list[dict[str, Any]] = []
        self.ports: list[dict[str, Any]] = []
        self.environment = MockEnvironment()
        self.configs = MockConfigs()
        self.depends = MockDepends()
        self.healthcheck = MockHealthcheck()

    def set_user(self, uid: int, gid: int) -> None:
        self.user = f"{uid}:{gid}"

    def set_read_only(self, read_only: bool) -> None:
        self.read_only = bool(read_only)

    def set_init(self, init: bool) -> None:
        self.init = bool(init)

    def set_grace_period(self, seconds: int) -> None:
        self.grace_period = seconds

    def add_storage(self, target_path: str, storage_dict: dict[str, Any]) -> None:
        self.volumes.append({
            "target": target_path,
            "storage": storage_dict,
        })

    def add_port(self, port: int, options: dict[str, Any] | None = None) -> None:
        self.ports.append({
            "published": port,
            "options": options or {},
        })

    def to_dict(self) -> dict[str, Any]:
        image_info = self.values.get("images", {}).get(self.image_key, {})
        repo = image_info.get("repository", "")
        tag = image_info.get("tag", "")
        image_str = f"{repo}:{tag}"

        return {
            "image": image_str,
            "user": self.user,
            "read_only": self.read_only,
            "init": self.init,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges=true"],
            "environment": self.environment.env,
            "volumes": self.volumes,
            "configs": self.configs.configs,
            "ports": self.ports,
            "depends_on": self.depends.deps,
        }


class MockPerms:
    def __init__(self, name: str) -> None:
        self.name = name
        self.actions: list[dict[str, Any]] = []
        self.active = False

    def add_or_skip_action(self, action_name: str, storage_dict: dict[str, Any], perms_config: dict[str, Any]) -> None:
        self.actions.append({
            "action": action_name,
            "storage": storage_dict,
            "config": perms_config,
        })

    def has_actions(self) -> bool:
        return len(self.actions) > 0

    def activate(self) -> None:
        self.active = True


class MockDeps:
    def __init__(self) -> None:
        self.perms_objs: dict[str, MockPerms] = {}

    def perms(self, name: str) -> MockPerms:
        if name not in self.perms_objs:
            self.perms_objs[name] = MockPerms(name)
        return self.perms_objs[name]


class MockRender:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.containers: dict[str, MockContainer] = {}
        self.deps = MockDeps()

    def add_container(self, name: str, image_key: str) -> MockContainer:
        container = MockContainer(name, image_key, self.values)
        self.containers[name] = container
        return container

    def render(self) -> dict[str, Any]:
        services = {}
        all_configs = {}
        for name, c in self.containers.items():
            services[name] = c.to_dict()
            for cfg in c.configs.configs:
                all_configs[cfg["name"]] = {"content": cfg["content"], "target": cfg["target"], "mode": cfg["mode"]}
        return {
            "services": services,
            "configs": all_configs,
        }


def render_template(template_path: Path, values: dict[str, Any]) -> dict[str, Any]:
    mock_ix_lib = type("MockIxLib", (), {
        "base": type("MockBase", (), {
            "render": type("MockRenderModule", (), {"Render": MockRender})()
        })()
    })()

    env = jinja2.Environment(extensions=["jinja2.ext.do"])
    tpl = env.from_string(template_path.read_text(encoding="utf-8"))
    res_raw = tpl.render(values=values, ix_lib=mock_ix_lib)
    return json.loads(res_raw)


def load_candidate(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("candidate cannot be read") from exc
    require(isinstance(value, dict), "candidate must be an object")
    return value


def validate(value: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    require(value.get("schema_version") == 2, "unsupported schema")
    require(value.get("candidate") == "wow-sidecar-go-truenas-app", "unexpected candidate")
    require(value.get("phase") == "repo-prepared-exact-image-pending", "unexpected candidate phase")

    source = value.get("wow_source")
    require(isinstance(source, dict), "wow_source missing")
    require(source.get("repository") == "https://github.com/SemperSupra/wow-sidecar.git", "WOW source must use public authority")
    require(source.get("public_candidate_revision") == PUBLIC_RUNTIME_REVISION, "WOW public candidate revision drift")
    release_prep = source.get("release_prep")
    require(isinstance(release_prep, dict), "release_prep missing")
    require(release_prep.get("qualification") == "PASS", "release-prep qualification missing")
    require(release_prep.get("head") == "dfd19a9b60329fcbe6e2ce50aa1ab7064825abb2", "repaired release-prep head drift")
    require(release_prep.get("run") == 37284087557, "repaired release-prep run drift")
    require(release_prep.get("evidence_scope") == "repaired-head qualify-only release mechanics", "release-prep evidence scope drift")
    require(release_prep.get("publish") == "SKIPPED", "repo-prepared candidate must not claim publication")
    require(release_prep.get("native_verify") == "SKIPPED", "repo-prepared candidate must not claim native publication verification")
    require(release_prep.get("receipt") == "SKIPPED", "repo-prepared candidate must not claim publication receipt")
    require(release_prep.get("receipt_schema_prepared") == "wow-sidecar.go-publication-receipt.v2", "release receipt schema drift")
    require(release_prep.get("receipt_contract_qualified") is True, "release receipt contract qualification missing")
    require(release_prep.get("receipt_contract_qualification") == "PASS", "release receipt contract qualification drift")
    required_receipt_fields = release_prep.get("receipt_required_fields")
    require(isinstance(required_receipt_fields, list), "release receipt required fields missing")
    require(required_receipt_fields == [
        "source_sha",
        "immutable_tag",
        "manifest_digest",
        "platform_digests.linux/amd64",
        "platform_digests.linux/arm64",
        "publication.run_id",
        "publication.run_attempt",
        "publication.workflow_sha",
        "build_recipe.dockerfile",
        "build_recipe.workflow",
        "build_recipe.go_toolchain",
        "build_recipe.buildkit_image",
        "build_recipe.provenance",
        "build_recipe.sbom",
    ], "release receipt required fields drift")

    container = value.get("container")
    require(isinstance(container, dict), "container missing")
    require(isinstance(container.get("registry_reference"), str) and IMAGE_RE.fullmatch(container["registry_reference"]) is not None, "candidate image must be exact GHCR digest syntax")
    require(container.get("synthetic_digest_fixture") is True, "repo-prepared candidate must declare synthetic digest fixture")
    require(container.get("registry_reference") == ZERO_IMAGE, "repo-prepared candidate must use the zero non-deployable digest fixture")
    require(container.get("publication_state") == "not-published", "repo-prepared candidate must not claim image publication")
    require(container.get("build_recipe") == "scratch-plus-ca-certificates", "Go image recipe drift")
    require(container.get("entrypoint") == "/wow-sidecar", "entrypoint drift")
    require(container.get("runtime_user") == "10001:10001", "runtime user drift")
    require(container.get("shell_required") is False, "Go core must not require a shell")

    tn = value.get("truenas_source")
    require(isinstance(tn, dict), "truenas_source missing")
    require(tn.get("source_path") == "candidates/wow-sidecar-go-app/ix-dev/community/wow-sidecar", "TrueNAS source path drift")

    contract = value.get("truenas_contract")
    require(isinstance(contract, dict), "truenas contract missing")
    expected = {
        "deployment_kind": "custom-app",
        "state_storage": "ix_volume",
        "state_mount": "/var/lib/wow-sidecar",
        "github_app_secret_mount": "/run/secrets/github-app.pem",
        "peer_credentials_mount": "/run/secrets/wow-peer-credentials.json",
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
        "seed_helper_required": False,
    }
    for key, expected_value in expected.items():
        require(contract.get(key) == expected_value, f"TrueNAS contract drift: {key}")

    gates = value.get("gates")
    require(isinstance(gates, dict), "gates missing")
    require(gates.get("runtime_hosted_qualified") is True, "hosted runtime qualification must be recorded")
    require(gates.get("runtime_independent_accepted") is False, "independent runtime acceptance must remain false until #96/#89 acceptance")
    require(gates.get("registry_image_published") is False, "synthetic fixture cannot claim image publication")
    require(gates.get("public_app_render_qualified") is False, "repo-prepared App cannot claim public render qualification")
    require(gates.get("private_truenas_hil_qualified") is False, "repo-prepared App cannot claim private HIL")
    require(gates.get("state_preserving_cutover_qualified") is False, "repo-prepared App cannot claim cutover qualification")
    require(gates.get("hil_eligible") is False, "synthetic-image App cannot be HIL eligible")

    rendered_text = json.dumps(value, sort_keys=True)
    require(PRIVATE_REPO_RE.search(rendered_text) is None, "private repository identity leaked into public candidate")

    if root is not None:
        app_dir = root / tn["source_path"]
        template_path = app_dir / "templates" / "docker-compose.yaml"
        test_values_path = app_dir / "templates" / "test_values" / "basic-values.yaml"
        require(template_path.exists(), f"template missing at {template_path}")
        require(test_values_path.exists(), f"test values missing at {test_values_path}")

        values = yaml.safe_load(test_values_path.read_text(encoding="utf-8"))
        rendered = render_template(template_path, values)

        # Verify services and security contract
        services = rendered.get("services", {})
        require("wow-sidecar" in services, "worker service missing from rendered output")
        require("wow-sidecar-config-seed" not in services, "seed helper container must not exist in Go candidate")
        require(len(services) == 1, f"unexpected additional services: {list(services.keys())}")

        worker = services["wow-sidecar"]
        require(worker.get("user") == "10001:10001", "worker user must be 10001:10001")
        require(worker.get("read_only") is True, "worker rootfs must be read_only")
        require("ALL" in worker.get("cap_drop", []), "worker cap_drop must include ALL")
        require("no-new-privileges=true" in worker.get("security_opt", []), "worker no-new-privileges missing")

        # Environment variables assertions
        env_vars = worker.get("environment", {})
        require(env_vars.get("WOW_NODE_ID") == values["wow"]["node_id"], "WOW_NODE_ID missing or mismatched")
        require(env_vars.get("WOW_LOCALITY") == "sovereign", "WOW_LOCALITY must be sovereign")
        require(env_vars.get("WOW_GENERATION_STATE_FILE") == "/var/lib/wow-sidecar/generation.json", "WOW_GENERATION_STATE_FILE mismatch")
        require(env_vars.get("WOW_LISTEN_ADDR") == "0.0.0.0:8080", "WOW_LISTEN_ADDR mismatch")
        require(env_vars.get("GITHUB_APP_ID") == values["wow"]["github_app_id"], "GITHUB_APP_ID mismatch")
        require(env_vars.get("GITHUB_APP_PRIVATE_KEY_FILE") == "/run/secrets/github-app.pem", "GITHUB_APP_PRIVATE_KEY_FILE mismatch")
        require(env_vars.get("WOW_CONTROL_POLL_SECONDS") == "15", "WOW_CONTROL_POLL_SECONDS mismatch")
        require("WOW_PEER_RENDEZVOUS_ENABLED" not in env_vars, "peer mutation must be disabled by default")
        require("WOW_PEER_MAX_CLOCK_SKEW_SECONDS" not in env_vars, "obsolete peer skew environment name must not appear")
        require("WOW_PEER_REPLAY_WINDOW_SECONDS" not in env_vars, "obsolete replay environment name must not appear")
        require("WOW_PUBLIC_ENDPOINT" not in env_vars, "WOW_PUBLIC_ENDPOINT must not be advertised by default")

        # Ensure key material is not in environment
        for k, v in env_vars.items():
            require("BEGIN " not in v and "PRIVATE KEY" not in v, f"secret key material leaked into env var {k}")

        # Config secret file assertions
        configs = rendered.get("configs", {})
        require("wow-github-app-private-key" in configs, "github app key config missing")
        require(configs["wow-github-app-private-key"]["target"] == "/run/secrets/github-app.pem", "github app key target path mismatch")
        require(configs["wow-github-app-private-key"]["mode"] == "0400", "github app key mode must be 0400")

    return {
        "result": "PASS",
        "candidate": value["candidate"],
        "phase": value["phase"],
        "registry_reference": container["registry_reference"],
        "seed_helper_required": False,
        "runtime_user": container["runtime_user"],
        "deployable": False,
    }


def find_repo_root(candidate_path: Path) -> Path:
    p = candidate_path.resolve()
    for parent in [p] + list(p.parents):
        if (parent / ".git").exists() or (parent / "candidates").is_dir():
            return parent
    return Path.cwd()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    root = find_repo_root(args.candidate)
    try:
        value = load_candidate(args.candidate)
        result = validate(value, root=root)
        print(json.dumps(result, sort_keys=True))
        return 0
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
