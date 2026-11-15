#!/usr/bin/env python3
"""Public GHA-only direct KVM capability check; no Agent Dispatch and no guest effect.

The syscall is KVM_GET_API_VERSION only (read-only capability inspection). No
KVM_CREATE_VM, scheduling service, TrueNAS API, ssh, credentials, or host mutation.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys

KVM_GET_API_VERSION = 0xAE00
EXPECTED_KVM_ABI = 12


def mem_total_mib() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) // 1024
    return 0


def observe() -> dict:
    report = {
        "schema": "foundry-direct-public-gha-kvm-preflight/v1",
        "classification": "public-read-only-host-preflight",
        "executor": "github-actions-native-ubuntu-x64",
        "agent_dispatch_used": False,
        "native_truenas_guest_started": False,
        "actual_app_f0_f5_qualified": False,
        "kvm_device": "/dev/kvm",
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "memory_total_mib": mem_total_mib(),
        "disk_free_gib": round(shutil.disk_usage(".").free / (1024**3), 2),
        "kvm_abi": None,
        "status": "BLOCKED",
        "blockers": [],
    }
    if report["machine"] != "x86_64":
        report["blockers"].append("host is not x86_64")
    if report["cpu_count"] is None or report["cpu_count"] < 2:
        report["blockers"].append("fewer than two CPUs")
    if report["memory_total_mib"] < 8192:
        report["blockers"].append("less than 8 GiB RAM for planned guest")
    if report["disk_free_gib"] < 40:
        report["blockers"].append("less than 40 GiB ephemeral disk free")
    try:
        entry = os.stat("/dev/kvm", follow_symlinks=False)
        if not stat.S_ISCHR(entry.st_mode):
            report["blockers"].append("/dev/kvm is not a character device")
        else:
            fd = os.open("/dev/kvm", os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
            try:
                abi = fcntl.ioctl(fd, KVM_GET_API_VERSION, 0)
                report["kvm_abi"] = abi
                if abi != EXPECTED_KVM_ABI:
                    report["blockers"].append("KVM ABI is not the expected version 12")
            finally:
                os.close(fd)
    except OSError as error:
        report["blockers"].append("KVM open/ioctl unavailable: " + type(error).__name__)
    if not report["blockers"]:
        report["status"] = "CAPABILITY_OBSERVED"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    report = observe()
    payload = json.dumps(report, sort_keys=True, indent=2) + "\n"
    args.evidence.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "CAPABILITY_OBSERVED" else 2


if __name__ == "__main__":
    sys.exit(main())
