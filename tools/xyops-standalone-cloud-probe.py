#!/usr/bin/env python3
"""xyOps software CI probe: self-contained, synthetic and loopback-only.

Explicitly NOT an Agent Dispatch integration or production scheduler deployment.
The only shell operation the test scheduler can launch is the fixed public literal
'printf xyops-rdte-marker'; it has no host bind mounts, host networking, or secrets.
"""
import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = "http://127.0.0.1:15522"
EV = Path("evidence")
EV.mkdir(exist_ok=True)
session_id = None
csrf_token = None
cookiejar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
checks = []

def http(path, data=None, session=False):
    global session_id
    headers = {"Accept":"application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if session and session_id:
        headers["X-Session-ID"] = session_id
    if session and data is not None and csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    req = urllib.request.Request(ROOT + path, headers=headers,
            data=json.dumps(data).encode() if data is not None else None)
    try:
        with opener.open(req, timeout=20) as r:
            code = r.status
            raw = r.read(500_000)
    except urllib.error.HTTPError as e:
        code = e.code
        raw = e.read(500_000)
    try:
        obj = json.loads(raw.decode())
    except Exception:
        obj = {"unparsed":raw[:120].decode("utf-8","replace")}
    return code, obj

def ok(value, label, detail=None):
    checks.append({"name": label, "pass": bool(value), **({"detail":detail} if detail is not None else {})})
    if not value:
        raise RuntimeError(f"{label} FAILED: {str(detail)[:250]}")

def call(path, payload=None, login=True):
    status, result = http(path, payload, session=login)
    if status != 200 or result.get("code") != 0:
        raise RuntimeError(f"{path}: status={status},code={result.get('code')},reason={str(result.get('description'))[:200]}")
    return result

def login():
    global session_id, csrf_token
    data = call("/api/user/login", {"username":"admin","password":"admin"}, login=False)
    session_id = data.get("session_id")
    csrf_token = data.get("csrf_token")
    ok(session_id or any(True for _ in cookiejar), "local ephemeral admin session established")
    ok(bool(csrf_token), "CSRF secret issued for authenticated POSTs")

def search(event_id):
    return call("/api/app/search_jobs/v1?" + urllib.parse.urlencode({"query":"event:"+event_id,"limit":50})).get("rows", [])

def before():
    status, raw = http("/")
    ok(status == 200, "human WebUI root serves HTTP", {"http":status})
    status, unauth = http("/api/app/get_events/v1")
    ok(status in (401,403) or unauth.get("code") != 0, "unauthenticated event reads denied",
       {"http":status,"code":unauth.get("code")})
    status, unauth = http("/api/app/create_event/v1", {"title":"not authorized","plugin":"shellplug"})
    ok(status in (401,403) or unauth.get("code") != 0, "unauthenticated event writes denied",
       {"http":status,"code":unauth.get("code")})
    login()
    rows = call("/api/app/get_events/v1").get("rows",[])
    ok(isinstance(rows,list), "authenticated schedule listing")
    plugins = call("/api/app/get_plugins/v1").get("rows",[])
    ok(any(x.get("id")=="shellplug" for x in plugins), "stock shell plugin discovered")
    servers = call("/api/app/get_servers/v1")
    wait_start = time.monotonic()
    while not servers.get("servers") and time.monotonic()-wait_start < 55:
        time.sleep(3)
        servers = call("/api/app/get_servers/v1")
    ok(bool(servers.get("servers")), "disposable local xySat registered",
       {"count":len(servers.get("servers",{}))})
    # Only a fixed harmless script in a publicly disposable CI container.
    spec = {
        "title":"Cloud RDTE inert scheduling probe",
        "enabled":True,"category":"general","targets":["main"],"algo":"random",
        "plugin":"shellplug",
        "params":{"script":"#!/bin/sh\nprintf 'xyops-rdte-marker\\n'"},
        "triggers":[
            {"type":"manual","enabled":True},
            {"type":"interval","enabled":True,"start":int(time.time())+5,"duration":10}
        ]
    }
    created = call("/api/app/create_event/v1",spec)
    event = created.get("event",{})
    event_id=event.get("id")
    ok(event_id and event.get("title")==spec["title"],"created scheduled event via stock REST API")
    (EV/"xyops-event-id.txt").write_text(event_id+"\n")
    detail=call("/api/app/get_event/v1?id="+urllib.parse.quote(event_id)).get("event",{})
    ok(detail.get("id")==event_id and len(detail.get("triggers",[]))==2,"schedule readback with two triggers")
    manual=call("/api/app/run_event/v1",{"id":event_id})
    job=manual.get("job",{})
    job_id=manual.get("id") or job.get("id")
    ok(bool(job_id), "manual job accepted with ID")
    deadline=time.monotonic()+55
    rec={}
    while time.monotonic()<deadline:
        rec=call("/api/app/get_job/v1?id="+urllib.parse.quote(job_id)).get("job",{})
        if rec.get("complete") or rec.get("state") in ("complete","completed","failed"):
            break
        time.sleep(2)
    ok(bool(rec.get("complete") or rec.get("state") in ("complete","completed")), "manual job reached terminal state",
       {"state":rec.get("state"),"complete":rec.get("complete"),"code":rec.get("code")})
    # Do not infer scheduled wake from manual success.
    scheduled=[]
    deadline=time.monotonic()+42
    while time.monotonic()<deadline:
        rows=search(event_id)
        scheduled=[x for x in rows if x.get("source")=="scheduler"]
        if scheduled: break
        time.sleep(3)
    ok(bool(scheduled),"real interval scheduled firing observed",{"scheduled_count":len(scheduled)})
    # Keep the event but pause it so restart tests examine durable state.
    changed=call("/api/app/update_event/v1",{"id":event_id,"enabled":False})
    ok(changed.get("event",{}).get("enabled") is False,"schedule disabled without deleting history")
    evidence={"phase":"before","event_id":event_id,"checks":checks,
              "scheduled_count":len(scheduled),
              "manual_terminal":{k:rec.get(k) for k in ("state","complete","code","source")},
              "server_count":len(servers.get("servers",{}))}
    return evidence

def after():
    login()
    event_id=(EV/"xyops-event-id.txt").read_text().strip()
    data=call("/api/app/get_event/v1?id="+urllib.parse.quote(event_id)).get("event",{})
    ok(data.get("id")==event_id,"event definition survived container replacement")
    ok(data.get("enabled") is False,"disabled state survived container replacement")
    rows=search(event_id)
    ok(len(rows)>=2,"manual and scheduled run history survived container replacement",
       {"record_count":len(rows)})
    return {"phase":"after","event_id":event_id,"checks":checks,
            "history_count":len(rows),"sources":sorted(set(str(x.get("source")) for x in rows))}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--phase",choices=("before","after"),required=True)
    args=parser.parse_args()
    result={"phase":args.phase,"status":"FAIL"}
    try:
        result=(before() if args.phase=="before" else after())
        result["status"]="PASS"
    except Exception as e:
        result["error"]=str(e)[:700]
        result["checks"]=checks
    (EV/("xyops-"+args.phase+"-result.json")).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    sys.exit(0 if result["status"]=="PASS" else 1)
