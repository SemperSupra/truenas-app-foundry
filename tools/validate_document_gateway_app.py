#!/usr/bin/env python3
"""Public qualification for the TrueNAS Document Gateway candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = REPO_ROOT / "candidates" / "document-gateway-app" / "candidate.json"
SOURCE = REPO_ROOT / "candidates" / "document-gateway-app" / "ix-dev" / "community" / "document-gateway"
APP = "document-gateway"
TRAIN = "community"
IMAGE = "chuckcharlie/cups-avahi-airprint:2.1.3"
FIXTURES = [
    "basic-values.yaml",
    "host-mdns-values.yaml",
    "external-lan-values.yaml",
    "cifs-fax-values.yaml",
]
CI_STATE = Path("/tmp/document-gateway-ci")


class ValidationError(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if check and cp.returncode:
        detail = (cp.stderr or cp.stdout or "")[-6000:]
        raise ValidationError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{detail}")
    return cp


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def checkout_upstream(root: Path, manifest: dict[str, Any]) -> Path:
    materializer = manifest["source_materializer"]
    checkout = root / "truenas-apps"
    run(["git", "init", "--quiet", str(checkout)])
    run(["git", "-C", str(checkout), "remote", "add", "origin", materializer["repository"]])
    run([
        "git", "-C", str(checkout), "fetch", "--quiet", "--depth", "1",
        "origin", materializer["commit"],
    ])
    run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
    actual = run(["git", "-C", str(checkout), "rev-parse", "HEAD"]).stdout.strip()
    if actual != materializer["commit"]:
        raise ValidationError(f"materializer drift: {actual} != {materializer['commit']}")
    return checkout


def install_candidate(checkout: Path, manifest: dict[str, Any]) -> Path:
    app_dir = checkout / "ix-dev" / TRAIN / APP
    if app_dir.exists():
        shutil.rmtree(app_dir)
    shutil.copytree(SOURCE, app_dir)

    lib_name = f"base_v{str(manifest['source_materializer']['lib_version']).replace('.', '_')}"
    lib_src = checkout / "ix-dev" / "community" / "ntfy" / "templates" / "library" / lib_name
    lib_dst = app_dir / "templates" / "library" / lib_name
    if not lib_src.is_dir():
        raise ValidationError(f"pinned library source missing: {lib_src}")
    shutil.copytree(lib_src, lib_dst)
    return app_dir


def render(checkout: Path, app_dir: Path, fixture: str) -> dict[str, Any]:
    run([
        "python3", ".github/scripts/ci.py",
        "--app", APP,
        "--train", TRAIN,
        "--test-file", fixture,
        "--render-only=true",
    ], cwd=checkout)
    rendered = app_dir / "templates" / "rendered" / "docker-compose.yaml"
    if not rendered.is_file():
        raise ValidationError(f"{fixture}: no rendered compose")
    cp = run([
        "docker", "compose", "-p", "foundry-document-gateway",
        "-f", str(rendered), "config", "--format", "json",
    ], cwd=checkout)
    try:
        compose = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{fixture}: compose normalization was not JSON") from exc
    compose.pop("name", None)
    return compose


def service_mounts(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mounts: dict[str, dict[str, Any]] = {}
    for value in service.get("volumes") or []:
        if isinstance(value, dict):
            mounts[str(value.get("target"))] = value
        elif isinstance(value, str):
            parts = value.split(":")
            if len(parts) >= 2:
                mounts[parts[1]] = {"source": parts[0], "target": parts[1], "type": "string"}
    return mounts


def assert_security(name: str, service: dict[str, Any]) -> None:
    if service.get("privileged"):
        raise ValidationError(f"{name}: privileged mode materialized")
    caps = {str(x).upper() for x in service.get("cap_drop") or []}
    if "ALL" not in caps:
        raise ValidationError(f"{name}: cap_drop ALL missing")
    opts = {str(x).lower().replace(":", "=") for x in service.get("security_opt") or []}
    if not any(x.startswith("no-new-privileges=true") for x in opts):
        raise ValidationError(f"{name}: no-new-privileges missing")
    if "docker.sock" in json.dumps(service):
        raise ValidationError(f"{name}: Docker socket leaked into candidate")


def config_content(compose: dict[str, Any], name: str) -> str:
    cfg = (compose.get("configs") or {}).get(name) or {}
    value = cfg.get("content")
    if not isinstance(value, str):
        raise ValidationError(f"config {name} missing inline content")
    return value


def assert_basic(compose: dict[str, Any]) -> None:
    services = compose.get("services") or {}
    if set(services) != {"cups", "normalizer"}:
        raise ValidationError(f"unexpected service inventory: {sorted(services)}")
    cups = services["cups"]
    norm = services["normalizer"]
    for name, svc in services.items():
        if svc.get("image") != IMAGE:
            raise ValidationError(f"{name}: image drift {svc.get('image')!r}")
        assert_security(name, svc)

    if cups.get("network_mode") == "host":
        raise ValidationError("safe default unexpectedly materialized host networking")
    ports = cups.get("ports") or []
    if not any(isinstance(p, dict) and int(p.get("target", 0)) == 631 for p in ports):
        raise ValidationError("safe default did not publish CUPS/IPP target 631")
    if norm.get("network_mode") != "none":
        raise ValidationError("normalizer must have network disabled")

    cups_mounts = service_mounts(cups)
    norm_mounts = service_mounts(norm)
    if set(cups_mounts) != {"/config", "/spool"}:
        raise ValidationError(f"CUPS mount contract drift: {sorted(cups_mounts)}")
    if set(norm_mounts) != {"/data", "/spool"}:
        raise ValidationError(f"normalizer mount contract drift: {sorted(norm_mounts)}")

    gateway_py = config_content(compose, "document-gateway-cups-script")
    norm_py = config_content(compose, "document-gateway-normalizer-script")
    gateway_cfg = json.loads(config_content(compose, "document-gateway-cups-config"))
    norm_cfg = json.loads(config_content(compose, "document-gateway-normalizer-config"))

    for needle in ("lpadmin", "cups-pdf:/", "printer-is-shared", "/spool/pdf"):
        if needle not in gateway_py:
            raise ValidationError(f"CUPS gateway script missing {needle!r}")
    if gateway_cfg["pdf_queue"] != "Save_to_Documents":
        raise ValidationError("virtual PDF queue contract drift")
    for needle in (
        'META = DATA / ".document-gateway"',
        'CONTRACT = META / "contract.json"',
        'STATUS = META / "status.json"',
        'JOURNAL = META / "events.jsonl"',
        "document_imported",
        "stable_seconds",
        "__{source}__",
    ):
        if needle not in norm_py:
            raise ValidationError(f"normalizer contract missing {needle!r}")
    if norm_cfg["fax_mode"] != "data_folder" or norm_cfg["sidecars"] is not True:
        raise ValidationError("basic normalizer configuration drift")


def assert_host_mdns(compose: dict[str, Any]) -> None:
    cups = compose["services"]["cups"]
    if cups.get("network_mode") != "host":
        raise ValidationError("host_mdns profile did not materialize host networking")
    if cups.get("ports"):
        raise ValidationError("host_mdns profile must not publish duplicate ports")


def assert_external_lan(compose: dict[str, Any]) -> None:
    cups = compose["services"]["cups"]
    nets = cups.get("networks") or {}
    item = nets.get("document-gateway-ci-lan") or {}
    if item.get("ipv4_address") != "172.30.80.10":
        raise ValidationError(f"external LAN static IP missing: {item!r}")
    top = (compose.get("networks") or {}).get("document-gateway-ci-lan") or {}
    if top.get("external") is not True:
        raise ValidationError("dedicated LAN network was not materialized as external")


def assert_cifs(compose: dict[str, Any]) -> None:
    norm = compose["services"]["normalizer"]
    mounts = service_mounts(norm)
    fax = mounts.get("/fax-source")
    if not fax or fax.get("read_only") is not True:
        raise ValidationError("CIFS fax source must be mounted read-only")

    source = str(fax.get("source") or "")
    volume = (compose.get("volumes") or {}).get(source) or {}
    opts = volume.get("driver_opts") or {}
    if opts.get("type") != "cifs":
        raise ValidationError(f"CIFS fax volume type did not materialize: {opts!r}")
    if opts.get("device") != "//192.0.2.1/fritz/fax":
        raise ValidationError(f"CIFS fax device drift: {opts.get('device')!r}")
    mount_opts = str(opts.get("o") or "")
    if "user=faxreader" not in mount_opts or "password=PublicQualificationOnly456!" not in mount_opts:
        raise ValidationError("CIFS fax credentials/options did not materialize in the qualification fixture")

    cfg = json.loads(config_content(compose, "document-gateway-cups-config"))
    printers = cfg.get("printers") or []
    if len(printers) != 1 or printers[0].get("queue_name") != "Brother_Office":
        raise ValidationError("physical-printer configuration did not materialize")
    if printers[0].get("driver") != "everywhere":
        raise ValidationError("driverless physical-printer default drift")


def find_question(questions: list[dict[str, Any]], variable: str) -> dict[str, Any]:
    for q in questions:
        if q.get("variable") == variable:
            return q
    raise ValidationError(f"questions.yaml missing top-level {variable!r}")


def find_attr(question: dict[str, Any], variable: str) -> dict[str, Any]:
    for a in ((question.get("schema") or {}).get("attrs") or []):
        if a.get("variable") == variable:
            return a
    raise ValidationError(f"{question.get('variable')}: missing attribute {variable!r}")


def assert_ux_contract() -> dict[str, Any]:
    data = yaml.safe_load((SOURCE / "questions.yaml").read_text(encoding="utf-8"))
    groups = {g["name"] for g in data.get("groups") or []}
    expected_groups = {
        "Gateway Basics", "Physical Printers", "Document Intake", "File Naming",
        "Network & Discovery", "Storage", "Resources",
    }
    if groups != expected_groups:
        raise ValidationError(f"human-facing group drift: {sorted(groups)}")

    questions = data.get("questions") or []
    gateway = find_question(questions, "gateway")
    printers = find_question(questions, "printers")
    usb = find_question(questions, "usb_enabled")
    intake = find_question(questions, "intake")
    naming = find_question(questions, "naming")
    network = find_question(questions, "network")
    storage = find_question(questions, "storage")

    if not (find_attr(gateway, "admin_password").get("schema") or {}).get("private"):
        raise ValidationError("CUPS password is not private in UI schema")
    if (find_attr(network, "mode").get("schema") or {}).get("default") != "published_ipp":
        raise ValidationError("safe IPP mode must remain default")
    if (find_attr(intake, "fax_mode").get("schema") or {}).get("default") != "data_folder":
        raise ValidationError("simple shared-folder fax intake must remain default")
    if (find_attr(naming, "style").get("schema") or {}).get("default") != "readable":
        raise ValidationError("human-readable naming must remain default")
    if (find_attr(naming, "sidecars").get("schema") or {}).get("default") is not False:
        raise ValidationError("per-file sidecars must remain opt-in")
    if (usb.get("schema") or {}).get("default") is not False:
        raise ValidationError("USB passthrough must remain opt-in")

    printer_item = ((printers.get("schema") or {}).get("items") or [None])[0]
    fields = {a.get("variable") for a in (((printer_item or {}).get("schema") or {}).get("attrs") or [])}
    for required in {"queue_name", "display_name", "device_uri", "driver", "shared"}:
        if required not in fields:
            raise ValidationError(f"physical-printer UX missing {required}")

    fax_cifs = find_attr(intake, "fax_cifs")
    cifs_password = next(
        (a for a in ((fax_cifs.get("schema") or {}).get("attrs") or []) if a.get("variable") == "password"),
        None,
    )
    if not cifs_password or not (cifs_password.get("schema") or {}).get("private"):
        raise ValidationError("FRITZ!Box SMB password is not private in UI schema")

    docs = find_attr(storage, "documents")
    docs_type = next(
        (a for a in ((docs.get("schema") or {}).get("attrs") or []) if a.get("variable") == "type"),
        None,
    )
    if not docs_type or (docs_type.get("schema") or {}).get("default") != "ix_volume":
        raise ValidationError("easy managed document storage must remain default")

    readme = (SOURCE / "README.md").read_text(encoding="utf-8")
    for heading in ("### Humans", "### Automation", "### Agents"):
        if heading not in readme:
            raise ValidationError(f"developer experience contract missing {heading}")

    return {
        "human_groups": sorted(groups),
        "safe_network_default": "published_ipp",
        "fax_default": "data_folder",
        "naming_default": "readable",
        "agent_contract_files": [
            "/data/.document-gateway/contract.json",
            "/data/.document-gateway/status.json",
            "/data/.document-gateway/events.jsonl",
        ],
    }


def wait_for(predicate, timeout: float, description: str) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        ok, last = predicate()
        if ok:
            return
        time.sleep(1)
    raise ValidationError(f"timeout waiting for {description}: {last}")


def runtime_smoke(checkout: Path, app_dir: Path) -> dict[str, Any]:
    shutil.rmtree(CI_STATE, ignore_errors=True)
    for sub in ("config", "spool", "documents"):
        (CI_STATE / sub).mkdir(parents=True, exist_ok=True)

    render(checkout, app_dir, "basic-values.yaml")
    rendered = app_dir / "templates" / "rendered" / "docker-compose.yaml"

    run(["docker", "pull", IMAGE])
    digests_raw = run(["docker", "image", "inspect", IMAGE, "--format", "{{json .RepoDigests}}"]).stdout.strip()
    try:
        repo_digests = json.loads(digests_raw)
    except json.JSONDecodeError:
        repo_digests = []

    project = "foundry-document-gateway-smoke"
    def dc(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run(["docker", "compose", "-p", project, "-f", str(rendered), *args], cwd=checkout, check=check)

    try:
        dc("up", "-d")

        def cups_ready():
            cp = dc("exec", "-T", "cups", "lpstat", "-p", "Save_to_Documents", check=False)
            return (cp.returncode == 0, (cp.stderr or cp.stdout)[-1000:])
        wait_for(cups_ready, 120, "virtual CUPS-PDF queue")

        print_cp = dc(
            "exec", "-T", "cups", "sh", "-ec",
            "printf 'Document Gateway Foundry smoke\\n' | lp -d Save_to_Documents -t FoundrySmoke",
            check=False,
        )
        if print_cp.returncode:
            raise ValidationError(f"virtual print submission failed: {(print_cp.stderr or print_cp.stdout)[-2000:]}")

        scan = CI_STATE / "documents" / "incoming" / "scan"
        fax = CI_STATE / "documents" / "incoming" / "fax"
        scan.mkdir(parents=True, exist_ok=True)
        fax.mkdir(parents=True, exist_ok=True)
        (scan / "Brother Scan 001.pdf").write_bytes(b"%PDF-1.4\\n% scan smoke\\n")
        (fax / "FRITZ Fax 001.pdf").write_bytes(b"%PDF-1.4\\n% fax smoke\\n")

        out = CI_STATE / "documents" / "output"
        def outputs_ready():
            files = [p.name for p in out.glob("*") if p.is_file() and not p.name.endswith(".json")]
            kinds = {k for k in ("print", "scan", "fax") if any(f"__{k}__" in x for x in files)}
            return (kinds == {"print", "scan", "fax"}, json.dumps(files))
        wait_for(outputs_ready, 120, "print/scan/fax normalized outputs")

        status_path = CI_STATE / "documents" / ".document-gateway" / "status.json"
        contract_path = CI_STATE / "documents" / ".document-gateway" / "contract.json"
        journal_path = CI_STATE / "documents" / ".document-gateway" / "events.jsonl"
        for p in (status_path, contract_path, journal_path):
            if not p.is_file():
                raise ValidationError(f"machine-readable contract artifact missing: {p}")

        status = load_json(status_path)
        contract = load_json(contract_path)
        if status.get("processed", 0) < 3 or status.get("errors") != 0:
            raise ValidationError(f"unexpected normalizer status: {status}")
        if contract.get("paths", {}).get("normalized_output") != "/data/output":
            raise ValidationError("runtime contract output path drift")

        out_names = sorted(p.name for p in out.glob("*") if p.is_file() and not p.name.endswith(".json"))
        pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}__(print|scan|fax)__.+")
        if not all(pattern.match(name) for name in out_names):
            raise ValidationError(f"non-conforming output filename: {out_names}")

        sidecars = sorted(p.name for p in out.glob("*.json"))
        if len(sidecars) < 3:
            raise ValidationError("sidecar-enabled smoke did not create metadata JSON files")

        events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        imported = [e for e in events if e.get("event") == "document_imported"]
        if {e.get("source") for e in imported} != {"print", "scan", "fax"}:
            raise ValidationError("event journal lacks all three source classes")

        return {
            "image_repo_digests": repo_digests,
            "virtual_pdf_queue": "PASS",
            "normalized_sources": ["fax", "print", "scan"],
            "output_names": out_names,
            "status_processed": status["processed"],
            "machine_contract": "PASS",
            "event_journal": "PASS",
            "sidecars": "PASS",
        }
    finally:
        dc("down", "-v", "--remove-orphans", check=False)
        shutil.rmtree(CI_STATE, ignore_errors=True)


def validate() -> dict[str, Any]:
    for tool in ("git", "docker", "python3"):
        if not shutil.which(tool):
            raise ValidationError(f"required tool missing: {tool}")

    manifest = load_json(CANDIDATE)
    ux = assert_ux_contract()
    root = Path(tempfile.mkdtemp(prefix="foundry-document-gateway-"))
    network_created = False
    try:
        checkout = checkout_upstream(root, manifest)
        app_dir = install_candidate(checkout, manifest)

        basic = render(checkout, app_dir, "basic-values.yaml")
        assert_basic(basic)

        host = render(checkout, app_dir, "host-mdns-values.yaml")
        assert_host_mdns(host)

        run(["docker", "network", "create", "--subnet", "172.30.80.0/24", "document-gateway-ci-lan"])
        network_created = True
        external = render(checkout, app_dir, "external-lan-values.yaml")
        assert_external_lan(external)

        cifs = render(checkout, app_dir, "cifs-fax-values.yaml")
        assert_cifs(cifs)

        smoke = runtime_smoke(checkout, app_dir)

        canonical = json.dumps(basic, sort_keys=True, separators=(",", ":")).encode()
        return {
            "result": "PASS",
            "candidate": "document-gateway-app",
            "materializer": manifest["source_materializer"],
            "image_tag": IMAGE,
            "basic_compose_sha256": hashlib.sha256(canonical).hexdigest(),
            "profiles": {
                "published_ipp": "PASS",
                "host_mdns": "PASS",
                "external_lan": "PASS",
                "cifs_fax": "PASS",
            },
            "ux_contract": ux,
            "runtime_smoke": smoke,
            "non_claims": [
                "no TrueNAS runtime realization",
                "no Brother hardware interoperability",
                "no FRITZ!Box hardware interoperability",
                "no LAN multicast/AirPrint discovery HIL",
                "OCI digest observed in CI is evidence; promotion still binds an exact approved digest",
            ],
        }
    finally:
        if network_created:
            run(["docker", "network", "rm", "document-gateway-ci-lan"], check=False)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=Path("document-gateway-evidence.json"))
    args = parser.parse_args()
    try:
        evidence = validate()
        payload = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        args.evidence.write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0
    except (ValidationError, OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
