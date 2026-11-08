#!/usr/bin/env python3
"""Free-cloud protocol proof: REST-only clock for an existing synthetic work item.

Uses a disposable xyOps v1.1.15 instance and temporary API key. Not the private
Agent Dispatch Python adapter, not Pandora/WOW, and no live schedule activation.
"""
import hashlib
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path("evidence")
OUT.mkdir(exist_ok=True)
ROOT = "http://127.0.0.1:15522"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
checks = []
sid = None
csrf = None
key = None

def raw(path, data=None, use_key=False):
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if use_key:
        headers["X-API-Key"] = key
    else:
        if sid: headers["X-Session-ID"] = sid
        if data is not None and csrf: headers["X-CSRF-Token"] = csrf
    req = urllib.request.Request(ROOT + path, headers=headers,
             data=json.dumps(data).encode() if data is not None else None,
             method="POST" if data is not None else "GET")
    try:
        with (urllib.request.urlopen(req, timeout=18) if use_key else opener.open(req, timeout=18)) as response:
            return response.status, json.loads(response.read(1000000))
    except urllib.error.HTTPError as exc:
        try:return exc.code,json.loads(exc.read(1000000))
        except Exception:return exc.code,{"code": -99}

def api(path, data=None, use_key=False):
    status,obj = raw(path,data,use_key)
    if status != 200 or obj.get("code") != 0:
        raise RuntimeError(f"xyOps {path} HTTP {status}, app code {obj.get('code')}")
    return obj

def test(ok, label, detail=None):
    checks.append({"name":label,"pass":bool(ok),
                   **({"detail":detail} if detail is not None else {})})
    if not ok: raise RuntimeError(label+(" "+str(detail)[:180] if detail is not None else ""))

def get_event(eid):
    return api("/api/app/get_event/v1?id="+urllib.parse.quote(eid),use_key=True).get("event",{})

def run():
    global sid,csrf,key
    login=api("/api/user/login",{"username":"admin","password":"admin"})
    sid=login.get("session_id")
    csrf=login.get("csrf_token")
    test(bool(sid or list(jar)) and bool(csrf),"disposable authenticated session and CSRF")
    plugins=api("/api/app/get_plugins/v1").get("rows",[])
    test(any(p.get("id")=="shellplug" for p in plugins),"stock xyOps plugins remain available")
    registered=api("/api/app/create_plugin/v1",{
       "id":"agent_dispatch_wake","title":"RDTE synthetic reserved wake",
       "type":"event","enabled":True,
       "command":"/opt/xyops-rdte/xyops-special-job-probe",
       "params":[
         {"id":"authority_ref","type":"text","title":"Authority","value":""},
         {"id":"authority_revision","type":"text","title":"Revision","value":""},
         {"id":"delegation","type":"text","title":"Delegation","value":""}
       ]
    }).get("plugin",{})
    test(registered.get("id")=="agent_dispatch_wake","native special Event Plugin registered")
    grant=api("/api/app/create_api_key/v1",{
       "title":"Disposable REST-only clock client","active":1,
       "privileges":{"admin":0,"create_events":1,"edit_events":1,
                     "delete_events":0,"run_jobs":0},"roles":[]
    })
    key=grant.get("plain_key")
    key_id=grant.get("api_key",{}).get("id")
    test(bool(key and key_id),"restricted server-generated native REST key")
    try:
        ref="github-file:example/synthetic@main:worksets/approved.json"
        delegation="synthetic-observe"
        assignment="already-existing-001"
        digest=hashlib.sha256(json.dumps([ref,delegation,assignment],
                             separators=(",",":")).encode()).hexdigest()[:24]
        eid="aw_"+digest
        params={"authority_ref":"https://github.com/example/synthetic-workset/issues/42",
                "authority_revision":"a"*40,"delegation":"synthetic-observe"}
        due=(int(time.time())//60+3)*60
        first=[{"type":"single","enabled":True,"epoch":due}]
        config={
            "id":eid,"title":"Agent Dispatch wake "+eid,
            "enabled":False,"category":"general","targets":["main"],
            "algo":"random","plugin":"agent_dispatch_wake",
            "params":params,"triggers":first
        }
        response=api("/api/app/create_event/v1",config,use_key=True).get("event",{})
        test(response.get("id")==eid and response.get("enabled") is False,
             "registered exact deterministic event disabled",{"id_prefix":eid[:3]})
        test(response.get("plugin")=="agent_dispatch_wake","special plugin fixed")
        test(get_event(eid).get("revision")==response.get("revision"),
             "native REST readback returns version")
        code,bad=raw("/api/app/create_event/v1",config,use_key=True)
        test(code!=200 or bad.get("code")!=0,
             "same deterministic ID cannot create duplicate native event")
        # Lost-reply approximation: a fresh caller can rediscover exact ID.
        found=get_event(eid)
        test(found.get("id")==eid and found.get("enabled") is False,
             "fresh readback reconciles create ambiguity without repeated POST")
        rev=found.get("revision")
        second=[{"type":"schedule","enabled":True,"weekdays":[5],
                 "hours":[8],"minutes":[0],"timezone":"Europe/Berlin"},
                {"type":"catchup","enabled":True}]
        update=api("/api/app/update_event/v1",{
            "id":eid,"revision":rev,"enabled":False,"triggers":second
        },use_key=True).get("event",{})
        test(update.get("revision")==rev+1,
             "reschedule with native revision CAS")
        updated=get_event(eid)
        triggers=updated.get("triggers",[])
        test(any(x.get("type")=="schedule" and x.get("timezone")=="Europe/Berlin" and
                 x.get("weekdays")==[5] for x in triggers),
             "Berlin recurring time preserved in native event")
        test(any(x.get("type")=="catchup" for x in triggers),
             "explicit missed-run policy preserved")
        test(updated.get("enabled") is False,
             "rescheduled event remains disabled")
        code,bad=raw("/api/app/update_event/v1",{
            "id":eid,"revision":rev,"enabled":True
        },use_key=True)
        test(code!=200 or bad.get("code")!=0,
             "stale revision cannot re-enable event")
        paused=api("/api/app/update_event/v1",{
            "id":eid,"revision":updated["revision"],"enabled":False
        },use_key=True).get("event",{})
        test(paused.get("enabled") is False,"cancel/disable keeps native event")
        test(paused.get("params",{}).get("authority_revision")=="a"*40,
             "clock changes preserve existing synthetic authority pointer")
        test(len(api("/api/app/search_jobs/v1?"+
                     urllib.parse.urlencode({"query":"event:"+eid,"limit":40}),use_key=True)
                 .get("rows",[]))==0,
             "no execution attempt created while special event disabled")
        return {"status":"PASS","checks":checks,
                "active_special_events":0,"sidecar_dispatches":0,
                "mcp_process_required":False,"native_version":"v1.1.15"}
    finally:
        api("/api/app/delete_api_key/v1",{"id":key_id})
        key=None

if __name__=="__main__":
    result={"status":"FAIL"}
    try:result=run()
    except Exception as e:result={"status":"FAIL","checks":checks,"error":str(e)[:380]}
    (OUT/"xyops-rest-clock-result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    sys.exit(0 if result["status"]=="PASS" else 1)
