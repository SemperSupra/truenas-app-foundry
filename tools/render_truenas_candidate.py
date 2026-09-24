#!/usr/bin/env python3
"""Render one exact Foundry TrueNAS source candidate from already-normalized values.

This is the second half of the public materialization contract:
  site adapter -> prepare_truenas_platform_values.py -> this renderer -> private apply

The renderer never contacts a TrueNAS host. Values may contain private material
such as certificate keys, so subprocess output is captured and never echoed on
success. The rendered/normalized Compose output is written mode 0600.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


class RenderError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RenderError(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(f"cannot read JSON {path}") from exc
    require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RenderError(f"cannot read YAML {path}") from exc
    require(isinstance(value, dict), f"{path} must contain a YAML mapping")
    return value


def run_private(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode:
        # Do not include stdout/stderr: renderer diagnostics may contain
        # normalized secret-bearing values supplied by the private site adapter.
        raise RenderError(f"private renderer command failed ({cp.returncode}): {cmd[0]}")
    return cp


def checkout_upstream(root: Path, manifest: dict[str, Any]) -> Path:
    materializer = manifest.get("source_materializer")
    require(isinstance(materializer, dict), "candidate source_materializer is required")
    repository = materializer.get("repository")
    commit = materializer.get("commit")
    require(isinstance(repository, str) and repository.startswith("https://"), "materializer repository must be HTTPS")
    require(isinstance(commit, str) and len(commit) == 40, "materializer commit must be a full SHA")

    checkout = root / "truenas-apps"
    run_private(["git", "init", "--quiet", str(checkout)], cwd=root)
    run_private(["git", "-C", str(checkout), "remote", "add", "origin", repository], cwd=root)
    run_private(
        ["git", "-C", str(checkout), "fetch", "--quiet", "--depth", "1", "origin", commit],
        cwd=root,
    )
    run_private(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=root)
    actual = run_private(["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=root).stdout.strip()
    require(actual == commit, "materializer checkout drifted")
    return checkout


def candidate_source(manifest: dict[str, Any]) -> tuple[Path, str, str]:
    source_path = manifest.get("source_path")
    require(isinstance(source_path, str) and source_path, "candidate source_path is required")
    source = (REPO_ROOT / source_path).resolve()
    require(source.is_dir(), "candidate source directory is missing")
    require(REPO_ROOT.resolve() in source.parents, "candidate source escapes repository")
    app = source.name
    train = source.parent.parent.name
    require(app and train, "candidate app/train identity is invalid")
    return source, train, app


def install_candidate(checkout: Path, manifest: dict[str, Any]) -> tuple[Path, str, str]:
    source, train, app = candidate_source(manifest)
    app_dir = checkout / "ix-dev" / train / app
    if app_dir.exists():
        shutil.rmtree(app_dir)
    shutil.copytree(source, app_dir)

    materializer = manifest["source_materializer"]
    version = str(materializer.get("lib_version") or "")
    require(version, "source materializer lib_version is required")
    lib_name = f"base_v{version.replace('.', '_')}"
    lib_src = checkout / "ix-dev" / train / "ntfy" / "templates" / "library" / lib_name
    lib_dst = app_dir / "templates" / "library" / lib_name
    require(lib_src.is_dir(), f"pinned TrueNAS renderer library is missing: {lib_name}")
    shutil.copytree(lib_src, lib_dst)
    return app_dir, train, app


def write_private_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    os.chmod(path, 0o600)


def normalize_compose(rendered: Path, checkout: Path) -> dict[str, Any]:
    cp = run_private(
        [
            "docker",
            "compose",
            "-p",
            "foundry-private-render",
            "-f",
            str(rendered),
            "config",
            "--format",
            "json",
        ],
        cwd=checkout,
    )
    try:
        compose = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RenderError("Docker Compose normalization did not return JSON") from exc
    require(isinstance(compose, dict), "normalized Compose is not an object")
    require(isinstance(compose.get("services"), dict) and compose["services"], "normalized Compose has no services")
    compose.pop("name", None)
    return compose


def render(manifest_path: Path, values_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    values = load_yaml(values_path)

    root = Path(tempfile.mkdtemp(prefix="foundry-private-render-"))
    try:
        checkout = checkout_upstream(root, manifest)
        app_dir, train, app = install_candidate(checkout, manifest)

        fixture_name = "foundry-materialized-values.yaml"
        fixture = app_dir / "templates" / "test_values" / fixture_name
        fixture.parent.mkdir(parents=True, exist_ok=True)
        write_private_yaml(fixture, values)

        run_private(
            [
                "python3",
                ".github/scripts/ci.py",
                "--app",
                app,
                "--train",
                train,
                "--test-file",
                fixture_name,
                "--render-only=true",
            ],
            cwd=checkout,
        )

        rendered = app_dir / "templates" / "rendered" / "docker-compose.yaml"
        require(rendered.is_file(), "candidate produced no rendered Compose")
        return normalize_compose(rendered, checkout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--values", type=Path, required=True)
    parser.add_argument("--output-compose", type=Path, required=True)
    args = parser.parse_args()

    for tool in ("git", "docker", "python3"):
        if not shutil.which(tool):
            print(f"ERROR: required tool missing: {tool}", file=os.sys.stderr)
            return 2

    try:
        compose = render(args.candidate, args.values)
        args.output_compose.parent.mkdir(parents=True, exist_ok=True)
        args.output_compose.write_text(
            json.dumps(compose, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(args.output_compose, 0o600)
        print(json.dumps({
            "status": "PASS",
            "output_mode": "0600",
            "services": sorted(compose["services"]),
            "secret_bearing_output": True,
        }, sort_keys=True))
        return 0
    except (RenderError, OSError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
