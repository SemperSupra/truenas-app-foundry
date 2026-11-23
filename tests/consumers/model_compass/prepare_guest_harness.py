#!/usr/bin/env python3
"""Build one disposable QEMU harness overlay without editing pinned vendor bytes.

This is an experiment-only source transform. It is NOT a replacement for the
authoritative upstream harness or a privileged product lifecycle executor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # tests/consumers/model_compass -> repository
VENDOR = ROOT / "tools/rdte/vendor/truenas-kvm"
SOURCE = "8744304c3c0a332460b1c5db97a2fb1e9562b222"
HARNESS = pathlib.Path("tools/rdte/vendor/truenas-kvm/scripts/gha_kvm_truenas_rdte.sh")
GUEST_PROBE = pathlib.Path("tools/rdte/vendor/truenas-kvm/scripts/truenas_middleware_compass_guest_transport_probe.py")


class OverlayError(RuntimeError):
    pass


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_vendor() -> dict:
    provenance = json.loads((VENDOR / "SOURCE-PROVENANCE.json").read_text(encoding="utf-8"))
    if provenance.get("source_commit") != SOURCE or provenance.get("supported_rung") != "t2":
        raise OverlayError("upstream TrueNAS KVM vendor pin drift")
    expected = provenance.get("files", {})
    if len(expected) != 6:
        raise OverlayError("vendored source inventory count changed")
    for name, expected_sha in expected.items():
        file = VENDOR / name
        if not file.is_file() or git_blob(file.read_bytes()) != expected_sha:
            raise OverlayError("upstream source-verbatim SHA mismatch: " + name)
    return provenance


def build(out: pathlib.Path) -> dict:
    provenance = verify_vendor()
    if out.exists():
        raise OverlayError("target overlay directory already exists; refusing overwrite")
    target_vendor = out / "tools/rdte/vendor/truenas-kvm"
    target_vendor.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(VENDOR, target_vendor)

    patch_path = HERE / "native_guest_harness.patch"
    patch = patch_path.read_text(encoding="utf-8")
    expected_title = f"diff --git a/{HARNESS} b/{HARNESS}"
    if patch.count("diff --git ") != 1 or not patch.startswith(expected_title):
        raise OverlayError("unbounded/nonmatching source overlay patch")
    if "\n--- a/" not in patch or "\n+++ b/" not in patch:
        raise OverlayError("incomplete or ambiguous patch")
    # Only affects the copied fixture; verified vendor bytes remain immutable.
    result = subprocess.run(
        ["patch", "--batch", "--fuzz=0", "--forward", "-p1", "-d", str(out), "-i", str(patch_path)],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode != 0:
        raise OverlayError("source-pinned test-only patch failed against exact vendor file")

    native = HERE / "truenas_native_guest_transport_probe.py"
    dest = out / GUEST_PROBE
    if dest.exists() or not native.is_file():
        raise OverlayError("unexpected guest probe source")
    shutil.copyfile(native, dest)
    harness = out / HARNESS
    original = VENDOR / "scripts/gha_kvm_truenas_rdte.sh"
    if git_blob(original.read_bytes()) != provenance["files"]["scripts/gha_kvm_truenas_rdte.sh"]:
        raise OverlayError("vendor source modified during overlay")

    for path in [harness, dest]:
        if not path.is_file() or path.stat().st_size == 0:
            raise OverlayError("generated native guest script missing")
    for command in (["bash", "-n", str(harness)],
                    [sys.executable, "-m", "py_compile", str(dest)]):
        check = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               timeout=20, check=False)
        if check.returncode:
            raise OverlayError("generated guest source syntax/compile failed")
    generated = harness.read_text(encoding="utf-8")
    for needle in ("model-compass", "native_compass_image_transport_exercised",
                   "COMPASS_HOSTFWD", "guest-image-transport"):
        if needle not in generated:
            raise OverlayError("missing native test boundary: " + needle)
    return {
        "schema": "foundry-native-compass-guest-overlay/v1",
        "classification": "SOURCE_OVERLAY_ONLY",
        "upstream_source_commit": SOURCE,
        "original_harness_git_blob": provenance["files"]["scripts/gha_kvm_truenas_rdte.sh"],
        "generated_harness_git_blob": git_blob(harness.read_bytes()),
        "guest_probe_git_blob": git_blob(dest.read_bytes()),
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "real_guest_HIL": "NOT_RUN",
        "product_F2_F6": "NOT_RUN",
        "upstream_modified": False,
        "site_modified": False,
    }


def main() -> int:
    arg = argparse.ArgumentParser()
    arg.add_argument("--out", type=pathlib.Path, required=True)
    arg.add_argument("--receipt", type=pathlib.Path)
    args = arg.parse_args()
    try:
        receipt = build(args.out)
    except (OverlayError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
