#!/usr/bin/env python3
"""Validate the pinned TrueNAS Apps materializer against known-good controls.

This is a public-safe execution-plane check. It never contacts a TrueNAS host,
starts an application, or consumes private credentials. The goal is narrower:
prove that one exact upstream TrueNAS Apps revision can render known-good catalog
applications and that the normalized Compose retains stable structural/security
properties.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from package_truenas_deployment_artifact import build_artifact

REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_FILE = REPO_ROOT / ".foundry" / "truenas-apps-upstream.json"


class ValidationError(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if cp.returncode:
        detail = (cp.stderr or cp.stdout or "")[-4000:]
        raise ValidationError(
            f"command failed ({cp.returncode}): {' '.join(cmd)}\n{detail}"
        )
    return cp


def load_pin() -> dict[str, Any]:
    try:
        pin = json.loads(PIN_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {PIN_FILE}: {exc}") from exc

    for key in (
        "repository",
        "ref",
        "train",
        "library_version",
        "library_hash",
        "controls",
    ):
        if not pin.get(key):
            raise ValidationError(f"pin manifest missing {key}")
    if not isinstance(pin["controls"], list) or len(pin["controls"]) < 2:
        raise ValidationError("pin manifest must define at least two controls")
    if len(str(pin["ref"])) != 40 or any(c not in "0123456789abcdef" for c in pin["ref"]):
        raise ValidationError("upstream ref must be a full lowercase Git commit SHA")
    return pin


def checkout_upstream(root: Path, pin: dict[str, Any]) -> Path:
    checkout = root / "truenas-apps"
    run(["git", "init", "--quiet", str(checkout)], cwd=root)
    run(["git", "-C", str(checkout), "remote", "add", "origin", pin["repository"]], cwd=root)
    run(
        [
            "git",
            "-C",
            str(checkout),
            "fetch",
            "--quiet",
            "--depth",
            "1",
            "origin",
            pin["ref"],
        ],
        cwd=root,
    )
    run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=root)
    actual = run(["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if actual != pin["ref"]:
        raise ValidationError(f"upstream checkout mismatch: expected {pin['ref']}, got {actual}")
    return checkout


def require_library_identity(app_dir: Path, pin: dict[str, Any]) -> None:
    app_yaml = app_dir / "app.yaml"
    if not app_yaml.is_file():
        raise ValidationError(f"missing catalog metadata: {app_yaml}")
    text = app_yaml.read_text()
    if f"lib_version: {pin['library_version']}" not in text:
        raise ValidationError(f"{app_dir.name}: library version differs from pinned baseline")
    if f"lib_version_hash: {pin['library_hash']}" not in text:
        raise ValidationError(f"{app_dir.name}: library hash differs from pinned baseline")


def normalize_rendered(checkout: Path, pin: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    app = str(control["app"])
    test_file = str(control["test_file"])
    train = str(pin["train"])
    app_dir = checkout / "ix-dev" / train / app
    require_library_identity(app_dir, pin)

    run(
        [
            "python3",
            ".github/scripts/ci.py",
            "--app",
            app,
            "--train",
            train,
            "--test-file",
            test_file,
            "--render-only=true",
        ],
        cwd=checkout,
    )

    rendered = app_dir / "templates" / "rendered" / "docker-compose.yaml"
    if not rendered.is_file():
        raise ValidationError(f"{train}/{app}:{test_file} produced no rendered Compose")

    normalized = run(
        [
            "docker",
            "compose",
            "-p",
            f"foundry-{app}"[:63],
            "-f",
            str(rendered),
            "config",
            "--format",
            "json",
        ],
        cwd=checkout,
    )
    try:
        compose = json.loads(normalized.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{app}: Docker Compose normalization did not return JSON") from exc
    if not isinstance(compose.get("services"), dict) or not compose["services"]:
        raise ValidationError(f"{app}: normalized Compose has no services")
    compose.pop("name", None)
    return compose


def service(compose: dict[str, Any], name: str) -> dict[str, Any]:
    value = compose.get("services", {}).get(name)
    if not isinstance(value, dict):
        raise ValidationError(
            f"expected service {name!r}; got {sorted(compose.get('services', {}))}"
        )
    return value


def mounts(value: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for mount in value.get("volumes") or []:
        if isinstance(mount, dict):
            result.append(
                {
                    "type": str(mount.get("type") or ""),
                    "source": str(mount.get("source") or ""),
                    "target": str(mount.get("target") or ""),
                    "read_only": bool(mount.get("read_only", False)),
                }
            )
        elif isinstance(mount, str):
            parts = mount.split(":")
            if len(parts) >= 2:
                result.append(
                    {
                        "type": "string",
                        "source": parts[0],
                        "target": parts[1],
                        "read_only": len(parts) > 2 and "ro" in parts[2].split(","),
                    }
                )
    return result


def has_target(value: dict[str, Any], target: str) -> bool:
    return any(mount["target"] == target for mount in mounts(value))


def has_docker_socket(value: dict[str, Any]) -> bool:
    return any(
        "/var/run/docker.sock" in mount["source"]
        or "/var/run/docker.sock" in mount["target"]
        for mount in mounts(value)
    )


def security(value: dict[str, Any]) -> dict[str, Any]:
    security_opts = [
        str(item).lower().replace(":", "=")
        for item in (value.get("security_opt") or [])
    ]
    return {
        "user": str(value.get("user") or ""),
        "privileged": bool(value.get("privileged", False)),
        "cap_drop": sorted(str(item).upper() for item in (value.get("cap_drop") or [])),
        "no_new_privileges": any(
            item.startswith("no-new-privileges=true") for item in security_opts
        ),
        "restart": str(value.get("restart") or ""),
        "healthcheck": bool(value.get("healthcheck")),
    }


def assert_library_security(label: str, value: dict[str, Any]) -> None:
    sec = security(value)
    failures: list[str] = []
    if sec["privileged"]:
        failures.append("privileged=true")
    if not sec["user"] or sec["user"] in {"0", "0:0", "root"}:
        failures.append("root or unspecified user")
    if "ALL" not in sec["cap_drop"]:
        failures.append("cap_drop ALL missing")
    if not sec["no_new_privileges"]:
        failures.append("no-new-privileges missing")
    if sec["restart"] != "unless-stopped":
        failures.append(f"unexpected restart policy {sec['restart']!r}")
    if not sec["healthcheck"]:
        failures.append("healthcheck missing")
    if failures:
        raise ValidationError(f"{label}: " + "; ".join(failures))


def assert_control(app: str, test_file: str, compose: dict[str, Any], primary_name: str) -> None:
    primary = service(compose, primary_name)
    assert_library_security(app, primary)

    if app == "forgejo-runner":
        for helper in ("init", "permissions"):
            service(compose, helper)
        if not has_target(primary, "/data"):
            raise ValidationError("forgejo-runner: /data storage missing")
        if not has_docker_socket(primary):
            raise ValidationError("forgejo-runner: expected upstream Docker socket missing")
        return

    if app == "element-web":
        if not primary.get("ports"):
            raise ValidationError("element-web: expected published web port missing")
        if has_docker_socket(primary):
            raise ValidationError("element-web: unexpected Docker socket materialized")
        for mount in mounts(primary):
            if mount["type"] == "bind" or str(mount["source"]).startswith("/"):
                raise ValidationError(
                    "element-web: live T6 control must not materialize host/bind storage"
                )
        return

    if app == "ntfy":
        service(compose, "permissions")
        if not primary.get("ports"):
            raise ValidationError("ntfy: expected published port missing")
        for target in ("/var/ntfy", "/etc/ntfy"):
            if not has_target(primary, target):
                raise ValidationError(f"ntfy: expected storage target {target} missing")
        if has_docker_socket(primary):
            raise ValidationError("ntfy: unexpected Docker socket materialized")

        if test_file == "https-values.yaml":
            configs = compose.get("configs") or {}
            if not all(name in configs for name in ("private", "public")):
                raise ValidationError("ntfy HTTPS: certificate/private-key configs were not rendered")
            env = primary.get("environment") or {}
            if not isinstance(env, dict):
                raise ValidationError("ntfy HTTPS: expected environment mapping")
            if not env.get("NTFY_KEY_FILE") or not env.get("NTFY_CERT_FILE"):
                raise ValidationError("ntfy HTTPS: certificate paths were not wired into the container")
            if not str(env.get("NTFY_LISTEN_HTTPS") or "").startswith(":"):
                raise ValidationError("ntfy HTTPS: HTTPS listener was not enabled")
        return

    raise ValidationError(f"no stable control assertions defined for {app!r}")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def image_repository(image: str) -> str:
    base = image.split("@", 1)[0]
    colon = base.rfind(":")
    slash = base.rfind("/")
    return base[:colon] if colon > slash else base


def resolve_runtime_images(compose: dict[str, Any], *, cwd: Path) -> tuple[dict[str, Any], dict[str, str]]:
    lowered = copy.deepcopy(compose)
    resolved: dict[str, str] = {}
    for service_name, value in lowered.get("services", {}).items():
        image = str(value.get("image") or "")
        if not image:
            continue
        if "@sha256:" in image:
            resolved[service_name] = image
            continue
        run(["docker", "pull", "--quiet", image], cwd=cwd)
        inspected = run(
            ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
            cwd=cwd,
        )
        try:
            repo_digests = json.loads(inspected.stdout.strip())
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{service_name}: Docker RepoDigests was not JSON") from exc
        repository = image_repository(image)
        matches = [
            str(item)
            for item in (repo_digests or [])
            if str(item).startswith(repository + "@sha256:")
        ]
        if len(matches) != 1:
            raise ValidationError(
                f"{service_name}: expected one immutable digest for {repository}, got {matches!r}"
            )
        value["image"] = matches[0]
        resolved[service_name] = matches[0]
    if not resolved:
        raise ValidationError("runtime-safe control resolved no container images")
    return lowered, resolved


def lower_runtime_control(
    compose: dict[str, Any],
    control: dict[str, Any],
    primary_name: str,
    *,
    cwd: Path,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    lowered = copy.deepcopy(compose)
    host_port = int(control.get("runtime_host_port") or 0)
    if not (1024 <= host_port <= 65535):
        raise ValidationError("runtime-safe control must define runtime_host_port >= 1024")
    primary = service(lowered, primary_name)
    ports = primary.get("ports") or []
    published = [p for p in ports if isinstance(p, dict) and p.get("published") is not None]
    if len(published) != 1:
        raise ValidationError(
            f"{control['app']}: expected exactly one published primary port for T6 lowering"
        )
    original_port = str(published[0]["published"])
    published[0]["published"] = str(host_port)

    for portal in lowered.get("x-portals") or []:
        if isinstance(portal, dict) and str(portal.get("port")) == original_port:
            portal["port"] = host_port

    lowered, image_digests = resolve_runtime_images(lowered, cwd=cwd)
    primary = service(lowered, primary_name)
    if primary.get("privileged") is True or has_docker_socket(primary):
        raise ValidationError(f"{control['app']}: runtime-safe control gained unsafe privilege/socket")
    for mount in mounts(primary):
        if mount["type"] == "bind" or str(mount["source"]).startswith("/"):
            raise ValidationError(
                f"{control['app']}: runtime-safe control contains a host/bind mount"
            )
    for name, value in lowered.get("services", {}).items():
        image = str(value.get("image") or "")
        if image and "@sha256:" not in image:
            raise ValidationError(f"{name}: runtime-safe image is not digest pinned")

    lowering = {
        "published_port": {
            "from": int(original_port),
            "to": host_port,
        },
        "images": "resolved-to-registry-digest",
    }
    return lowered, image_digests, lowering


def fingerprint(compose: dict[str, Any], primary_name: str) -> dict[str, Any]:
    primary = service(compose, primary_name)
    canonical = json.dumps(compose, sort_keys=True, separators=(",", ":")).encode()
    return {
        "services": sorted(compose.get("services", {})),
        "primary_service": primary_name,
        "security": security(primary),
        "mount_targets": sorted(mount["target"] for mount in mounts(primary)),
        "has_ports": bool(primary.get("ports")),
        "has_configs": bool(compose.get("configs")),
        "has_docker_socket": has_docker_socket(primary),
        "images": {
            name: str(value.get("image") or "")
            for name, value in sorted(compose.get("services", {}).items())
        },
        "compose_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def _materialized_filename(app: str, test_file: str) -> str:
    safe_test = test_file.removesuffix(".yaml").replace("/", "-")
    return f"{app}--{safe_test}.compose.json"


def write_materialized_controls(
    directory: Path,
    pin: dict[str, Any],
    controls: list[dict[str, Any]],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    index_entries: list[dict[str, Any]] = []
    for item in controls:
        app = str(item["app"])
        test_file = str(item["test_file"])
        compose = item["compose"]
        fp = item["fingerprint"]
        filename = _materialized_filename(app, test_file)
        (directory / filename).write_text(
            json.dumps(compose, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        entry = {
            "app": app,
            "test_file": test_file,
            "primary_service": item["primary_service"],
            "compose_path": filename,
            "compose_sha256": fp["compose_sha256"],
            "runtime_safe": bool(item.get("runtime_safe", False)),
            "qualification_role": item.get("qualification_role"),
        }
        if item.get("source_compose") is not None:
            source_filename = filename.replace(".compose.json", ".source.compose.json")
            (directory / source_filename).write_text(
                json.dumps(item["source_compose"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            entry["source_compose_path"] = source_filename
            entry["source_compose_sha256"] = item["source_compose_sha256"]
            entry["image_digests"] = item["image_digests"]
            entry["target_lowering"] = item["target_lowering"]
            entry["runtime_app_name"] = item["runtime_app_name"]

            deployment = item["deployment_artifact"]
            deployment_filename = filename.replace(".compose.json", ".deployment.json")
            deployment_text = json.dumps(deployment, indent=2, sort_keys=True) + "\n"
            (directory / deployment_filename).write_text(deployment_text, encoding="utf-8")
            entry["deployment_artifact_path"] = deployment_filename
            entry["deployment_artifact_file_sha256"] = hashlib.sha256(
                deployment_text.encode()
            ).hexdigest()
            entry["deployment_artifact_sha256"] = deployment["artifact_sha256"]
            entry["materialization_identity"] = deployment["materialization_identity"]
        index_entries.append(entry)

    index = {
        "schema": "truenas-foundry-materialized-controls/v1",
        "upstream": {
            "repository": pin["repository"],
            "ref": pin["ref"],
            "train": pin["train"],
            "library_version": pin["library_version"],
            "library_hash": pin["library_hash"],
        },
        "controls": index_entries,
    }
    (directory / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def validate(materialized_dir: Path | None = None) -> dict[str, Any]:
    for tool in ("git", "docker", "python3"):
        if not shutil.which(tool):
            raise ValidationError(f"required tool not found: {tool}")

    pin = load_pin()
    root = Path(tempfile.mkdtemp(prefix="foundry-truenas-materialization-"))
    try:
        checkout = checkout_upstream(root, pin)
        evidence: dict[str, Any] = {}
        materialized: list[dict[str, Any]] = []
        for control in pin["controls"]:
            app = str(control["app"])
            test_file = str(control["test_file"])
            primary_name = str(control["primary_service"])
            source_compose = normalize_rendered(checkout, pin, control)
            assert_control(app, test_file, source_compose, primary_name)
            compose = source_compose
            runtime_fields: dict[str, Any] = {}
            if control.get("runtime_safe") is True:
                compose, image_digests, target_lowering = lower_runtime_control(
                    source_compose, control, primary_name, cwd=checkout
                )
                runtime_app_name = str(control.get("runtime_app_name") or "")
                if not runtime_app_name:
                    raise ValidationError("runtime-safe control must define runtime_app_name")
                source_sha = canonical_sha256(source_compose)
                deployment = build_artifact(
                    runtime_app_name,
                    compose,
                    provenance={
                        "source": "truenas/apps",
                        "repository": pin["repository"],
                        "ref": pin["ref"],
                        "train": pin["train"],
                        "app": app,
                        "test_file": test_file,
                        "source_compose_sha256": source_sha,
                        "qualification_role": control.get("qualification_role"),
                        "target_lowering": target_lowering,
                        "image_digests": image_digests,
                    },
                )
                runtime_fields = {
                    "source_compose": source_compose,
                    "source_compose_sha256": source_sha,
                    "image_digests": image_digests,
                    "target_lowering": target_lowering,
                    "runtime_app_name": runtime_app_name,
                    "deployment_artifact": deployment,
                }
            fp = fingerprint(compose, primary_name)
            evidence[f"{pin['train']}/{app}:{test_file}"] = {
                **fp,
                "runtime_safe": bool(control.get("runtime_safe", False)),
                "qualification_role": control.get("qualification_role"),
                **({
                    "source_compose_sha256": runtime_fields["source_compose_sha256"],
                    "image_digests": runtime_fields["image_digests"],
                    "target_lowering": runtime_fields["target_lowering"],
                    "runtime_app_name": runtime_fields["runtime_app_name"],
                    "deployment_artifact_sha256": runtime_fields["deployment_artifact"]["artifact_sha256"],
                    "materialization_identity": runtime_fields["deployment_artifact"]["materialization_identity"],
                } if runtime_fields else {}),
            }
            materialized.append({
                "app": app,
                "test_file": test_file,
                "primary_service": primary_name,
                "compose": compose,
                "fingerprint": fp,
                "runtime_safe": bool(control.get("runtime_safe", False)),
                "qualification_role": control.get("qualification_role"),
                **runtime_fields,
            })
    finally:
        try:
            shutil.rmtree(root)
        except OSError as exc:
            # Upstream ci.py may leave rendered paths owned by a container user.
            # Hosted runners are ephemeral; cleanup inability must not convert an
            # otherwise-valid materialization result into a qualification failure.
            print(f"WARNING: best-effort temporary cleanup failed: {exc}", file=sys.stderr)

    if materialized_dir is not None:
        write_materialized_controls(materialized_dir, pin, materialized)

    return {
        "result": "PASS",
        "trust_claim": "pinned TrueNAS Apps materializer reproduced controls and lowered runtime-safe controls into immutable deployment artifacts",
        "non_claims": [
            "no private promotion approval",
            "no provider correctness claim",
            "no live TrueNAS compatibility claim",
        ],
        "upstream": {
            "repository": pin["repository"],
            "ref": pin["ref"],
            "train": pin["train"],
            "library_version": pin["library_version"],
            "library_hash": pin["library_hash"],
        },
        "controls": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        type=Path,
        help="optional path for the sanitized JSON evidence record",
    )
    parser.add_argument(
        "--materialized-dir",
        type=Path,
        help="optional directory for normalized Compose controls and an identity index",
    )
    args = parser.parse_args()
    try:
        evidence = validate(args.materialized_dir)
        payload = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        if args.evidence:
            args.evidence.write_text(payload)
        print(payload, end="")
        return 0
    except (ValidationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
