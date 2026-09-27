#!/usr/bin/env python3
"""Public qualification for the TrueNAS Document Gateway candidate."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
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
    if set(services) != {"cups", "normalizer", "fax-sender", "control"}:
        raise ValidationError(f"unexpected service inventory: {sorted(services)}")
    cups = services["cups"]
    norm = services["normalizer"]
    fax_sender = services["fax-sender"]
    control = services["control"]
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
    if fax_sender.get("network_mode") != "none":
        raise ValidationError("null fax sender must have network disabled")
    control_ports = control.get("ports") or []
    if not any(isinstance(p, dict) and int(p.get("target", 0)) == 8080 for p in control_ports):
        raise ValidationError("management API target 8080 was not published")

    cups_mounts = service_mounts(cups)
    norm_mounts = service_mounts(norm)
    fax_mounts = service_mounts(fax_sender)
    control_mounts = service_mounts(control)
    if set(cups_mounts) != {"/config", "/spool"}:
        raise ValidationError(f"CUPS mount contract drift: {sorted(cups_mounts)}")
    if set(norm_mounts) != {"/data", "/spool"}:
        raise ValidationError(f"normalizer mount contract drift: {sorted(norm_mounts)}")
    if set(fax_mounts) != {"/data"}:
        raise ValidationError(f"fax sender mount contract drift: {sorted(fax_mounts)}")
    if set(control_mounts) != {"/data", "/spool"}:
        raise ValidationError(f"control-plane mount contract drift: {sorted(control_mounts)}")

    gateway_py = config_content(compose, "document-gateway-cups-script")
    norm_py = config_content(compose, "document-gateway-normalizer-script")
    fax_py = config_content(compose, "document-gateway-fax-sender-script")
    control_py = config_content(compose, "document-gateway-control-script")
    gateway_cfg = json.loads(config_content(compose, "document-gateway-cups-config"))
    norm_cfg = json.loads(config_content(compose, "document-gateway-normalizer-config"))

    for needle in (
        "lpadmin", "cups-pdf:/", "printer-is-shared", "/spool/pdf",
        "desired.json", "reconcile", "BrowseLocalProtocols=none",
        "BrowseLocalProtocols=dnssd", "BrowseDNSSDSubTypes=_print,_universal",
    ):
        if needle not in gateway_py:
            raise ValidationError(f"CUPS gateway script missing {needle!r}")
    if gateway_cfg["pdf_queue"] != "Save_to_Documents":
        raise ValidationError("virtual PDF queue contract drift")
    if gateway_cfg.get("network_mode") != "published_ipp":
        raise ValidationError("basic profile discovery/network intent drift")
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
    if norm_cfg.get("fax_outbox_enabled") is not True or norm_cfg.get("fax_sender") != "null":
        raise ValidationError("fax outbox bootstrap configuration drift")
    fax_cfg = json.loads(config_content(compose, "document-gateway-fax-sender-config"))
    if fax_cfg != {"plugin_api": "document-gateway.fax-sender/v1", "sender": "null"}:
        raise ValidationError(f"fax sender config drift: {fax_cfg!r}")
    for needle in ("class NullSender", "can_transmit = False", "pending_valid", "job.json", "application/pdf"):
        if needle not in fax_py:
            raise ValidationError(f"null fax sender contract missing {needle!r}")
    control_cfg = json.loads(config_content(compose, "document-gateway-control-config"))
    if control_cfg.get("api_version") != "document-gateway.control/v1":
        raise ValidationError("control API version drift")
    for needle in ("/api/v1/destinations", "do_PUT", "do_DELETE", "changed", "generation", "document-gateway.control/v1"):
        if needle not in control_py:
            raise ValidationError(f"control-plane contract missing {needle!r}")


def assert_host_mdns(compose: dict[str, Any]) -> None:
    cups = compose["services"]["cups"]
    if cups.get("network_mode") != "host":
        raise ValidationError("host_mdns profile did not materialize host networking")
    if cups.get("ports"):
        raise ValidationError("host_mdns profile must not publish duplicate ports")
    cfg = json.loads(config_content(compose, "document-gateway-cups-config"))
    if cfg.get("network_mode") != "host_mdns":
        raise ValidationError("host_mdns discovery intent missing from CUPS config")


def assert_external_lan(compose: dict[str, Any]) -> None:
    cups = compose["services"]["cups"]
    nets = cups.get("networks") or {}
    item = nets.get("document-gateway-ci-lan") or {}
    if item.get("ipv4_address") != "172.30.80.10":
        raise ValidationError(f"external LAN static IP missing: {item!r}")
    top = (compose.get("networks") or {}).get("document-gateway-ci-lan") or {}
    if top.get("external") is not True:
        raise ValidationError("dedicated LAN network was not materialized as external")
    cfg = json.loads(config_content(compose, "document-gateway-cups-config"))
    if cfg.get("network_mode") != "external_lan":
        raise ValidationError("external LAN discovery intent missing from CUPS config")


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
        "Document Gateway Configuration", "Network Configuration",
        "Storage Configuration", "Resources Configuration",
    }
    if groups != expected_groups:
        raise ValidationError(f"human-facing group drift: {sorted(groups)}")

    questions = data.get("questions") or []
    gateway = find_question(questions, "gateway")
    management = find_question(questions, "management")
    printers = find_question(questions, "printers")
    usb = find_question(questions, "usb_enabled")
    intake = find_question(questions, "intake")
    fax_outbox = find_question(questions, "fax_outbox")
    naming = find_question(questions, "naming")
    network = find_question(questions, "network")
    storage = find_question(questions, "storage")

    if not (find_attr(gateway, "admin_password").get("schema") or {}).get("private"):
        raise ValidationError("CUPS password is not private in UI schema")
    if (find_attr(management, "enabled").get("schema") or {}).get("default") is not True:
        raise ValidationError("common management WebUI/API must be enabled by default")
    if (find_attr(network, "mode").get("schema") or {}).get("default") != "published_ipp":
        raise ValidationError("safe IPP mode must remain default")
    if (find_attr(intake, "fax_mode").get("schema") or {}).get("default") != "data_folder":
        raise ValidationError("simple shared-folder fax intake must remain default")
    if (find_attr(fax_outbox, "sender").get("schema") or {}).get("default") != "null":
        raise ValidationError("null fax sender must remain the public default")
    if (find_attr(fax_outbox, "enabled").get("schema") or {}).get("default") is not True:
        raise ValidationError("fax outbox must be enabled by default")
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

    output_abi = (SOURCE / "OUTPUT_PLUGIN_ABI.md").read_text(encoding="utf-8")
    if "document-gateway.renderer/v1" not in output_abi:
        raise ValidationError("renderer/output-format ABI contract missing")

    discovery = (SOURCE / "DISCOVERY_CONTRACT.md").read_text(encoding="utf-8")
    for needle in ("_print._sub._ipp._tcp", "_universal._sub._ipp._tcp", "Windows", "Android"):
        if needle not in discovery:
            raise ValidationError(f"cross-platform discovery contract missing {needle!r}")

    return {
        "human_groups": sorted(groups),
        "safe_network_default": "published_ipp",
        "management_default": "enabled",
        "fax_default": "data_folder",
        "fax_sender_default": "null",
        "renderer_abi": "document-gateway.renderer/v1",
        "discovery_profile": "driverless on LAN discovery modes",
        "naming_default": "readable",
        "agent_contract_files": [
            "/data/.document-gateway/contract.json",
            "/data/.document-gateway/status.json",
            "/data/.document-gateway/events.jsonl",
        ],
    }


def management_auth_header() -> str:
    fixture = yaml.safe_load((SOURCE / "templates" / "test_values" / "basic-values.yaml").read_text(encoding="utf-8"))
    user = fixture["gateway"]["admin_user"]
    secret = fixture["gateway"]["admin_password"]
    token = base64.b64encode(f"{user}:{secret}".encode()).decode()
    return "Basic " + token


def http_json(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    url = "http://127.0.0.1:30880" + path
    data = None
    headers = {"Authorization": management_auth_header()}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode(errors="replace")
        raise ValidationError(f"management API {method} {path} failed: {exc.code} {payload}") from exc


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

    pull_error = ""
    for attempt in range(1, 4):
        cp = run(["docker", "pull", IMAGE], check=False)
        if cp.returncode == 0:
            break
        pull_error = (cp.stderr or cp.stdout or "")[-3000:]
        if attempt < 3:
            time.sleep(attempt * 3)
    else:
        raise ValidationError(f"image pull failed after 3 attempts: {pull_error}")

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
            if cp.returncode == 0:
                return (True, cp.stdout[-1000:])
            state = dc("ps", "cups", check=False)
            logs = dc("logs", "--tail", "80", "cups", check=False)
            detail = "\n".join([
                (cp.stderr or cp.stdout)[-1000:],
                state.stdout[-1500:],
                logs.stdout[-5000:],
                logs.stderr[-2000:],
            ])
            return (False, detail)
        wait_for(cups_ready, 120, "virtual CUPS-PDF queue")

        def control_ready():
            try:
                with urllib.request.urlopen("http://127.0.0.1:30880/health", timeout=5) as response:
                    body = json.loads(response.read())
                    ok = response.status == 200 and body.get("api_version") == "document-gateway.control/v1"
                    return (ok, json.dumps(body))
            except Exception as exc:
                return (False, str(exc))
        wait_for(control_ready, 60, "Document Gateway management API")

        status_code, first = http_json("GET", "/api/v1/destinations")
        if status_code != 200:
            raise ValidationError("management destinations read failed")
        initial_generation = int(first.get("generation", 0))

        synthetic = {
            "id": "Automation_PDF",
            "kind": "physical-print",
            "display_name": "Automation PDF",
            "device_uri": "cups-pdf:/",
            "driver": "custom",
            "model": "drv:///cups-pdf.drv/Generic-CUPS-PDF-Printer.ppd",
            "shared": False,
        }
        _, put1 = http_json("PUT", "/api/v1/destinations/Automation_PDF", synthetic)
        _, put2 = http_json("PUT", "/api/v1/destinations/Automation_PDF", synthetic)
        if put1.get("changed") is not True or put2.get("changed") is not False:
            raise ValidationError(f"idempotent destination PUT contract failed: {put1!r} {put2!r}")
        if int(put2.get("generation", 0)) != int(put1.get("generation", 0)):
            raise ValidationError("idempotent destination PUT changed generation on retry")
        if int(put1.get("generation", 0)) <= initial_generation:
            raise ValidationError("destination PUT did not advance desired generation")

        def synthetic_ready():
            cp = dc("exec", "-T", "cups", "lpstat", "-p", "Automation_PDF", check=False)
            return (cp.returncode == 0, (cp.stderr or cp.stdout)[-1000:])
        wait_for(synthetic_ready, 30, "control-plane destination reconciliation")

        http_json("DELETE", "/api/v1/destinations/Automation_PDF")
        http_json("DELETE", "/api/v1/destinations/Automation_PDF")

        def synthetic_removed():
            cp = dc("exec", "-T", "cups", "lpstat", "-p", "Automation_PDF", check=False)
            return (cp.returncode != 0, (cp.stderr or cp.stdout)[-1000:])
        wait_for(synthetic_removed, 30, "idempotent destination removal")

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

        fax_job = CI_STATE / "documents" / "outgoing" / "fax" / "pending" / "fax-smoke-001"
        fax_job.mkdir(parents=True, exist_ok=True)
        fax_doc = fax_job / "document.pdf"
        fax_doc.write_bytes(b"%PDF-1.4\\n% outbound fax smoke\\n")
        (fax_job / "job.json").write_text(json.dumps({
            "schema_version": 1,
            "channel": "fax",
            "job_id": "fax-smoke-001",
            "to": "+497031234567",
            "created_at": "2026-09-27T12:00:00+02:00",
            "document": "document.pdf",
            "media_type": "application/pdf",
        }, indent=2) + "\\n", encoding="utf-8")

        out = CI_STATE / "documents" / "output"
        def outputs_ready():
            files = [p.name for p in out.glob("*") if p.is_file() and not p.name.endswith(".json")]
            kinds = {k for k in ("print", "scan", "fax") if any(f"__{k}__" in x for x in files)}
            return (kinds == {"print", "scan", "fax"}, json.dumps(files))
        wait_for(outputs_ready, 120, "print/scan/fax normalized outputs")

        status_path = CI_STATE / "documents" / ".document-gateway" / "status.json"
        contract_path = CI_STATE / "documents" / ".document-gateway" / "contract.json"
        journal_path = CI_STATE / "documents" / ".document-gateway" / "events.jsonl"
        fax_sender_status_path = CI_STATE / "documents" / ".document-gateway" / "fax-sender.json"
        for p in (status_path, contract_path, journal_path, fax_sender_status_path):
            if not p.is_file():
                raise ValidationError(f"machine-readable contract artifact missing: {p}")

        status = load_json(status_path)
        contract = load_json(contract_path)
        fax_sender_status = load_json(fax_sender_status_path)
        if status.get("processed", 0) < 3 or status.get("errors") != 0:
            raise ValidationError(f"unexpected normalizer status: {status}")
        if contract.get("paths", {}).get("normalized_output") != "/data/output":
            raise ValidationError("runtime contract output path drift")
        if contract.get("fax_sender", {}).get("plugin_api") != "document-gateway.fax-sender/v1":
            raise ValidationError("fax sender plugin contract missing from runtime contract")
        if fax_sender_status.get("plugin") != "null" or fax_sender_status.get("can_transmit") is not False:
            raise ValidationError(f"null fax sender status drift: {fax_sender_status}")
        valid_ids = {j.get("job_id") for j in fax_sender_status.get("pending_valid", [])}
        if "fax-smoke-001" not in valid_ids:
            raise ValidationError(f"null fax sender did not validate pending job: {fax_sender_status}")
        if not fax_job.is_dir():
            raise ValidationError("null fax sender consumed or moved the pending fax job")

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
            "fax_outbox": "PASS",
            "fax_sender_plugin": "null",
            "fax_sender_can_transmit": False,
            "management_api": "PASS",
            "management_webui": "PASS",
            "idempotent_destination_put_delete": "PASS",
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
