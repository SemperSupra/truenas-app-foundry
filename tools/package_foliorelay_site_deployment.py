#!/usr/bin/env python3
"""Bind an exact FolioRelay T6 control bundle to one physical TrueNAS site.
Packaging only: no TrueNAS calls, storage creation, token creation, or support promotion.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, os, re
from pathlib import Path
from typing import Any
from package_truenas_deployment_artifact import ArtifactError, build_artifact, canonical_sha256

SCHEMA="semper-supra.foliorelay-truenas-t6-control/1"; OUT_SCHEMA="semper-supra.foliorelay-site-deployment/1"
VERSIONS={"25.04.1","25.04.2.6","25.10.7","26.0.0-BETA.3"}; AVAHI=VERSIONS-{"26.0.0-BETA.3"}
ORACLES={"app-create-running","config-readback-exact-compose","management-endpoint-ready","truenas-webui-portal-advertised","management-tls-ready","management-tls-identity-persistent","ipp-get-printer-attributes","canonical-uri-coherence","control-cups-dnssd-uuid-coherence","dnssd-universal-visible","pdf-exact-source-inbox","urf-exact-source-inbox","restart-preserves-identity-and-inbox","update-redeploy-preserves-identity-and-inbox","replan-noop","delete-zero-residue"}
HOST_RE=re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$")
class SiteError(RuntimeError): pass
CONTROL_SCHEMA=SCHEMA
EXPECTED_ORACLES=ORACLES
SiteBindingError=SiteError

def readj(p:Path)->dict[str,Any]:
    try: v=json.loads(p.read_text())
    except Exception as e: raise SiteError(f"cannot read {p.name}: {e}") from e
    if not isinstance(v,dict): raise SiteError(f"{p.name} must be an object")
    return v

def file_sha(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()
def flag(cmd:list[Any],name:str)->str|None:
    try: i=cmd.index(name); return cmd[i+1] if isinstance(cmd[i+1],str) else None
    except (ValueError,IndexError): return None
def setflag(cmd:list[Any],name:str,value:str)->None:
    try: cmd[cmd.index(name)+1]=value
    except (ValueError,IndexError) as e: raise SiteError(f"missing {name}") from e
def mounts(s:dict[str,Any],target:str)->list[dict[str,Any]]: return [x for x in s.get("volumes",[]) if isinstance(x,dict) and x.get("target")==target]
def one_mount(s:dict[str,Any],target:str)->dict[str,Any]:
    m=mounts(s,target)
    if len(m)!=1: raise SiteError(f"expected one mount for {target}")
    return m[0]
def has_port(s:dict[str,Any],p:int)->bool: return any(isinstance(x,dict) and x.get("target")==p and str(x.get("published"))==str(p) for x in s.get("ports",[]))
def req(cond:bool,msg:str)->None:
    if not cond: raise SiteError(msg)

def validate(bundle:Path,foundry:str,version:str,control_image:str,cups_image:str)->tuple[dict,dict]:
    ps={n:bundle/n for n in ("control.json","compose.json","publication-receipt.json","target-profile.json","values.yaml")}
    req(all(p.is_file() for p in ps.values()),"incomplete T6 bundle")
    c,comp,pub,target=readj(ps["control.json"]),readj(ps["compose.json"]),readj(ps["publication-receipt.json"]),readj(ps["target-profile.json"])
    cand=c.get("candidate") or {}; rt=c.get("runtime") or {}; art=c.get("artifacts") or {}
    req(c.get("schema")==SCHEMA and c.get("secrets_captured") is False,"not a sanitized T6 control")
    req(re.fullmatch(r"[0-9a-f]{40}",foundry or "") is not None and c.get("foundry_ref")==foundry,"Foundry ref mismatch")
    req(version in VERSIONS and cand.get("truenas_version")==version,"target version mismatch")
    req(cand.get("target_profile_id")==target.get("profile_id") and target.get("truenas_version")==version,"profile mismatch")
    req(cand.get("control_image")==control_image and cand.get("cups_image")==cups_image and "@sha256:" in control_image and "@sha256:" in cups_image,"image identity mismatch")
    req(set(c.get("required_oracles") or [])==ORACLES,"oracle contract drift")
    req(art.get("compose_canonical_sha256")==canonical_sha256(comp) and art.get("publication_receipt_sha256")==file_sha(ps["publication-receipt.json"]) and art.get("target_profile_sha256")==file_sha(ps["target-profile.json"]) and art.get("values_sha256")==file_sha(ps["values.yaml"]),"bundle hash mismatch")
    req(pub.get("status")=="PASS" and pub.get("source_revision")==cand.get("source_revision"),"publication authority mismatch")
    for n,img in (("control",control_image),("cups",cups_image)):
        r=pub.get(n) or {}; req(r.get("anonymous_pull") is True and r.get("signed_keyless") is True and f"{r.get('image')}@{r.get('digest')}"==img,f"{n} publication mismatch")
    svc=comp.get("services") or {}; req(set(svc)=={"control","cups","discovery"},"service set drift"); ctl,cups,disc=svc["control"],svc["cups"],svc["discovery"]
    req(ctl.get("image")==control_image and cups.get("image")==cups_image and disc.get("image")==control_image,"service image drift")
    for n,s in svc.items(): req(s.get("read_only") is True and s.get("cap_drop")==["ALL"] and "no-new-privileges:true" in (s.get("security_opt") or []),f"{n} security drift")
    req(has_port(ctl,18443) and not has_port(ctl,18080) and has_port(cups,8634),"published port drift")
    req(flag(ctl.get("command",[]),"-listen")=="0.0.0.0:18080" and flag(ctl.get("command",[]),"-https-listen")=="0.0.0.0:18443" and flag(ctl.get("command",[]),"-tls-state-dir")=="/var/lib/foliorelay-tls","listener/TLS drift")
    portal=comp.get("x-portals") or []; req(portal==[rt.get("management_portal")],"portal/runtime drift")
    host=portal[0].get("host"); req(flag(ctl.get("command",[]),"-printer-uri")==f"ipp://{host}:8634/printers/FolioRelay" and (cups.get("environment") or {}).get("FOLIORELAY_PUBLIC_HOST")==host,"public identity drift")
    req(disc.get("network_mode")=="host" and disc.get("healthcheck")=={"disable":True},"discovery runtime drift")
    if version in AVAHI:
        req(cand.get("discovery_backend")=="avahi" and disc.get("user")=="65534:10001" and flag(disc.get("command",[]),"-backend")=="avahi","Avahi contract drift")
        m=one_mount(disc,"/run/dbus/system_bus_socket"); req(m.get("source")=="/run/dbus/system_bus_socket" and m.get("read_only") is True,"D-Bus mount drift")
    else: req(cand.get("discovery_backend")=="direct" and "user" not in disc and not mounts(disc,"/run/dbus/system_bus_socket"),"direct discovery drift")
    req(one_mount(ctl,"/var/lib/foliorelay-tls").get("read_only") is False and not mounts(cups,"/var/lib/foliorelay-tls") and not mounts(disc,"/var/lib/foliorelay-tls"),"TLS mount isolation drift")
    req(rt.get("management_port")==18443 and rt.get("management_internal_port")==18080 and rt.get("ipp_port")==8634 and rt.get("management_scheme")=="https","runtime endpoint drift")
    return c,comp

def bind(c:dict,source:dict,app_name:str,data_root:str,token_file:str,public_host:str,printer_name:str,printer_location:str)->tuple[dict,dict]:
    root,token=Path(data_root),Path(token_file); req(root.is_absolute() and len(root.parts)>=3 and root.parts[1]=="mnt","data root must be beneath /mnt"); req(token==root/"secrets"/"control.token","token path must be <data-root>/secrets/control.token")
    host=public_host.rstrip(".").lower(); req(HOST_RE.fullmatch(host) is not None and host.endswith(".local") and host!="localhost.local","public host must be a .local name")
    req(bool(printer_name.strip()) and all(ord(x)>=32 and ord(x)!=127 for x in printer_name+printer_location),"invalid printer text")
    out=copy.deepcopy(source); svc=out["services"]; ctl,cups,disc=svc["control"],svc["cups"],svc["discovery"]; rt=c["runtime"]
    mp={rt["control_root"]:str(root/"control"),rt["management_tls_root"]:str(root/"tls"),rt["artifact_root"]:str(root/"artifacts"),rt["cups_state_root"]:str(root/"cups-state"),rt["cups_spool_root"]:str(root/"cups-spool"),rt["token_path"]:str(token)}
    for s in svc.values():
        for m in s.get("volumes",[]):
            if isinstance(m,dict) and m.get("source") in mp: m["source"]=mp[m["source"]]
    uri=f"ipp://{host}:8634/printers/FolioRelay"; setflag(ctl["command"],"-printer-uri",uri); setflag(ctl["command"],"-printer-name",printer_name); setflag(ctl["command"],"-printer-location",printer_location); cups["environment"]["FOLIORELAY_PUBLIC_HOST"]=host; out["x-portals"][0]["host"]=host
    cmode="0710" if c["candidate"]["discovery_backend"]=="avahi" else "0700"; specs=[("control",cmode),("tls","0700"),("artifacts","0700"),("cups-state","0755"),("cups-spool","0755"),("secrets","0700")]
    reqs=[{"path":str(root/n),"kind":"directory","uid":10001,"gid":10001,"mode":mode} for n,mode in specs]+[{"path":str(token),"kind":"file","uid":10001,"gid":10001,"mode":"0400"}]
    site={"schema":OUT_SCHEMA,"app_name":app_name,"truenas_version":c["candidate"]["truenas_version"],"foundry_ref":c["foundry_ref"],"source_control_sha256":canonical_sha256(c),"source_compose_sha256":c["artifacts"]["compose_canonical_sha256"],"site_compose_sha256":canonical_sha256(out),"control_image":c["candidate"]["control_image"],"cups_image":c["candidate"]["cups_image"],"discovery_backend":c["candidate"]["discovery_backend"],"public_printer_uri":uri,"management_portal":out["x-portals"][0],"host_path_requirements":reqs,"secrets_captured":False}
    return out,site

_validate_source=validate
bind_site=bind
def writej(p:Path,v:dict)->None: p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n"); os.chmod(p,0o600)
def main()->int:
    a=argparse.ArgumentParser(); a.add_argument("--control-dir",type=Path,required=True); a.add_argument("--expected-foundry-ref",required=True); a.add_argument("--expected-target-version",required=True); a.add_argument("--expected-control-image",required=True); a.add_argument("--expected-cups-image",required=True); a.add_argument("--app-name",required=True); a.add_argument("--data-root",required=True); a.add_argument("--token-file",required=True); a.add_argument("--public-host",required=True); a.add_argument("--printer-name",default="FolioRelay"); a.add_argument("--printer-location",default=""); a.add_argument("--out-dir",type=Path,required=True); x=a.parse_args()
    try:
        c,src=validate(x.control_dir,x.expected_foundry_ref,x.expected_target_version,x.expected_control_image,x.expected_cups_image); comp,site=bind(c,src,x.app_name,x.data_root,x.token_file,x.public_host,x.printer_name,x.printer_location)
        prov={"product":"FolioRelay","foundry_ref":c["foundry_ref"],"truenas_version":c["candidate"]["truenas_version"],"target_profile_id":c["candidate"]["target_profile_id"],"target_profile_sha256":c["artifacts"]["target_profile_sha256"],"control_image":c["candidate"]["control_image"],"cups_image":c["candidate"]["cups_image"],"source_control_sha256":site["source_control_sha256"],"source_compose_sha256":site["source_compose_sha256"],"site_binding_sha256":canonical_sha256(site)}; dep=build_artifact(x.app_name,comp,prov)
        x.out_dir.mkdir(parents=True,exist_ok=False); writej(x.out_dir/"compose.json",comp); writej(x.out_dir/"site-control.json",site); writej(x.out_dir/"deployment-artifact.json",dep)
        print(json.dumps({"status":"PASS","schema":OUT_SCHEMA,"app_name":x.app_name,"truenas_version":c["candidate"]["truenas_version"],"materialization_identity":dep["materialization_identity"],"artifact_sha256":dep["artifact_sha256"],"secrets_captured":False},sort_keys=True)); return 0
    except (SiteError,ArtifactError,OSError) as e: print(f"ERROR: {e}",file=os.sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
