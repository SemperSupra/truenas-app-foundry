#!/usr/bin/env python3
"""Synthetic native xyOps inbound Magic Link -> outbound WebHook -> Magic Link.
No private data, no external callback, no production authentication, no
Agent Dispatch/WOW or SupraChat session; disposable public cloud runner only.
"""
import concurrent.futures
import http.cookiejar
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT="http://127.0.0.1:15524"
OUT=Path("evidence")
OUT.mkdir(exist_ok=True)
JAR=http.cookiejar.CookieJar()
HTTP=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
SESSION=None
CSRF=None
CHECKS=[]

def check(ok,name,detail=None):
    CHECKS.append({"name":name,"pass":bool(ok),
                   **({"detail":detail} if detail is not None else {})})
    if not ok:raise RuntimeError(name+": "+str(detail)[:180])

def request(path,data=None,headers=None):
    h=dict(headers or {})
    if SESSION:h["X-Session-ID"]=SESSION
    if data is not None:
        h["Content-Type"]="application/json"
        if CSRF:h["X-CSRF-Token"]=CSRF
    q=urllib.request.Request(ROOT+path,headers=h,
           data=json.dumps(data).encode("utf8") if data is not None else None)
    try:
        with HTTP.open(q,timeout=30) as r:
            b=r.read(1000000)
            return r.status,json.loads(b) if b else {}
    except urllib.error.HTTPError as e:
        b=e.read(1000000)
        try:return e.code,json.loads(b) if b else {}
        except (ValueError,TypeError):return e.code,{"code":-99,"description":"unreadable error"}

def api(path,data=None):
    status,body=request(path,data)
    if status!=200 or body.get("code")!=0:
        raise RuntimeError(f"api failure {path.split('?')[0]} HTTP={status} code={body.get('code')} detail={str(body.get('description'))[:150]}")
    return body

def get_job(job_id):
    return api("/api/app/get_job/v1?id="+urllib.parse.quote(job_id)).get("job",{})

def wait_job(job_id,timeout=50):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        job=get_job(job_id)
        if job.get("complete") or job.get("state") in ("complete","completed","failed"):return job
        time.sleep(2)
    raise RuntimeError("job did not finish")

def event_jobs(event_id):
    q=urllib.parse.urlencode({"query":"event:"+event_id,"limit":100})
    return api("/api/app/search_jobs/v1?"+q).get("rows",[])

def wait_count(event_id,n,timeout=50):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        jobs=event_jobs(event_id)
        if len(jobs)>=n:return jobs
        time.sleep(2)
    return event_jobs(event_id)

