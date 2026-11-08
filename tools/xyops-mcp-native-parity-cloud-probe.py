#!/usr/bin/env python3
"""Cloud-only xyCLI MCP and xyOps REST parity for ordinary vs reserved jobs.

No ChatGPT tunnel, external credentials or Agent Dispatch/WOW calls. The test
uses disposable local xyOps credentials and a mock special plugin fixture.
"""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT="http://127.0.0.1:15522"
MCP="http://127.0.0.1:18080/mcp"
OUT=Path("evidence")
OUT.mkdir(exist_ok=True)
JAR=http.cookiejar.CookieJar()
CLIENT=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
SID=None
CSRF=None
CHECKS=[]
REF="https://github.com/example/synthetic-workset/issues/42"
REV="a"*40

def request(url,payload=None,headers=None):
    hdr=dict(headers or {})
    if payload is not None:hdr.setdefault("Content-Type","application/json")
    req=urllib.request.Request(url,headers=hdr,
            data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with CLIENT.open(req,timeout=22) as resp:
            return resp.status,resp.headers.get("Content-Type",""),resp.read(1_000_000)
    except urllib.error.HTTPError as e:
        return e.code,e.headers.get("Content-Type",""),e.read(1_000_000)

def api(path,payload=None):
    hdr={}
    if SID:hdr["X-Session-ID"]=SID
    if payload is not None and CSRF:hdr["X-CSRF-Token"]=CSRF
    status,_,raw=request(ROOT+path,payload,hdr)
    try:data=json.loads(raw)
    except Exception:raise RuntimeError("REST non-JSON HTTP="+str(status))
    if status!=200 or data.get("code")!=0:
        raise RuntimeError("REST "+path+" HTTP="+str(status)+
                           " code="+str(data.get("code"))+
                           " reason="+str(data.get("description"))[:140])
    return data

def rpc(token,method,params,rid):
    hdr={"Authorization":"Bearer "+token,
         "Accept":"application/json, text/event-stream",
         "Content-Type":"application/json"}
    status,kind,raw=request(MCP,{"jsonrpc":"2.0","id":rid,
                                  "method":method,"params":params},hdr)
    data=None
    if "text/event-stream" in kind:
        for line in raw.decode("utf-8","replace").splitlines():
            if line.startswith("data:"):
                try:msg=json.loads(line[5:].strip())
                except Exception:continue
                if msg.get("id")==rid:data=msg;break
    else:
        try:data=json.loads(raw)
        except Exception:pass
    return status,data

def call(token,name,args,rid):
    status,data=rpc(token,"tools/call",{"name":name,"arguments":args},rid)
    result=(data or {}).get("result") or {}
    if status!=200 or (data or {}).get("error") or result.get("isError"):
        excerpt=" ".join(str(x.get("text","")) for x in result.get("content",[]) if isinstance(x,dict))
        return False,{"http":status,"message":excerpt.replace(token,"<hidden>")[:170]}
    return True,result.get("structuredContent") or {}

def check(condition,label,details=None):
    CHECKS.append({"name":label,"pass":bool(condition),
                  **({"detail":details} if details is not None else {})})
    if not condition:raise RuntimeError(label+" failed "+str(details)[:210])

def get_rest(id_):
    return api("/api/app/get_event/v1?id="+urllib.parse.quote(id_)).get("event",{})

def run():
    global SID,CSRF
    login=api("/api/user/login",{"username":"admin","password":"admin"})
    SID=login.get("session_id")
    CSRF=login.get("csrf_token")
    check(bool(SID or list(JAR)) and bool(CSRF),"local fixture session with CSRF")
    existing=api("/api/app/get_plugins/v1").get("rows",[])
    check(any(x.get("id")=="shellplug" for x in existing),"ordinary plugin available")
    p=api("/api/app/create_plugin/v1",{
        "id":"agent_dispatch_wake",
        "title":"Restricted special wake — cloud fixture",
        "enabled":True,"type":"event",
        "command":"/opt/xyops-rdte/xyops-special-job-probe",
        "params":[{"id":"authority_ref","type":"text","title":"Authority","value":""},
                  {"id":"authority_revision","type":"text","title":"Revision","value":""},
                  {"id":"delegation","type":"text","title":"Delegation","value":""}]
    }).get("plugin",{})
    check(p.get("id")=="agent_dispatch_wake","reserved native Event Plugin registered")
    grant=api("/api/app/create_api_key/v1",{
      "title":"Disposable MCP normal-and-special CRUD probe","active":1,
      "privileges":{"admin":0,"create_events":1,"edit_events":1,
                    "delete_events":1,"run_jobs":0},"roles":[]
    })
    key_id=grant.get("api_key",{}).get("id")
    token=grant.get("plain_key")
    check(bool(key_id and token),"ephemeral server-generated API key")
    try:
        status,data=rpc(token,"initialize",{"protocolVersion":"2025-06-18",
           "capabilities":{},"clientInfo":{"name":"native-job-parity-probe","version":"0.1"}},1)
        check(status==200 and bool((data or {}).get("result")),"xyCLI MCP initialized")
        status,data=rpc(token,"tools/list",{},2)
        available={x.get("name") for x in (data or {}).get("result",{}).get("tools",[])}
        check({"create_event","get_event","list_events","update_event",
               "delete_event","run_event"} <= available,"native MCP CRUD tools available")
        specs=[
          ("ordinary",{
            "title":"MCP parity ordinary xyOps task","enabled":True,"category":"general",
            "targets":["main"],"algo":"random","plugin":"shellplug",
            "params":{"script":"#!/bin/sh\nprintf 'ordinary fixture\n'"},
            "triggers":[{"type":"manual","enabled":True}]
          }),
          ("special",{
            "title":"MCP parity Agent Dispatch special wake","enabled":True,
            "category":"general","targets":["main"],"algo":"random",
            "plugin":"agent_dispatch_wake",
            "params":{"authority_ref":REF,"authority_revision":REV,
                      "delegation":"synthetic-observe"},
            "triggers":[{"type":"manual","enabled":True}]
          })
        ]
        ids=[]
        counter=10
        for kind,spec in specs:
            counter+=1
            accepted,data=call(token,"create_event",{"event":spec},counter)
            check(accepted and bool(data.get("event",{}).get("id")),
                  "MCP creates "+kind,{"error":data.get("message") if not accepted else None})
            eid=data["event"]["id"]
            revision=data["event"].get("revision")
            ids.append(eid)
            check(type(revision) is int and revision>=1,"revision received "+kind)
            event=get_rest(eid)
            check(event.get("plugin")==spec["plugin"] and event.get("params")==spec["params"],
                  "REST readback matches MCP creation "+kind)
            check(event.get("triggers")==spec["triggers"],"schedule readback "+kind)
            counter+=1
            accepted,detail=call(token,"get_event",{"id":eid},counter)
            check(accepted and detail.get("event",{}).get("plugin")==spec["plugin"],
                  "MCP readback matches REST "+kind)
            counter+=1
            accepted,listed=call(token,"list_events",{"title":spec["title"],"limit":10},counter)
            check(accepted and any(x.get("id")==eid for x in listed.get("rows",[])),
                  "MCP list identifies "+kind)
            counter+=1
            accepted,denial=call(token,"run_event",{"id":eid},counter)
            check(not accepted,"CRUD-only credential cannot directly run "+kind)
            counter+=1
            accepted,update=call(token,"update_event",{
                "id":eid,"revision":revision,
                "changes":{"enabled":False}},counter)
            check(accepted and update.get("event",{}).get("revision")==revision+1,
                  "MCP CAS disables "+kind,{"reason":update.get("message")})
            check(get_rest(eid).get("enabled") is False,"REST sees disabled "+kind)
            counter+=1
            accepted,_=call(token,"update_event",{
                "id":eid,"revision":revision,"changes":{"enabled":True}},counter)
            check(not accepted,"stale CAS rejected "+kind)
            counter+=1
            accepted,_=call(token,"delete_event",{"id":eid},counter)
            check(accepted,"MCP deletes "+kind)
        check(len(ids)==2 and ids[0]!=ids[1],"ordinary and special identities distinct")
        return {"status":"PASS","checks":CHECKS,"mcp_tool_count":len(available),
                "ordinary_and_special_native_crud":"PASS",
                "sidecar_touched":False,
                "webui":"HTML smoke only; authenticated human/editor and accessibility untested"}
    finally:
        api("/api/app/delete_api_key/v1",{"id":key_id})

if __name__=="__main__":
    result={"status":"FAIL"}
    try:result=run()
    except Exception as e:result={"status":"FAIL","checks":CHECKS,"reason":str(e)[:500]}
    (OUT/"xyops-mcp-native-parity.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    sys.exit(0 if result["status"]=="PASS" else 1)
