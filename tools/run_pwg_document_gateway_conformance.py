#!/usr/bin/env python3
"""Run the PWG IPP Everywhere v1.1 source-built suite as engineering evidence."""
from __future__ import annotations

import argparse
import json
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path


def run(cmd: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if cp.stdout:
        print(cp.stdout, end="")
    if cp.stderr:
        print(cp.stderr, file=sys.stderr, end="")
    if check and cp.returncode:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(cmd)}")
    return cp


def discover_name(timeout: int) -> str:
    deadline = time.time() + timeout
    pattern = re.compile(r"(?:/printers/|/ipp/print/).*Save_to_Documents$")
    last = ""
    while time.time() < deadline:
        cp = subprocess.run(
            ["ippfind", "_ipp._tcp,_print.local.", "--print-name", "-T", "2"],
            text=True, capture_output=True, check=False,
        )
        last = (cp.stderr or cp.stdout or "").strip()
        names = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
        for name in names:
            probe = subprocess.run(
                ["ippfind", "_ipp._tcp,_print.local.", "--literal-name", name, "--print", "-T", "2"],
                text=True, capture_output=True, check=False,
            )
            if any(pattern.search(line.strip()) for line in probe.stdout.splitlines()):
                return name
        time.sleep(1)
    raise RuntimeError(f"DNS-SD service for Save_to_Documents not found: {last}")


def plist_result(path: Path) -> dict:
    if not path.is_file():
        return {"result": "FAIL", "reason": "result plist missing", "path": str(path)}
    with path.open("rb") as fh:
        data = plistlib.load(fh)
    successful = bool(data.get("Successful", False))
    tests = data.get("Tests") or []
    failures = [
        test.get("Name", "unnamed")
        for test in tests
        if isinstance(test, dict) and test.get("Successful") is False
    ]
    skipped = [
        test.get("Name", "unnamed")
        for test in tests
        if isinstance(test, dict) and test.get("Skipped") is True
    ]
    return {
        "result": "PASS" if successful else "FAIL",
        "successful": successful,
        "tests": len(tests),
        "failures": failures,
        "skipped": skipped,
        "path": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selfcert", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--discovery-timeout", type=int, default=45)
    args = parser.parse_args()

    root = args.selfcert.resolve()
    tests = root / "tests"
    service = discover_name(args.discovery_timeout)

    suites = [
        ("dnssd", "dnssd-tests.sh", tests / f"{service} DNS-SD Results.plist"),
        ("ipp", "ipp-tests.sh", tests / f"{service} IPP Results.plist"),
        ("document", "document-tests.sh", tests / f"{service} Document Results.plist"),
    ]

    results = {}
    commands = {}
    for suite, script, plist in suites:
        cp = run([str(root / "runtests.sh"), script, service], cwd=root)
        commands[suite] = {"returncode": cp.returncode}
        results[suite] = plist_result(plist)

    evidence = {
        "result": "PASS" if all(v["result"] == "PASS" for v in results.values()) else "FAIL",
        "claim": "engineering conformance evidence; not PWG certification",
        "service_name": service,
        "pwg_suite": {
            "standard": "PWG 5100.14-2020 IPP Everywhere v1.1",
            "manual": "PWG 5100.20-2020",
            "source_ref": "af2b5887854e86888b8bed25bf2c0dd3c5c25614",
        },
        "commands": commands,
        "suites": results,
    }
    args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
