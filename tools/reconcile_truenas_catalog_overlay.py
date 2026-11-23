#!/usr/bin/env python3
"""Reconcile one Foundry-generated app overlay into a TrueNAS catalog checkout.

This is intentionally *not* a catalog source manager. It only owns the exact
app/train paths declared by a generated overlay and the corresponding
catalog.json entry. The official catalog Git HEAD remains the baseline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class OverlayError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_fingerprint(path: Path) -> str:
    if not path.exists():
        return ""
    records: list[str] = []
    for p in sorted(path.rglob("*")):
        rel = p.relative_to(path).as_posix()
        if p.is_symlink():
            raise OverlayError(f"symlink not allowed in overlay tree: {rel}")
        if p.is_dir():
            records.append(f"D {rel}")
        elif p.is_file():
            mode = p.stat().st_mode & 0o777
            records.append(f"F {mode:03o} {rel} {sha256_file(p)}")
    return hashlib.sha256(("\n".join(records) + "\n").encode()).hexdigest()


def git(catalog: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        ["git", "-C", str(catalog), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and cp.returncode:
        raise OverlayError(f"git {' '.join(args)} failed: {cp.stderr.strip()}")
    return cp


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverlayError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OverlayError(f"{path} must contain a JSON object")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=4)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if tmp.exists():
            tmp.unlink()


def load_overlay(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "overlay.json")
    for key in ("schema", "app", "train", "version", "catalog_entry", "tree_fingerprint"):
        if key not in manifest:
            raise OverlayError(f"overlay manifest missing {key}")
    if manifest["schema"] != "semper-supra.truenas-catalog-overlay/1":
        raise OverlayError("unsupported overlay schema")
    app = str(manifest["app"])
    train = str(manifest["train"])
    if not app or not train or "/" in app or "/" in train:
        raise OverlayError("invalid overlay app/train")
    source_tree = root / "trains" / train / app
    if not source_tree.is_dir():
        raise OverlayError(f"overlay train tree missing: {source_tree}")
    actual_fp = tree_fingerprint(source_tree)
    if actual_fp != manifest["tree_fingerprint"]:
        raise OverlayError(
            f"overlay tree fingerprint mismatch: expected={manifest['tree_fingerprint']} actual={actual_fp}"
        )
    if not isinstance(manifest["catalog_entry"], dict):
        raise OverlayError("catalog_entry must be an object")
    if manifest["catalog_entry"].get("name") not in (None, app):
        raise OverlayError("catalog_entry name conflicts with overlay app")
    return {**manifest, "source_tree": source_tree, "actual_fingerprint": actual_fp}


def baseline_contains_app(catalog: Path, train: str, app: str) -> bool:
    cp = git(catalog, "show", "HEAD:catalog.json", check=False)
    if cp.returncode:
        raise OverlayError("cannot read baseline catalog.json from HEAD")
    baseline = json.loads(cp.stdout)
    if isinstance(baseline, dict) and isinstance(baseline.get(train), dict):
        if app in baseline[train]:
            return True
    tracked = git(catalog, "ls-tree", "-r", "--name-only", "HEAD", "--", f"trains/{train}/{app}", check=False)
    return bool(tracked.stdout.strip())


def unrelated_changes(catalog: Path, train: str, app: str) -> list[str]:
    cp = git(catalog, "status", "--porcelain=v1", "--untracked-files=all")
    allowed_prefix = f"trains/{train}/{app}/"
    bad: list[str] = []
    for raw in cp.stdout.splitlines():
        if len(raw) < 4:
            continue
        path = raw[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path == "catalog.json" or path.startswith(allowed_prefix):
            continue
        bad.append(raw)
    return bad


def inspect(catalog: Path, overlay: dict[str, Any]) -> dict[str, Any]:
    train = str(overlay["train"])
    app = str(overlay["app"])
    desired_entry = overlay["catalog_entry"]
    desired_fp = overlay["tree_fingerprint"]
    if not (catalog / ".git").exists():
        raise OverlayError(f"catalog root is not a Git checkout: {catalog}")
    head = git(catalog, "rev-parse", "HEAD").stdout.strip()
    if baseline_contains_app(catalog, train, app):
        return {
            "status": "UPSTREAM_PRESENT",
            "action": "NONE",
            "head": head,
            "reason": "official Git HEAD already owns the app",
        }
    bad = unrelated_changes(catalog, train, app)
    if bad:
        return {
            "status": "UNRELATED_DRIFT",
            "action": "REFUSE",
            "head": head,
            "unrelated_changes": bad,
        }

    catalog_json = load_json(catalog / "catalog.json")
    train_data = catalog_json.get(train)
    if train_data is None:
        train_data = {}
    if not isinstance(train_data, dict):
        raise OverlayError(f"catalog train is not an object: {train}")
    observed_entry = train_data.get(app)

    dest = catalog / "trains" / train / app
    observed_fp = tree_fingerprint(dest) if dest.exists() else ""

    if observed_entry is None and not dest.exists():
        return {
            "status": "ABSENT",
            "action": "CREATE",
            "head": head,
            "observed_tree_fingerprint": None,
        }
    if observed_entry == desired_entry and observed_fp == desired_fp:
        return {
            "status": "OWNED_MATCH",
            "action": "NOOP",
            "head": head,
            "observed_tree_fingerprint": observed_fp,
        }
    if observed_entry is None and dest.exists():
        return {
            "status": "PARTIAL_DRIFT",
            "action": "REFUSE",
            "head": head,
            "reason": "overlay tree exists but catalog entry is absent",
            "observed_tree_fingerprint": observed_fp,
        }
    if observed_entry is not None and not dest.exists():
        return {
            "status": "PARTIAL_DRIFT",
            "action": "REFUSE",
            "head": head,
            "reason": "catalog entry exists but overlay tree is absent",
        }
    return {
        "status": "OWNED_DRIFT",
        "action": "REFUSE",
        "head": head,
        "observed_tree_fingerprint": observed_fp or None,
    }


def apply_overlay(catalog: Path, overlay: dict[str, Any]) -> dict[str, Any]:
    plan = inspect(catalog, overlay)
    if plan["action"] == "NOOP":
        return {**plan, "result": "NOOP"}
    if plan["action"] != "CREATE":
        return {**plan, "result": "REFUSED"}

    train = str(overlay["train"])
    app = str(overlay["app"])
    source = Path(overlay["source_tree"])
    dest = catalog / "trains" / train / app
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{app}.overlay.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(source, tmp)
    if tree_fingerprint(tmp) != overlay["tree_fingerprint"]:
        shutil.rmtree(tmp, ignore_errors=True)
        raise OverlayError("staged overlay fingerprint mismatch")
    os.replace(tmp, dest)

    catalog_path = catalog / "catalog.json"
    data = load_json(catalog_path)
    train_data = data.setdefault(train, {})
    if not isinstance(train_data, dict):
        raise OverlayError(f"catalog train is not an object: {train}")
    if app in train_data:
        raise OverlayError("catalog entry appeared during apply")
    train_data[app] = overlay["catalog_entry"]
    write_json_atomic(catalog_path, data)

    verified = inspect(catalog, overlay)
    if verified["action"] != "NOOP":
        raise OverlayError(f"post-apply verification failed: {verified}")
    return {**verified, "result": "APPLIED"}


def revert_overlay(catalog: Path, overlay: dict[str, Any]) -> dict[str, Any]:
    plan = inspect(catalog, overlay)
    if plan["status"] == "ABSENT":
        return {**plan, "result": "NOOP"}
    if plan["status"] == "UPSTREAM_PRESENT":
        return {**plan, "result": "REFUSED"}
    if plan["action"] != "NOOP":
        return {**plan, "result": "REFUSED"}

    train = str(overlay["train"])
    app = str(overlay["app"])
    dest = catalog / "trains" / train / app
    shutil.rmtree(dest)

    catalog_path = catalog / "catalog.json"
    data = load_json(catalog_path)
    train_data = data.get(train)
    if not isinstance(train_data, dict) or train_data.get(app) != overlay["catalog_entry"]:
        raise OverlayError("catalog entry changed during revert")
    del train_data[app]
    write_json_atomic(catalog_path, data)

    verified = inspect(catalog, overlay)
    if verified["status"] != "ABSENT":
        raise OverlayError(f"post-revert verification failed: {verified}")
    return {**verified, "result": "REVERTED"}


def receipt(mode: str, overlay: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "semper-supra.truenas-catalog-overlay-reconcile/1",
        "mode": mode,
        "app": overlay["app"],
        "train": overlay["train"],
        "version": overlay["version"],
        "overlay_tree_fingerprint": overlay["tree_fingerprint"],
        "status": outcome.get("status"),
        "action": outcome.get("action"),
        "result": outcome.get("result", "PLANNED"),
        "catalog_head": outcome.get("head"),
        "reason": outcome.get("reason"),
        "secrets_captured": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--overlay", type=Path, required=True)
    p.add_argument("--catalog-root", type=Path, required=True)
    p.add_argument("--mode", choices=("plan", "apply", "verify", "revert"), default="plan")
    p.add_argument("--evidence", type=Path)
    args = p.parse_args()
    try:
        overlay = load_overlay(args.overlay.resolve())
        catalog = args.catalog_root.resolve()
        if args.mode == "apply":
            outcome = apply_overlay(catalog, overlay)
        elif args.mode == "revert":
            outcome = revert_overlay(catalog, overlay)
        else:
            outcome = inspect(catalog, overlay)
            if args.mode == "verify":
                outcome = {**outcome, "result": "PASS" if outcome["action"] == "NOOP" else "FAIL"}
        out = receipt(args.mode, overlay, outcome)
        payload = json.dumps(out, indent=2, sort_keys=True) + "\n"
        if args.evidence:
            args.evidence.write_text(payload, encoding="utf-8")
        print(payload, end="")
        if outcome.get("action") == "REFUSE" or out.get("result") == "FAIL":
            return 3
        return 0
    except (OverlayError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
