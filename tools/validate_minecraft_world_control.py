#!/usr/bin/env python3
"""Public-safe H3 source-render control: externalize only /data/world."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / ".foundry" / "controls" / "minecraft-paper-upstream.json"
VALUES = ROOT / ".foundry" / "controls" / "minecraft-paper-world-hostpath-values.yaml"
VANILLA_PIN = ROOT / ".foundry/controls/minecraft-vanilla-263-11530-upstream.json"
VANILLA_11531_PIN = ROOT / ".foundry/controls/minecraft-vanilla-263-11531-upstream.json"
VANILLA_VALUES = ROOT / ".foundry/controls/minecraft-vanilla-263-world-hostpath-values.yaml"
WORLD_SOURCE = "/opt/tests/collage-world-only"
OWNERSHIP_ENV = {
    "SUPRACRAFT_COLLAGE_MANAGED": "true",
    "SUPRACRAFT_COLLAGE_SCHEMA": "1",
    "SUPRACRAFT_COLLAGE_MANAGER_ID": "manager-rdte",
    "SUPRACRAFT_COLLAGE_FLEET_ID": "rdte",
    "SUPRACRAFT_COLLAGE_SERVICE_ID": "11111111-1111-4111-8111-111111111111",
    "SUPRACRAFT_COLLAGE_WORLD_ID": "world-rdte-001",
}

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

def validate(*, pin_path=PIN, values_path=VALUES, expected_type="PAPER",
             expected_version="1.21.11", expected_selector="image",
             expected_world_path=WORLD_SOURCE, expected_ownership=OWNERSHIP_ENV):
    for tool in ("git","docker","python3"):
        if not shutil.which(tool):
            raise ValidationError("missing tool: "+tool)

    if pin_path not in (PIN, ROOT / '.foundry/controls/minecraft-paper-11530-upstream.json', VANILLA_PIN, VANILLA_11531_PIN):
        raise ValidationError('Unadmitted pinned Minecraft catalog profile')
    if pin_path in (VANILLA_PIN, VANILLA_11531_PIN):
        if (values_path != VANILLA_VALUES or expected_type != 'VANILLA'
                or expected_version != '26.3' or expected_selector != 'j25_image'
                or expected_world_path != '/opt/tests/collage-vanilla-263-world'):
            raise ValidationError('unadmitted vanilla 26.3 source configuration')
    elif values_path != VALUES or expected_type != 'PAPER' or expected_version != '1.21.11':
        raise ValidationError('legacy Paper source configuration drift')
    pin=json.loads(pin_path.read_text())
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
            "--values", str(values_path),
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

        test_name=("collage-vanilla263-world-hostpath-values.yaml" if expected_type=="VANILLA" else "collage-paper-world-hostpath-values.yaml")
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
        if env.get("TYPE")!=expected_type or env.get("VERSION")!=expected_version:
            raise ValidationError("exact Minecraft type/version not preserved")
        observed_ownership={
            key:value for key,value in env.items()
            if key.startswith("SUPRACRAFT_COLLAGE_")
        }
        if observed_ownership != expected_ownership:
            raise ValidationError(
                f"COLLAGE ownership metadata drift: {observed_ownership!r}"
            )

        all_mounts=mounts(service)
        data=[m for m in all_mounts if m["target"]=="/data"]
        world=[m for m in all_mounts if m["target"]=="/data/world"]
        if len(data)!=1:
            raise ValidationError(f"expected one base /data mount, got {data!r}")
        if len(world)!=1:
            raise ValidationError(f"expected one /data/world mount, got {world!r}")
        if data[0]["source"]==expected_world_path:
            raise ValidationError("world source incorrectly owns entire /data")
        if world[0]["source"]!=expected_world_path:
            raise ValidationError(f"world host path not preserved: {world[0]!r}")
        if world[0]["read_only"]:
            raise ValidationError("world mount unexpectedly read-only")
        if service.get("privileged"):
            raise ValidationError("privileged=true")
        for mount in all_mounts:
            if "/var/run/docker.sock" in mount["source"] or "/var/run/docker.sock" in mount["target"]:
                raise ValidationError("unexpected Docker socket")

        if expected_type=="VANILLA" and "image_selector: j25_image" not in values_path.read_text():
            raise ValidationError("Java25 selector drift")
        expected_image = pin.get("image")
        if service.get("image") != expected_image or "@sha256:" not in expected_image:
            raise ValidationError("pinned digest Minecraft image drift")
        if (expected_type=="VANILLA" and not expected_image.endswith("@sha256:5a2ab74ae179c11e2dbbce67f307cdcf2c1257b3abb0f654d3a310b3d8ea57da")):
            raise ValidationError("Java25 native catalog digest drift")
        expected_catalog_version = pin.get("catalog_version")
        version_yaml = checkout / "trains" / pin["train"] / "minecraft" / expected_catalog_version / "app.yaml"
        if not version_yaml.is_file() or f"version: {expected_catalog_version}" not in version_yaml.read_text():
            raise ValidationError("requested native catalog revision absent at pinned upstream commit")

        canonical=json.dumps(compose,sort_keys=True,separators=(",",":")).encode()
        return {
            "result":"PASS",
            "experiment":("SupraCraft vanilla26.3 Java25 exact native source-only render" if expected_type=="VANILLA" else "COLLAGE H3 world-only source-render control"),
            "trust_claim":"Pinned upstream TrueNAS Minecraft app can keep ordinary /data on App storage, independently mount a writable external world at /data/world, and carry bounded non-secret COLLAGE ownership/adoption metadata through its supported additional_envs surface",
            "upstream":{
                "repository":pin["repository"],
                "ref":ref,
                "app":"community/minecraft",
                "library_version":pin["library_version"],
                "library_hash":pin["library_hash"],
            },
            "server":{
                "type":env.get("TYPE"),
                "minecraft_version":env.get("VERSION"),
                "image_selector":expected_selector,
                "image_ref":service.get("image"),
                "catalog_version":expected_catalog_version,
                "base_data_mount":data[0],
                "world_mount":world[0],
                "ownership_metadata":observed_ownership,
            },
            "platform_normalization":{
                "dependency_identity_sha256":plan.get("dependency_identity_sha256"),
                "actions":actions,
            },
            "non_claims":[
                "no evidence of TrueNAS 25.04.2.6 runtime App lifecycle or current image OCI boot from source render alone",
                "no live TrueNAS qualification",
                "no proof yet that Paper creates/loads the world successfully through the nested mount",
                "no snapshot/clone or single-writer qualification",
                "no proof yet that TrueNAS app.query/GetAppWithConfig returns the persisted ownership metadata after live install or controller restart",
            ],
            "compose_sha256":hashlib.sha256(canonical).hexdigest(),
        }
    finally:
        shutil.rmtree(tmp,ignore_errors=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--product", choices=["paper-legacy", "vanilla-263"], default="paper-legacy")
    parser.add_argument("--target-version", default="25.04.1")
    parser.add_argument("--catalog-profile", choices=["1.15.29", "1.15.30", "1.15.31"],
                        default="1.15.29")
    args=parser.parse_args()
    pin_path=(PIN if args.catalog_profile=="1.15.29" else
              ROOT / '.foundry/controls/minecraft-paper-11530-upstream.json')
    try:
        if args.product == "vanilla-263":
            if args.target_version != "25.04.2.6" or args.catalog_profile not in ("1.15.30", "1.15.31"):
                raise ValidationError("vanilla 26.3 requires exact 25.04.2.6 target and pinned native catalog")
            target=json.loads((ROOT/".foundry/truenas-compatibility/25.04.2.6-materialization.json").read_text())
            if (target.get("truenas_version") != "25.04.2.6" or
                    target.get("middleware",{}).get("commit") != "244b717370fe35fb9eefc3096acfbc25f12b57b6"):
                raise ValidationError("exact target profile drift")
            evidence=validate(pin_path=(VANILLA_PIN if args.catalog_profile == "1.15.30" else VANILLA_11531_PIN),values_path=VANILLA_VALUES,
                expected_type="VANILLA", expected_version="26.3",
                expected_selector="j25_image",
                expected_world_path="/opt/tests/collage-vanilla-263-world",
                expected_ownership={**OWNERSHIP_ENV,"SUPRACRAFT_COLLAGE_WORLD_ID":"lantern-rdte"})
            evidence["truenas_target"]="25.04.2.6"
            evidence["runtime_qualification"]=False
        else:
            if args.target_version != "25.04.1":
                raise ValidationError("legacy control requires target 25.04.1")
            evidence=validate(pin_path=pin_path)
        payload=json.dumps(evidence,indent=2,sort_keys=True)+"\n"
        (ROOT/"minecraft-world-control-evidence.json").write_text(payload)
        print(payload,end="")
        return 0
    except (ValidationError,OSError,json.JSONDecodeError) as exc:
        print("ERROR: "+str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
