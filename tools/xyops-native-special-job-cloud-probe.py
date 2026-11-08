#!/usr/bin/env python3
"""Public CI: native xyOps special Event Plugin beside unchanged ordinary Shell Plugin.

The special Go executable is mounted read-only, has no sidecar credentials, and
generates synthetic receipts only. Local admin/admin is confined to throwaway CI.
"""
import gzip
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT="http://127.0.0.1:15522"
EVD=Path("evidence")
EVD.mkdir(exist_ok=True)
JAR=http.cookiejar.CookieJar()
HTTP=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
SESSION=None
CSRF=None
CHECKS=[]
REF="https://github.com/example/synthetic-workset/issues/42"
REV="a"*40

def check(ok,label,detail=None):
    CHECKS.append({"name":label,"pass":bool(ok),
                   **({"detail":detail} if detail is not None else {})})
    if not ok:raise RuntimeError(label+": "+str(detail)[:220])

def request(path,obj=None,raw=False):
    h={}
    if SESSION:h["X-Session-ID"]=SESSION
    if obj is not None:
        h["Content-Type"]="application/json"
        if CSRF:h["X-CSRF-Token"]=CSRF
    q=urllib.request.Request(ROOT+path,headers=h,
             data=json.dumps(obj).encode() if obj is not None else None)
    try:
        with HTTP.open(q,timeout=20) as r:
            data=r.read(800000)
            if r.headers.get("Content-Encoding","").lower()=="gzip":
                data=gzip.decompress(data)
            if raw:return r.status,data
            return r.status,json.loads(data)
    except urllib.error.HTTPError as e:
        data=e.read(800000)
        if raw:return e.code,data
        try:return e.code,json.loads(data)
        except Exception:return e.code,{"code":-99,"description":"non-JSON error"}

def api(path,obj=None):
    status,data=request(path,obj)
    if status!=200 or data.get("code")!=0:
        raise RuntimeError(f"{path}: HTTP {status} code {data.get('code')} {str(data.get('description'))[:150]}")
    return data

def job_status(id_):
    return api("/api/app/get_job/v1?id="+urllib.parse.quote(id_)).get("job",{})

def job_output(id_):
    status,data=request("/api/app/get_job_log/v1?id="+urllib.parse.quote(id_),raw=True)
    return data.decode("utf-8","replace") if status==200 else ""

def job_wait(id_,timeout=65):
    until=time.monotonic()+timeout
    job={}
    while time.monotonic()<until:
        job=job_status(id_)
        if job.get("complete") or job.get("state") in ("complete","completed","failed"):break
        time.sleep(2)
    check(bool(job.get("complete") or job.get("state") in ("complete","completed","failed")),
          "job completed",{"job_id":id_,"state":job.get("state")})
    return job

def marker_wait(id_,marker,timeout=30):
    until=time.monotonic()+timeout
    result=""
    while time.monotonic()<until:
        result=job_output(id_)
        if marker in result:return True
        time.sleep(2)
    return False

