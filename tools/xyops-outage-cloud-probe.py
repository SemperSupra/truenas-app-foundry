#!/usr/bin/env python3
"""Isolated xyOps v1.1.15 missed-one-shot (catchup/no-catchup) qualification.

Runs on a free GitHub-hosted CI runner only. The shell job is a fixed benign
printf marker. No external credentials, host mounts, outbound tunnels, Pandora,
WOW, or actual Agent Dispatch integration. Compare two single-shot events under
the SAME conductor downtime; observe accepted job logs, not just HTTP 200.
"""
import argparse
import gzip
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT="http://127.0.0.1:15522"
EV=Path("evidence");EV.mkdir(exist_ok=True)
jar=http.cookiejar.CookieJar()
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
session=None
csrf=None
checks=[]

def check(ok,label,detail=None):
    checks.append({"name":label,"pass":bool(ok),**({"detail":detail} if detail is not None else {})})
    if not ok:raise RuntimeError(label+": "+str(detail)[:180])

def request(path,data=None,raw=False):
    headers={"Accept":"application/json"}
    if session:headers["X-Session-ID"]=session
    if data is not None:
        headers["Content-Type"]="application/json"
        if csrf:headers["X-CSRF-Token"]=csrf
    req=urllib.request.Request(ROOT+path,headers=headers,
             data=json.dumps(data).encode() if data is not None else None)
    try:
        with opener.open(req,timeout=22) as resp:
            payload=resp.read(600_000)
            if raw:
                if resp.headers.get("Content-Encoding","").lower()=="gzip":
                    payload=gzip.decompress(payload)
                return resp.status,payload
            return resp.status,json.loads(payload)
    except urllib.error.HTTPError as e:
        if raw:return e.code,e.read(2500)
        return e.code,json.loads(e.read(2500))

def api(path,data=None):
    code,result=request(path,data)
    if code!=200 or result.get("code")!=0:
        raise RuntimeError(f"{path}: HTTP {code}, code={result.get('code')}, desc={str(result.get('description'))[:150]}")
    return result

def login():
    global session,csrf
    x=api("/api/user/login",{"username":"admin","password":"admin"})
    session=x.get("session_id");csrf=x.get("csrf_token")
    check(bool(session or list(jar)) and bool(csrf),"ephemeral cookie/CSRF login")

def history(id_):
    q=urllib.parse.urlencode({"query":"event:"+id_,"limit":50})
    return [r for r in api("/api/app/search_jobs/v1?"+q).get("rows",[]) if r.get("source")=="scheduler"]

def job_log(id_):
    code,body=request("/api/app/get_job_log/v1?id="+urllib.parse.quote(id_),raw=True)
    return body.decode("utf-8","replace") if code==200 else ""

def arm():
    login()
    start=int(time.time())
    # first minute tick is needed to establish a durable catch-up cursor;
    # the next full minute is intentionally taken offline.
    next_tick=(start//60+1)*60
    due=(start//60+2)*60
    spec={"category":"general","targets":["main"],"algo":"random","plugin":"shellplug","enabled":True}
    ids={}
    for name,catchup in (("with_catchup",True),("without_catchup",False)):
        marker="outage-"+name
        data={**spec,"title":"Isolated missed one-shot "+name,
              "params":{"script":"#!/bin/sh\nprintf '"+marker+"\\n'"},
              "triggers":[{"type":"single","enabled":True,"epoch":due}]}
        if catchup:data["triggers"].append({"type":"catchup","enabled":True})
        event=api("/api/app/create_event/v1",data).get("event",{})
        id_=event.get("id")
        check(bool(id_), "created "+name)
        ids[name]=id_
    # Wait past the preceding minute tick, establishing on-disk catch-up cursor.
    sleep=max(0,next_tick+6-time.time())
    if sleep:time.sleep(sleep)
    check(time.time()<due-3,"preceding scheduler tick occurred before due",
          {"seconds_to_due":round(due-time.time(),1)})
    for name,id_ in ids.items():
        check(len(history(id_))==0,"no premature wake "+name)
    (EV/"xyops-outage-spec.json").write_text(json.dumps({"ids":ids,"due_utc":due,
        "preceding_minute_utc":next_tick},indent=2)+"\n")
    return {"status":"PASS","phase":"arm","checks":checks,
            "seconds_to_due":round(due-time.time(),1),"due_utc":due}

def verify():
    login()
    spec=json.loads((EV/"xyops-outage-spec.json").read_text())
    ids=spec["ids"];due=spec["due_utc"]
    deadline=time.monotonic()+90
    seen=[]
    while time.monotonic()<deadline:
        seen=history(ids["with_catchup"])
        if seen:break
        time.sleep(3)
    check(len(seen)==1,"catch-up replayed exactly one missed single-shot",
          {"scheduled_count":len(seen)})
    check(bool(seen[0].get("id")),"catch-up execution has durable job id")
    jobid=seen[0]["id"]
    log_deadline=time.monotonic()+30
    log=""
    while time.monotonic()<log_deadline:
        log=job_log(jobid)
        if "outage-with_catchup" in log:break
        time.sleep(2)
    check("outage-with_catchup" in log,"catch-up job emitted independent output marker")
    check(len(history(ids["without_catchup"]))==0,
          "no-catchup single-shot did not silently execute after outage")
    check(len(history(ids["with_catchup"]))==1,
          "catchup history remains exactly once after recovery")
    return {"status":"PASS","phase":"verify","checks":checks,
            "due_utc":due,"catchup_scheduled_count":1,"no_catchup_scheduled_count":0}

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("phase",choices=("arm","verify"));phase=p.parse_args().phase
    try:r=arm() if phase=="arm" else verify()
    except Exception as e:r={"status":"FAIL","phase":phase,"reason":str(e)[:450],"checks":checks}
    (EV/("xyops-outage-"+phase+".json")).write_text(json.dumps(r,indent=2)+"\n")
    print(json.dumps(r,indent=2))
    raise SystemExit(0 if r["status"]=="PASS" else 1)
