#!/usr/bin/env python3
"""Official upstream-pinned iX source-render oracle for a non-deployable synthetic App.

Never runs a TrueNAS API call, pulls an image, or touches private product/source.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
PIN=ROOT/".foundry/truenas-apps-upstream.json"
SOURCE=ROOT/"candidates/agent-dispatch-app/ix-dev/community/agent-dispatch-synthetic"
NAME="agent-dispatch-synthetic"
CONTROL="agent-dispatch-rdte-control"
WORKER="agent-dispatch-rdte-worker"
IMAGE="registry.invalid/foundry-rdte/synthetic-go@sha256:"+"0"*64

class RenderFailure(RuntimeError): pass

def run(argv, cwd=None):
    r=subprocess.run(argv,cwd=cwd,text=True,capture_output=True,timeout=180,check=False)
    if r.returncode!=0:
        raise RenderFailure(f"{' '.join(argv)} failed ({r.returncode}): {(r.stderr or r.stdout)[-2500:]}")
    return r.stdout.strip()

def mount(service, target):
    found=[v for v in service.get("volumes",[]) if v.get("target")==target]
    if len(found)!=1: raise RenderFailure(f"{target}: mount count {len(found)}")
    return found[0]

def verify(compose):
    services=compose.get("services",{})
    if set(services)!={CONTROL,WORKER}:
        raise RenderFailure(f"unexpected services: {sorted(services)}")
    for label in (CONTROL,WORKER):
        item=services[label]
        if item.get("image")!=IMAGE: raise RenderFailure(f"{label}: image identity drift")
        if item.get("user")!="65532:65532": raise RenderFailure(f"{label}: root/UID drift")
        if item.get("read_only") is not True: raise RenderFailure(f"{label}: root writable")
        if item.get("privileged") is True or item.get("network_mode")=="host":
            raise RenderFailure(f"{label}: privileged host exposure")
        if "ALL" not in [str(v).upper() for v in item.get("cap_drop",[])]:
            raise RenderFailure(f"{label}: cap_drop ALL missing")
        opts=[str(v).lower().replace(":","=") for v in item.get("security_opt",[])]
        if not any(v.startswith("no-new-privileges=true") for v in opts):
            raise RenderFailure(f"{label}: no-new-privileges missing")
        for target,source,readonly in (
            ("/custody","/mnt/synthetic/agent-dispatch-rdte/custody",True),
            ("/ledger","/mnt/synthetic/agent-dispatch-rdte/ledger",False),
        ):
            m=mount(item,target)
            if m.get("type")!="bind" or m.get("source")!=source or m.get("read_only",False)!=readonly:
                raise RenderFailure(f"{label}: incorrect {target} external storage")
            if m.get("bind",{}).get("create_host_path") is True:
                raise RenderFailure(f"{label}: unexpected host path creation")
        if item.get("command")!=["serve" if label==CONTROL else "worker"]:
            raise RenderFailure(f"{label}: command drift")
        if any(v in json.dumps(item).lower() for v in ("docker.sock","/var/run/docker","/run/udev")):
            raise RenderFailure(f"{label}: forbidden host runtime socket")
    if services[WORKER].get("ports"):
        raise RenderFailure("worker unexpectedly exposes a port")
    ports=services[CONTROL].get("ports",[])
    if len(ports)!=1: raise RenderFailure("control requires one loopback port")
    port=ports[0]
    if str(port.get("target"))!="8080" or str(port.get("published"))!="18091" or port.get("host_ip")!="127.0.0.1":
        raise RenderFailure("control port must be loopback 18091->8080")
    return {"services": sorted(services), "loopback":True, "external_data_retained_by_contract":True}

def qualify():
    pin=json.loads(PIN.read_text(encoding="utf-8"))
    if pin.get("ref")!="532236882212e8c5e51d5b49cfe2c6ce3dd5675e" or pin.get("library_version")!="2.3.4":
        raise RenderFailure("shared Foundry upstream source identity changed")
    with tempfile.TemporaryDirectory(prefix="foundry-ad-ix-") as tmp:
        checkout=Path(tmp)/"apps"
        run(["git","init","--quiet",str(checkout)])
        run(["git","-C",str(checkout),"remote","add","origin",pin["repository"]])
        run(["git","-C",str(checkout),"fetch","--quiet","--depth","1","origin",pin["ref"]])
        run(["git","-C",str(checkout),"checkout","--quiet","--detach","FETCH_HEAD"])
        if run(["git","-C",str(checkout),"rev-parse","HEAD"])!=pin["ref"]:
            raise RenderFailure("upstream source SHA mismatch")
        target=checkout/"ix-dev/community"/NAME
        shutil.copytree(SOURCE,target)
        lib="base_v2_3_4"
        lib_src=checkout/"ix-dev/community/ntfy/templates/library"/lib
        if not lib_src.is_dir(): raise RenderFailure("pinned upstream ix_lib not found")
        shutil.copytree(lib_src,target/"templates/library"/lib)
        rendered_root=target/"templates/rendered"
        try:
            run(["python3",".github/scripts/ci.py","--app",NAME,"--train","community",
                 "--test-file","basic-values.yaml","--render-only=true"],cwd=checkout)
        finally:
            # Upstream validation Docker writes root-owned render output. Restore only
            # this disposable contained directory before TemporaryDirectory cleanup.
            if rendered_root.exists():
                if rendered_root.is_symlink() or not rendered_root.resolve().is_relative_to(checkout.resolve()):
                    raise RenderFailure("render output escapes disposable checkout")
                run(["sudo","-n","chown","-hR",f"{os.getuid()}:{os.getgid()}",str(rendered_root)])
        rendered=rendered_root/"docker-compose.yaml"
        if not rendered.is_file():raise RenderFailure("missing upstream rendered compose")
        output=run(["docker","compose","-p","foundry-ad-synthetic","-f",str(rendered),"config","--format","json"])
        compose=json.loads(output)
        verdict=verify(compose)
        packed=json.dumps(compose,sort_keys=True,separators=(",",":")).encode()
        return {"result":"PASS","classification":"public-source-render-only","upstream_sha":pin["ref"],
                "library_version":pin["library_version"],"compose_sha256":hashlib.sha256(packed).hexdigest(),
                **verdict,
                "not_claimed":["private Go image","host custody","native TrueNAS Apps F0-F5","live migration","catalog publication"]}

if __name__=="__main__":
    try:
        print(json.dumps(qualify(),sort_keys=True,indent=2))
    except (RenderFailure,OSError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
        print(json.dumps({"result":"FAIL","classification":"public-source-render-only",
                          "diagnostic":str(exc)[-1800:]},sort_keys=True))
        raise SystemExit(1)