def run():
    global SESSION,CSRF
    s=api("/api/user/login",{"username":"admin","password":"admin"})
    SESSION=s.get("session_id")
    CSRF=s.get("csrf_token")
    check(bool(SESSION or list(JAR)) and CSRF,"isolated session and CSRF verified")
    receiver_key=secrets.token_urlsafe(28)
    incoming_key=secrets.token_urlsafe(28)
    bad_key=secrets.token_urlsafe(28)
    marker="synthetic-outbound-receipt-v1"
    # Receiver is a second synthetic xyOps event. It cannot call external systems.
    receiver=api("/api/app/create_event/v1",{
      "title":"RDTE synthetic outbound receiver", "enabled":True,
      "category":"general", "targets":["main"],"algo":"random","plugin":"shellplug",
      "params":{"script":"#!/bin/sh\nprintf 'synthetic-receiver-ok\n'"},
      "triggers":[{"type":"magic","enabled":True,"key":receiver_key}],
      "limits":[{"type":"file","enabled":True,"amount":0}]
    }).get("event",{})
    recv_id=receiver.get("id")
    check(bool(recv_id),"inbound receiver event registered")
    hook=api("/api/app/create_web_hook/v1",{
      "id":"rdte_outbound_receipt",
      "title":"Synthetic outbound to isolated local xyOps Magic Link",
      "enabled":True,"method":"POST",
      "url":"http://127.0.0.1:5522/api/app/magic/v1/"+receiver_key,
      "headers":[{"name":"Content-Type","value":"application/json"}],
      "body":json.dumps({"type":marker,"source":"xyops-rdte"}),
      "retries":0,"timeout":10,"follow":False,"ssl_cert_bypass":False,
      "max_per_day":20
    }).get("web_hook",{})
    check(hook.get("id")=="rdte_outbound_receipt","native outbound HTTP webhook created")
    incoming=api("/api/app/create_event/v1",{
      "title":"RDTE synthetic inbound Magic Link", "enabled":True,
      "category":"general", "targets":["main"],"algo":"random","plugin":"shellplug",
      "params":{"script":"#!/bin/sh\nprintf 'synthetic-ingress-ok\n'"},
      "triggers":[{"type":"magic","enabled":True,"key":incoming_key}],
      "actions":[{"enabled":True,"condition":"success","type":"web_hook","web_hook":"rdte_outbound_receipt"}],
      "limits":[{"type":"file","enabled":True,"amount":0}]
    }).get("event",{})
    inc_id=incoming.get("id")
    check(bool(inc_id),"native inbound Magic Link with success action registered")
    invalid_status,invalid=request("/api/app/magic/v1/"+bad_key,{"synthetic":True})
    check(invalid.get("code")!=0 or invalid_status!=200,"wrong bearer key rejected",
          {"http":invalid_status,"code":invalid.get("code")})
    check(len(event_jobs(inc_id))==0,"unauthorized request launched no job")
    delivery_id=secrets.token_hex(16)
    status,launched=request("/api/app/magic/v1/"+incoming_key,
               {"synthetic":"event","serial":"one"},
               {"X-GitHub-Delivery":delivery_id,"X-Research-Synthetic":"yes"})
    check(status==200 and launched.get("code")==0 and bool(launched.get("id")),
          "signed-url bearer ingress accepted (no GitHub HMAC claimed)",
          {"http":status,"code":launched.get("code")})
    jid=launched["id"]
    job=wait_job(jid)
    check(job.get("code")==0 and job.get("complete"),
          "incoming job completed with success",{"code":job.get("code")})
    check(job.get("source")=="magic","ingress identified as native Magic Link")
    # Outbound web hook should invoke exactly the second recipient event, as
    # a real HTTP POST sent from inside the isolated xyOps conductor.
    recv_jobs=wait_count(recv_id,1,timeout=55)
    check(len(recv_jobs)>=1,"outbound HTTP callback delivered to receiver",
          {"count":len(recv_jobs)})
    receipt=wait_job(recv_jobs[0]["id"])
    check(receipt.get("code")==0 and receipt.get("complete"),
          "outbound receiver job completed",{"code":receipt.get("code")})
    body=(receipt.get("magic") or {}).get("body") or ""
    check(marker in body,"outbound HTTP request body preserved at receiver")
    # An identical delivery ID is not by itself deduplicated by native Magic Link:
    # demonstrate the separate replay guard required before a governed wake.
    status2,launched2=request("/api/app/magic/v1/"+incoming_key,
               {"synthetic":"event","serial":"one"},
               {"X-GitHub-Delivery":delivery_id})
    check(status2==200 and launched2.get("code")==0 and launched2.get("id")!=jid,
          "replayed external delivery launched distinct job (requires upstream dedup)")
    wait_job(launched2["id"])
    check(len(wait_count(inc_id,2,timeout=15))>=2,
          "duplicate ingress observed, NOT an idempotency PASS")
    # Distinct concurrent R6 lane: FOUR identical external delivery IDs,
    # submitted through independent unauthenticated-by-session Magic requests.
    # No private webhook, no GitHub signature or owner-effect simulation.
    def duplicate_delivery(_):
        payload=json.dumps({"synthetic":"event","serial":"one"}).encode("utf-8")
        q=urllib.request.Request(
            ROOT+"/api/app/magic/v1/"+incoming_key,data=payload,
            headers={"Content-Type":"application/json",
                     "X-GitHub-Delivery":delivery_id,
                     "X-Research-Synthetic":"concurrent-r6"},method="POST")
        try:
            with urllib.request.urlopen(q,timeout=30) as res:
                ans=json.loads(res.read(1000000))
                return {"http":res.status,"code":ans.get("code"),
                        "job":ans.get("id")}
        except urllib.error.HTTPError as e:
            return {"http":e.code,"code":"native-http-error","job":None}
        except Exception as e:
            return {"http":None,"code":type(e).__name__,"job":None}
    t0=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        outcomes=list(pool.map(duplicate_delivery,range(4)))
    accepted=[o["job"] for o in outcomes if o["http"]==200 and o["code"]==0 and o["job"]]
    post_jobs=wait_count(inc_id,2+len(accepted),timeout=30)
    concurrency_observation={
        "delivery_count":4,"native_accepted":len(accepted),
        "native_distinct_job_ids":len(set(accepted)),
        "total_inbound_jobs_observed":len(post_jobs),
        "wall_ms":round((time.monotonic()-t0)*1000,3),
        "statuses":[{"http":o["http"],"code":o["code"]} for o in outcomes],
        "external_delivery_id_dedup_qualified":False,
        "actual_owner_effect_qualified":False,
    }
    check(len(post_jobs)>=2,"concurrent ingress did not erase prior native history",
          {"count":len(post_jobs)})
    api("/api/app/update_event/v1",{"id":inc_id,"enabled":False})
    api("/api/app/update_event/v1",{"id":recv_id,"enabled":False})
    return {"status":"PASS","checks":CHECKS,
            "inbound":"TOKENIZED_MAGIC_LINK_DEMONSTRATED",
            "outbound":"LOCAL_HTTP_WEBHOOK_DEMONSTRATED",
            "replay":"REQUIRES_SIDECAR_OWNER_IDEMPOTENCY",
            "concurrent_duplicate_delivery":concurrency_observation,
            "auth":"BEARER_URL_ONLY_NOT_GITHUB_SIGNATURE",
            "external_network_touched":False,
            "pandora_touched":False,"suprachat_touched":False}

if __name__=="__main__":
    result={"status":"FAIL"}
    try:result=run()
    except Exception as e:result={"status":"FAIL","checks":CHECKS,"reason":str(e)[:500]}
    (OUT/"xyops-native-webhook-io.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["status"]=="PASS" else 1)
