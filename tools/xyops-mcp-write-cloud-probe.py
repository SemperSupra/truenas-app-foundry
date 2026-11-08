#!/usr/bin/env python3
"""Bounded cloud-only xyCLI MCP write/optimistic-concurrency qualification.

A fresh, restricted API key is created INSIDE disposable GitHub Actions CI.
All saved schedules contain an inert script and MANUAL trigger only; no
production credentials, remote listeners, Agent Dispatch or WOW integration.
"""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

OUT=Path("evidence"); OUT.mkdir(exist_ok=True)
BASE="http://127.0.0.1:15522"
MCP="http://127.0.0.1:18080/mcp"
jar=http.cookiejar.CookieJar()
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
session=None
csrf=None
checks=[]

def request(url,payload=None,headers=None):
    hdr=dict(headers or {})
    if payload is not None: hdr.setdefault("Content-Type","application/json")
    req=urllib.request.Request(url,headers=hdr,data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with client.open(req,timeout=25) as r: return r.status,r.headers.get("content-type",""),r.read(800000)
    except urllib.error.HTTPError as e: return e.code,e.headers.get("content-type",""),e.read(800000)

def api(path,payload=None):
    headers={}
    if session: headers["X-Session-ID"]=session
    if csrf and payload is not None:headers["X-CSRF-Token"]=csrf
    code,_,raw=request(BASE+path,payload,headers)
    try: data=json.loads(raw)
    except Exception:raise RuntimeError(f"API {path}: invalid JSON HTTP {code}")
    if code!=200 or data.get("code")!=0:
        raise RuntimeError(f"API {path}: HTTP {code}, app {data.get('code')}, {str(data.get('description'))[:120]}")
    return data

def rpc(method,params,id,key):
    headers={"Accept":"application/json, text/event-stream","Content-Type":"application/json",
             "Authorization":"Bearer "+key}
    code,ct,raw=request(MCP,{"jsonrpc":"2.0","id":id,"method":method,"params":params},headers)
    data=None
    if "text/event-stream" in ct:
        for line in raw.decode("utf-8","replace").splitlines():
            if line.startswith("data:"):
                try: value=json.loads(line[5:].strip())
                except Exception:continue
                if value.get("id")==id: data=value;break
    else:
        try:data=json.loads(raw)
        except Exception:pass
    return code,data

def note(condition,label,detail=None):
    checks.append({"name":label,"pass":bool(condition),**({"detail":detail} if detail is not None else {})})
    if not condition:raise RuntimeError(label+" failed"+(" ("+str(detail)[:160]+")" if detail is not None else ""))

def tool(key,name,arguments,id):
    status,data=rpc("tools/call",{"name":name,"arguments":arguments},id,key)
    value=(data or {}).get("result") or {}
    if status!=200 or (data or {}).get("error") or value.get("isError"):
        excerpt=" ".join(str(x.get("text","")) for x in value.get("content",[]) if isinstance(x,dict))
        excerpt=excerpt.replace(key,"<secret>")[:200]
        return False,{"status":status,"message":excerpt,"protocol_error":(data or {}).get("error")}
    return True,value.get("structuredContent") or {}

def run():
    global session,csrf
    login=api("/api/user/login",{"username":"admin","password":"admin"})
    session=login.get("session_id"); csrf=login.get("csrf_token")
    note(bool(session or list(jar)) and bool(csrf),"local-only login with CSRF")
    grant=api("/api/app/create_api_key/v1",{
      "title":"RDTE schedule-write permission probe","active":1,
      "privileges":{"admin":0,"create_events":1,"edit_events":1,"delete_events":1,"run_jobs":0},
      "roles":[]
    })
    key_id=grant.get("api_key",{}).get("id")
    token=grant.get("plain_key")
    note(bool(key_id and token),"server-generated ephemeral write key available")
    try:
        code,data=rpc("initialize",{"protocolVersion":"2025-06-18","capabilities":{},
               "clientInfo":{"name":"xyops-write-rdte","version":"0.1"}},1,token)
        note(code==200 and bool((data or {}).get("result")),"write MCP initialized")
        code,data=rpc("tools/list",{},2,token)
        tools=(data or {}).get("result",{}).get("tools",[])
        names={t.get("name") for t in tools}
        note({"create_event","update_event","get_event","delete_event","run_event"} <= names,
             "stock MCP exposes full schedule and execution tools",{"count":len(tools)})
        schema=next(t["inputSchema"] for t in tools if t["name"]=="create_event")
        broad=schema.get("properties",{}).get("event",{}).get("properties",{})
        note({"plugin","targets","params","workflow"} <= set(broad),
             "stock event creation exposes execution-bearing fields (production HOLD)")
        # No time trigger: an enabled event can only run if *explicitly* executed.
        event={"title":"RDTE MCP manual-only harmless event","enabled":True,"category":"general",
               "targets":["main"],"algo":"random","plugin":"shellplug",
               "params":{"script":"#!/bin/sh\\nprintf 'rdte-safe-marker\\n'"},
               "triggers":[{"type":"manual","enabled":True}]}
        accepted,res=tool(token,"create_event",{"event":event},3)
        note(accepted and bool(res.get("event",{}).get("id")),"MCP created approved synthetic event",
             {"accepted":accepted,"reason":res.get("message") if not accepted else None})
        event_id=res["event"]["id"]; rev=res["event"].get("revision")
        note(type(rev) is int and rev>=1,"create returned positive revision")
        accepted,loaded=tool(token,"get_event",{"id":event_id},4)
        note(accepted and loaded.get("event",{}).get("id")==event_id,
             "MCP read back created event")
        # Even on a *manual-only* harmless event, run_jobs=0 must prevent execution.
        accepted,res=tool(token,"run_event",{"id":event_id},5)
        note(not accepted,"restricted scheduling key cannot execute manually",
             {"denied":not accepted})
        accepted,updated=tool(token,"update_event",
                {"id":event_id,"revision":rev,"changes":{"enabled":False,"title":"RDTE MCP paused event"}},6)
        note(accepted and updated.get("event",{}).get("revision")==rev+1,
             "MCP compare-and-swap pause succeeds",
             {"accepted":accepted,"reason":updated.get("message") if not accepted else None})
        accepted,res=tool(token,"update_event",
                {"id":event_id,"revision":rev,"changes":{"enabled":True}},7)
        note(not accepted,"MCP stale-revision modification rejected")
        accepted,loaded=tool(token,"get_event",{"id":event_id},8)
        note(accepted and loaded.get("event",{}).get("enabled") is False,
             "failed stale update did not re-enable event")
        accepted,res=tool(token,"delete_event",{"id":event_id},9)
        note(accepted,"MCP synthetic event deleted")
        return {"status":"PASS","checks":checks,"tool_count":len(tools),
                "unrestricted_create_fields_present":True}
    finally:
        # Cleanup happens even on failed assertions. The CI network/volume is
        # destroyed regardless; don't echo the API credential.
        api("/api/app/delete_api_key/v1",{"id":key_id})

if __name__=="__main__":
    try:result=run()
    except Exception as e:result={"status":"FAIL","checks":checks,"reason":str(e)[:600]}
    (OUT/"xyops-mcp-write-result.json").write_text(json.dumps(result,indent=2)+"\\n")
    print(json.dumps(result,indent=2))
    sys.exit(0 if result["status"]=="PASS" else 1)
