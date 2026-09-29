#!/usr/bin/env python3
"""Package one published TrueNAS app into a Foundry catalog overlay artifact."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from reconcile_truenas_catalog_overlay import OverlayError, tree_fingerprint


def load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverlayError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OverlayError(f"{path} must contain a JSON object")
    return value


def build_desired(
    published_app: Path,
    catalog_entry_path: Path,
    *,
    app: str,
    train: str,
    version: str,
    root: Path,
) -> Path:
    if not published_app.is_dir():
        raise OverlayError(f"published app directory missing: {published_app}")
    for required in ("item.yaml", "app_versions.json"):
        if not (published_app / required).is_file():
            raise OverlayError(f"published app missing {required}")
    if not (published_app / version).is_dir():
        raise OverlayError(f"published app missing version directory {version}")

    entry = load_object(catalog_entry_path)
    if entry.get("name") not in (None, app):
        raise OverlayError("catalog entry name conflicts with requested app")
    if entry.get("latest_version") != version:
        raise OverlayError(
            f"catalog entry latest_version {entry.get('latest_version')!r} != {version!r}"
        )
    timestamp_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    if not isinstance(entry.get("last_update"), str) or not timestamp_re.fullmatch(entry["last_update"]):
        raise OverlayError("catalog entry last_update must be a deterministic TrueNAS timestamp")

    versions = load_object(published_app / "app_versions.json")
    selected = versions.get(version)
    if not isinstance(selected, dict):
        raise OverlayError(f"app_versions.json missing version {version}")
    if not isinstance(selected.get("last_update"), str) or not timestamp_re.fullmatch(selected["last_update"]):
        raise OverlayError("published app version last_update must be a deterministic TrueNAS timestamp")

    desired = root / "desired"
    train_root = desired / "trains" / train
    train_root.mkdir(parents=True)
    shutil.copytree(published_app, train_root / app)
    fp = tree_fingerprint(train_root / app)
    manifest = {
        "schema": "semper-supra.truenas-catalog-overlay/1",
        "app": app,
        "train": train,
        "version": version,
        "catalog_entry": entry,
        "tree_fingerprint": fp,
    }
    (desired / "overlay.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return desired


def overlay_fingerprint(path: Path) -> str:
    return tree_fingerprint(path)


def determine_action(destination: Path, desired_fp: str) -> tuple[str, str]:
    if not destination.exists():
        return "CREATE", ""
    observed = overlay_fingerprint(destination)
    if observed == desired_fp:
        return "NOOP", observed
    return "DRIFT_REFUSE", observed


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--published-app", type=Path, required=True)
    p.add_argument("--catalog-entry", type=Path, required=True)
    p.add_argument("--app", required=True)
    p.add_argument("--train", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode", choices=("plan", "apply"), default="apply")
    p.add_argument("--evidence", type=Path)
    args = p.parse_args()

    try:
        with tempfile.TemporaryDirectory(prefix="foundry-overlay-package-") as tmp:
            desired = build_desired(
                args.published_app.resolve(),
                args.catalog_entry.resolve(),
                app=args.app,
                train=args.train,
                version=args.version,
                root=Path(tmp),
            )
            desired_fp = overlay_fingerprint(desired)
            destination = args.output.resolve()
            action, observed_fp = determine_action(destination, desired_fp)
            status = "PLANNED" if args.mode == "plan" else "PENDING"

            if args.mode == "apply":
                if action == "CREATE":
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(desired, destination)
                    if overlay_fingerprint(destination) != desired_fp:
                        raise OverlayError("post-copy overlay fingerprint mismatch")
                    status = "APPLIED"
                elif action == "NOOP":
                    status = "NOOP"
                else:
                    status = "REFUSED"

            receipt = {
                "schema": "semper-supra.truenas-catalog-overlay-package/1",
                "status": status,
                "action": action,
                "app": args.app,
                "train": args.train,
                "version": args.version,
                "desired_fingerprint": desired_fp,
                "observed_fingerprint": observed_fp or None,
                "secrets_captured": False,
            }
            payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            if args.evidence:
                args.evidence.write_text(payload, encoding="utf-8")
            print(payload, end="")
            return 0 if status != "REFUSED" else 3
    except OverlayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
