#!/usr/bin/env python3
"""Public-safe H3 source-render control: externalize only /data/world."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / ".foundry" / "truenas-apps-upstream.json"
VALUES = ROOT / ".foundry" / "controls" / "minecraft-paper-world-hostpath-values.yaml"
WORLD_SOURCE = "/opt/tests/collage-world-only"

class ValidationError(RuntimeError):
    pass

def run(cmd, cwd):
    print("+ " + " ".join(cmd), file=sys.stderr)
    cp = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if cp.returncode:
        detail = (cp.stdout or "") + "\n--- STDERR ---\n" + (cp.stderr or "")
        raise ValidationError(detail[-8000:])
    return cp

def mounts(service):
    out=[]
    for item in service.get("volumes") or []:
        if isinstance(item, dict):
            out.append({
                "source":str(item.get("source") or ""),
                "target":str(item.get("target") or ""),
                "read_only":bool(item.get("read_only",False)),
            })
        elif isinstance(item,str):
            parts=item.split(":")
            if len(parts)>=2:
                out.append({
                    "source":parts[0],
                    "target":parts[1],
                    "read_only":len(parts)>2 and "ro" in parts[2].split(","),
                })
    return out

def envmap(service):
    env=service.get("environment") or {}
    if isinstance(env,dict):
        return {str(k):str(v) for k,v in env.items()}
    out={}
    for item in env:
        k,sep,v=str(item).partition("=")
        if sep:
            out[k]=v
    return out

def validate():
    for tool in ("git","docker","python3"):
        if not shutil.which(tool):
            raise ValidationError("missing tool: "+tool)

    pin=json.loads(PIN.read_text())
    ref=str(pin["ref"])
    tmp=Path(tempfile.mkdtemp(prefix="collage-world-control-"))
    try:
        checkout=tmp/"apps"
        run(["git","init","--quiet",str(checkout)],tmp)
        run(["git","-C",str(checkout),"remote","add","origin",pin["repository"]],tmp)
        run(["git","-C",str(checkout),"fetch","--quiet","--depth","1","origin",ref],tmp)
        run(["git","-C",str(checkout),"checkout","--quiet","--detach","FETCH_HEAD"],tmp)
        actual=run(["git","-C",str(checkout),"rev-parse","HEAD"],tmp).stdout.strip()
        if actual != ref:
            raise ValidationError("upstream checkout mismatch")

        app=checkout/"ix-dev"/pin["train"]/"minecraft"
        app_yaml=(app/"app.yaml").read_text()
        if f"lib_version: {pin['library_version']}" not in app_yaml:
            raise ValidationError("library version drift")
        if f"lib_version_hash: {pin['library_hash']}" not in app_yaml:
            raise ValidationError("library hash drift")

        resolved = tmp / "resolved.json"
        resolved.write_text(json.dumps({
            "timezones": {"Etc/UTC": "Etc/UTC"},
            "ix_volumes": {
                "data": {
                    "host_path": "/opt/tests/collage-server-data",
                    "properties": {}
                }
            }
        }), encoding="utf-8")
        normalized = tmp / "normalized-values.yaml"
        platform_plan = tmp / "platform-plan.json"
        run([
            "python3", str(ROOT / "tools" / "prepare_truenas_platform_values.py"),
            "--questions", str(app / "questions.yaml"),
            "--values", str(VALUES),
            "--resolved", str(resolved),
            "--output-values", str(normalized),
            "--plan", str(platform_plan),
        ], ROOT)
        plan = json.loads(platform_plan.read_text(encoding="utf-8"))
        actions = plan.get("actions") or []
        if not any(
            action.get("action") == "ensure-ix-volume"
            and action.get("dataset_name") == "data"
            for action in actions
        ):
            raise ValidationError("platform normalization did not plan the base data ixVolume")
        if "/opt/tests/collage-server-data" in json.dumps(plan, sort_keys=True):
            raise ValidationError("sanitized platform plan leaked the resolved host path")

        test_name="collage-paper-world-hostpath-values.yaml"
        shutil.copyfile(normalized, app/"templates"/"test_values"/test_name)
        run([
            "python3",".github/scripts/ci.py",
            "--app","minecraft","--train",pin["train"],
            "--test-file",test_name,"--render-only=true",
        ],checkout)

        rendered=app/"templates"/"rendered"/"docker-compose.yaml"
        cp=run([
            "docker","compose","-p","foundry-collage-world",
            "-f",str(rendered),"config","--format","json",
        ],checkout)
        compose=json.loads(cp.stdout)
        compose.pop("name",None)
        service=(compose.get("services") or {}).get("minecraft")
        if not isinstance(service,dict):
            raise ValidationError("minecraft service missing")

        env=envmap(service)
        if env.get("TYPE")!="PAPER":
            raise ValidationError("TYPE=PAPER not preserved")

        all_mounts=mounts(service)
        data=[m for m in all_mounts if m["target"]=="/data"]
        world=[m for m in all_mounts if m["target"]=="/data/world"]
        if len(data)!=1:
            raise ValidationError(f"expected one base /data mount, got {data!r}")
        if len(world)!=1:
            raise ValidationError(f"expected one /data/world mount, got {world!r}")
        if data[0]["source"]==WORLD_SOURCE:
            raise ValidationError("world source incorrectly owns entire /data")
        if world[0]["source"]!=WORLD_SOURCE:
            raise ValidationError(f"world host path not preserved: {world[0]!r}")
        if world[0]["read_only"]:
            raise ValidationError("world mount unexpectedly read-only")
        if service.get("privileged"):
            raise ValidationError("privileged=true")
        for mount in all_mounts:
            if "/var/run/docker.sock" in mount["source"] or "/var/run/docker.sock" in mount["target"]:
                raise ValidationError("unexpected Docker socket")

        canonical=json.dumps(compose,sort_keys=True,separators=(",",":")).encode()
        return {
            "result":"PASS",
            "experiment":"COLLAGE H3 world-only source-render control",
            "trust_claim":"Pinned upstream TrueNAS Minecraft app can keep ordinary /data on App storage while independently mounting a writable external world at /data/world",
            "upstream":{
                "repository":pin["repository"],
                "ref":ref,
                "app":"community/minecraft",
                "library_version":pin["library_version"],
                "library_hash":pin["library_hash"],
            },
            "server":{
                "type":env.get("TYPE"),
                "base_data_mount":data[0],
                "world_mount":world[0],
            },
            "platform_normalization":{
                "dependency_identity_sha256":plan.get("dependency_identity_sha256"),
                "actions":actions,
            },
            "non_claims":[
                "no live TrueNAS qualification",
                "no proof yet that Paper creates/loads the world successfully through the nested mount",
                "no snapshot/clone or single-writer qualification",
            ],
            "compose_sha256":hashlib.sha256(canonical).hexdigest(),
        }
    finally:
        shutil.rmtree(tmp,ignore_errors=True)

def main():
    try:
        evidence=validate()
        payload=json.dumps(evidence,indent=2,sort_keys=True)+"\n"
        (ROOT/"minecraft-world-control-evidence.json").write_text(payload)
        print(payload,end="")
        return 0
    except (ValidationError,OSError,json.JSONDecodeError) as exc:
        print("ERROR: "+str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