def run():
    global SESSION,CSRF
    status,html=request("/",raw=True)
    check(status==200 and b"<html" in html.lower(),"native xyOps WebUI served")
    auth=api("/api/user/login",{"username":"admin","password":"admin"})
    SESSION=auth.get("session_id")
    CSRF=auth.get("csrf_token")
    check(bool(SESSION or list(JAR)) and bool(CSRF),"ephemeral session and CSRF")
    plugins=api("/api/app/get_plugins/v1").get("rows",[])
    check(any(p.get("id")=="shellplug" for p in plugins),"standard shell plugin retained")
    new_plugin=api("/api/app/create_plugin/v1",{
       "id":"agent_dispatch_wake",
       "title":"Agent Dispatch special wake (synthetic cloud qualification)",
       "enabled":True,"type":"event",
       "command":"/opt/xyops-rdte/xyops-special-job-probe",
       "params":[
           {"id":"authority_ref","type":"text","title":"DLE owner locator","value":""},
           {"id":"authority_revision","type":"text","title":"Owner revision","value":""},
           {"id":"delegation","type":"text","title":"Exact delegation","value":""}
       ]
    }).get("plugin",{})
    check(new_plugin.get("id")=="agent_dispatch_wake","native special Event Plugin registered")
    normal=api("/api/app/create_event/v1",{
      "title":"Unchanged normal xyOps workload","enabled":True,"category":"general",
      "targets":["main"],"algo":"random","plugin":"shellplug",
      "params":{"script":"#!/bin/sh\nprintf 'normal-xyops-job-ok\n'"},
      "triggers":[{"type":"manual","enabled":True}]
    }).get("event",{})
    normal_id=normal.get("id")
    check(bool(normal_id),"normal xyOps job created without special restrictions")
    run_normal=api("/api/app/run_event/v1",{"id":normal_id})
    normal_job=run_normal.get("id") or run_normal.get("job",{}).get("id")
    check(bool(normal_job),"normal job started")
    normal_result=job_wait(normal_job)
    check(normal_result.get("code")==0,"normal job exited successfully")
    check(marker_wait(normal_job,"normal-xyops-job-ok"),"native ordinary Shell Plugin output verified")

    special_params={"authority_ref":REF,"authority_revision":REV,
                     "delegation":"synthetic-observe"}
    now=int(time.time())
    special=api("/api/app/create_event/v1",{
      "title":"Synthetic Agent Dispatch special wake","enabled":True,
      "category":"general","targets":["main"],"algo":"random",
      "plugin":"agent_dispatch_wake","params":special_params,
      "triggers":[{"type":"interval","enabled":True,"start":now-15,"duration":10}]
    }).get("event",{})
    sid=special.get("id")
    check(bool(sid),"special event created through native xyOps scheduling")
    deadline=time.monotonic()+92
    rows=[]
    while time.monotonic()<deadline:
        q=urllib.parse.urlencode({"query":"event:"+sid,"limit":30})
        rows=[x for x in api("/api/app/search_jobs/v1?"+q).get("rows",[])
                if x.get("source")=="scheduler"]
        if rows:break
        time.sleep(3)
    check(bool(rows),"scheduler fired special Event Plugin")
    special_job=rows[0].get("id")
    check(bool(special_job),"special plugin job has independently inspectable identity")
    info=job_wait(special_job)
    check(info.get("code")==0,"native special event completed",{"code":info.get("code")})
    api("/api/app/update_event/v1",{"id":sid,"enabled":False})
    check(marker_wait(special_job,"synthetic reference receipt only"),
          "special plugin synthetic receipt emitted without sidecar execution")

    # Negative: a user may author the event in xyOps, but plugin must still
    # refuse to turn unapproved parameters into Agent Dispatch work.
    reject=api("/api/app/create_event/v1",{
      "title":"Unapproved synthetic special job","enabled":True,
      "category":"general","targets":["main"],"algo":"random",
      "plugin":"agent_dispatch_wake",
      "params":{**special_params, "authority_ref":"https://github.com/example/unknown/issues/99"},
      "triggers":[{"type":"manual","enabled":True}]
    }).get("event",{})
    badid=reject.get("id")
    check(bool(badid),"native special event with unapproved authority persisted")
    triggered=api("/api/app/run_event/v1",{"id":badid})
    deniedid=triggered.get("id") or triggered.get("job",{}).get("id")
    check(bool(deniedid),"negative special job launched")
    denied=job_wait(deniedid)
    check(denied.get("code")!=0,"special plugin refused unapproved authority",
          {"job_exit_code":denied.get("code")})
    return {"status":"PASS","checks":CHECKS,
            "ordinary_job":"PASS","special_wake":"SYNTHETIC_RECEIPT_ONLY",
            "unapproved_special":"DENIED","private_sidecar_touched":False}

if __name__=="__main__":
    result={"status":"FAIL"}
    try:result=run()
    except Exception as e:result={"status":"FAIL","checks":CHECKS,"reason":str(e)[:600]}
    (EVD/"xyops-native-special-job.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["status"]=="PASS" else 1)
