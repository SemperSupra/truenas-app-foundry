#!/usr/bin/env python3
"""Bind normalized Compose IR to one TrueNAS site using declarative exact patches.

This is product-neutral packaging only. It performs no host calls, creates no
storage or secrets, and grants no mutation authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from package_truenas_deployment_artifact import ArtifactError, build_artifact, canonical_sha256

SCHEMA="truenas-foundry-site-binding/v1"
RECEIPT_SCHEMA="truenas-foundry-site-binding-receipt/v1"
MODE_RE=re.compile(r"^0[0-7]{3}$")

class BindingError(RuntimeError):
    pass

def load(path:Path,label:str)->dict[str,Any]:
    try: value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise BindingError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value,dict): raise BindingError(f"{label} must be an object")
    return value

def pointer_tokens(pointer:str)->list[str]:
    if not isinstance(pointer,str) or not pointer.startswith("/") or pointer=="/":
        raise BindingError("patch path must be a non-root JSON Pointer")
    return [x.replace("~1","/").replace("~0","~") for x in pointer[1:].split("/")]

def get_parent(root:Any,pointer:str)->tuple[Any,str]:
    toks=pointer_tokens(pointer)
    cur=root
    for token in toks[:-1]:
        if isinstance(cur,list):
            try: idx=int(token)
            except ValueError as exc: raise BindingError(f"array pointer segment is not an integer: {pointer}") from exc
            if idx<0 or idx>=len(cur): raise BindingError(f"array pointer out of range: {pointer}")
            cur=cur[idx]
        elif isinstance(cur,dict):
            if token not in cur: raise BindingError(f"pointer path is absent: {pointer}")
            cur=cur[token]
        else:
            raise BindingError(f"pointer traverses a scalar: {pointer}")
    return cur,toks[-1]

def exact_patch(root:Any,pointer:str,expected:Any,value:Any)->None:
    parent,key=get_parent(root,pointer)
    if isinstance(parent,list):
        try: idx=int(key)
        except ValueError as exc: raise BindingError(f"array pointer segment is not an integer: {pointer}") from exc
        if idx<0 or idx>=len(parent): raise BindingError(f"array pointer out of range: {pointer}")
        actual=parent[idx]
        if actual!=expected: raise BindingError(f"patch expected-value mismatch: {pointer}")
        parent[idx]=copy.deepcopy(value)
    elif isinstance(parent,dict):
        if key not in parent: raise BindingError(f"patch path is absent: {pointer}")
        if parent[key]!=expected: raise BindingError(f"patch expected-value mismatch: {pointer}")
        parent[key]=copy.deepcopy(value)
    else:
        raise BindingError(f"patch parent is scalar: {pointer}")

def validate_resource(item:Any)->dict[str,Any]:
    if not isinstance(item,dict): raise BindingError("host resource must be an object")
    allowed={"path","kind","uid","gid","mode","ownership","retain_on_remove","content_policy"}
    if set(item)-allowed: raise BindingError("host resource has unsupported keys")
    path=str(item.get("path") or "")
    p=Path(path)
    if not p.is_absolute() or len(p.parts)<3 or p.parts[1]!="mnt":
        raise BindingError("host resource path must be beneath /mnt")
    kind=item.get("kind")
    if kind not in {"directory","file"}: raise BindingError("host resource kind must be directory|file")
    uid=item.get("uid"); gid=item.get("gid")
    if not isinstance(uid,int) or uid<0 or not isinstance(gid,int) or gid<0:
        raise BindingError("host resource uid/gid must be non-negative integers")
    mode=str(item.get("mode") or "")
    if MODE_RE.fullmatch(mode) is None: raise BindingError("host resource mode must be a four-digit octal string")
    ownership=item.get("ownership")
    if ownership not in {"foundry-owned","external-existing"}:
        raise BindingError("host resource ownership must be foundry-owned|external-existing")
    retain=item.get("retain_on_remove")
    if not isinstance(retain,bool): raise BindingError("retain_on_remove must be boolean")
    policy=item.get("content_policy")
    if kind=="directory" and policy is not None:
        raise BindingError("directory cannot carry content_policy")
    if kind=="file":
        if not isinstance(policy,dict): raise BindingError("file requires content_policy")
        ptype=policy.get("kind")
        if ptype=="generated-random-base64":
            if set(policy)!={"kind","bytes"}:
                raise BindingError("generated-random-base64 content policy has extra keys")
            count=policy.get("bytes")
            if not isinstance(count,int) or count<16 or count>4096:
                raise BindingError("generated secret byte count outside 16..4096")
        elif ptype=="external-existing":
            if set(policy)!={"kind"}: raise BindingError("external-existing content policy has extra keys")
        else:
            raise BindingError("unsupported file content_policy")
    return copy.deepcopy(item)

def bind(compose:dict[str,Any],spec:dict[str,Any])->tuple[dict[str,Any],list[dict[str,Any]]]:
    if spec.get("schema")!=SCHEMA: raise BindingError("unsupported site-binding schema")
    expected=str(spec.get("expected_base_compose_sha256") or "")
    actual=canonical_sha256(compose)
    if expected!=actual: raise BindingError("base Compose identity mismatch")
    patches=spec.get("patches",[])
    if not isinstance(patches,list): raise BindingError("patches must be an array")
    pointers=set()
    out=copy.deepcopy(compose)
    for item in patches:
        if not isinstance(item,dict) or set(item)!={"path","expected","value"}:
            raise BindingError("each patch must contain exactly path/expected/value")
        path=item["path"]
        if path in pointers: raise BindingError(f"duplicate patch path: {path}")
        pointers.add(path)
        exact_patch(out,path,item["expected"],item["value"])
    resources=spec.get("host_resources",[])
    if not isinstance(resources,list): raise BindingError("host_resources must be an array")
    checked=[validate_resource(x) for x in resources]
    resource_paths=[x["path"] for x in checked]
    if len(resource_paths)!=len(set(resource_paths)): raise BindingError("duplicate host resource path")
    return out,checked

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--compose",type=Path,required=True)
    p.add_argument("--binding",type=Path,required=True)
    p.add_argument("--provenance",type=Path)
    p.add_argument("--out-dir",type=Path,required=True)
    args=p.parse_args()
    try:
        compose=load(args.compose,"Compose")
        if not isinstance(compose.get("services"),dict) or not compose["services"]:
            raise BindingError("Compose services must be non-empty")
        spec=load(args.binding,"site binding")
        bound,resources=bind(compose,spec)
        app_name=str(spec.get("app_name") or "")
        provenance=load(args.provenance,"provenance") if args.provenance else {}
        provenance=copy.deepcopy(provenance or {})
        provenance["site_binding"]={
            "schema":SCHEMA,
            "binding_sha256":canonical_sha256(spec),
            "base_compose_sha256":canonical_sha256(compose),
        }
        artifact=build_artifact(app_name,bound,provenance)
        artifact["site_requirements"]={
            "schema":"truenas-foundry-site-requirements/v1",
            "host_resources":resources,
        }
        body=dict(artifact); body.pop("artifact_sha256",None)
        artifact["artifact_sha256"]=canonical_sha256(body)
        receipt={
            "schema":RECEIPT_SCHEMA,
            "status":"PASS",
            "app_name":app_name,
            "base_compose_sha256":canonical_sha256(compose),
            "bound_compose_sha256":canonical_sha256(bound),
            "binding_sha256":canonical_sha256(spec),
            "materialization_identity":artifact["materialization_identity"],
            "artifact_sha256":artifact["artifact_sha256"],
            "host_resource_count":len(resources),
            "secrets_captured":False,
            "mutation_performed":False,
        }
        args.out_dir.mkdir(parents=True,exist_ok=False)
        for name,value in (("compose.json",bound),("deployment-artifact.json",artifact),("binding-receipt.json",receipt)):
            path=args.out_dir/name
            path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
            os.chmod(path,0o600)
        print(json.dumps(receipt,sort_keys=True))
        return 0
    except (BindingError,ArtifactError,OSError,ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}",file=os.sys.stderr)
        return 2

if __name__=="__main__": raise SystemExit(main())
