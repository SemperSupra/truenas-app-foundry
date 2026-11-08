#!/usr/bin/env python3
"""Public-safe disposable native xyOps Trigger Plugin gate qualification.

No network outside runner loopback, no Agent Dispatch, no private task prompts.
Only synthetic four-source fixture and real conductor scheduling.
"""
import gzip
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = "http://127.0.0.1:15523"
EVIDENCE = Path("evidence")
EVIDENCE.mkdir(exist_ok=True)
JAR = http.cookiejar.CookieJar()
HTTP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
SESSION = None
CSRF = None
CHECKS = []

def check(ok, name, detail=None):
    CHECKS.append({"name": name, "pass": bool(ok),
                   **({"detail": detail} if detail is not None else {})})
    if not ok:
        raise RuntimeError(name + ": " + str(detail)[:200])

def request(path, body=None, raw=False):
    headers = {}
    if SESSION:
        headers["X-Session-ID"] = SESSION
    if body is not None:
        headers["Content-Type"] = "application/json"
        if CSRF:
            headers["X-CSRF-Token"] = CSRF
    req = urllib.request.Request(ROOT + path, headers=headers,
              data=json.dumps(body).encode() if body is not None else None)
    try:
        with HTTP.open(req, timeout=20) as res:
            data = res.read(800000)
            if res.headers.get("Content-Encoding", "").lower() == "gzip":
                data = gzip.decompress(data)
            return res.status, data if raw else json.loads(data)
    except urllib.error.HTTPError as ex:
        data = ex.read(800000)
        if raw:
            return ex.code, data
        try:
            return ex.code, json.loads(data)
        except (ValueError, TypeError):
            return ex.code, {"code": -99, "description": "non-JSON error"}

def api(path, body=None):
    status, data = request(path, body)
    if status != 200 or data.get("code") != 0:
        raise RuntimeError(f"{path}: HTTP {status}, code {data.get('code')}, "
                           f"detail {str(data.get('description'))[:140]}")
    return data

def event_jobs(event_id):
    query = urllib.parse.urlencode({"query": "event:" + event_id, "limit": 100})
    rows = api("/api/app/search_jobs/v1?" + query).get("rows", [])
    return [r for r in rows if r.get("source") == "plugin"]

def wait_done(job_id, seconds=40):
    until = time.monotonic() + seconds
    last = {}
    while time.monotonic() < until:
        last = api("/api/app/get_job/v1?id=" + urllib.parse.quote(job_id)).get("job", {})
        if last.get("complete") or last.get("state") in ("complete", "completed", "failed"):
            return last
        time.sleep(2)
    return last

def stdout(job_id):
    status, data = request("/api/app/get_job_log/v1?id=" + urllib.parse.quote(job_id), raw=True)
    return data.decode("utf8", "replace") if status == 200 else ""

def run():
    global SESSION, CSRF
    status, html = request("/", raw=True)
    check(status == 200 and b"<html" in html.lower(), "native xyOps UI available")
    session = api("/api/user/login", {"username":"admin","password":"admin"})
    SESSION = session.get("session_id")
    CSRF = session.get("csrf_token")
    check(bool(SESSION or list(JAR)) and bool(CSRF), "ephemeral login and CSRF")

    plugin = api("/api/app/create_plugin/v1", {
      "id": "synthetic_condition_gate",
      "title": "Synthetic read-only condition gate",
      "enabled": True,
      "type": "scheduler",
      "command": "/opt/xyops-rdte/xyops-trigger-condition-probe",
      "params": [{"id": "watch_key", "type": "text", "title": "Synthetic fixture key", "value": ""}],
    }).get("plugin", {})
    check(plugin.get("type") == "scheduler", "native scheduler Trigger Plugin registered")

    ids = {}
    for key in ("watch-ready", "watch-false", "watch-unknown", "watch-accepted"):
        event = api("/api/app/create_event/v1", {
          "title": "Synthetic trigger fixture " + key,
          "enabled": True, "category": "general",
          "targets": ["main"], "algo": "random", "plugin": "shellplug",
          "params": {"script": "#!/bin/sh\nprintf 'synthetic-trigger-marker\\n'"},
          "triggers": [
            {"type": "schedule", "enabled": True, "timezone": "UTC"},
            {"type": "plugin", "enabled": True, "plugin_id": "synthetic_condition_gate",
             "params": {"watch_key": key}, "timezone": "UTC"},
          ],
        }).get("event", {})
        check(bool(event.get("id")), "created native synthetic event for "+key)
        ids[key] = event["id"]

    # Full minute scheduler tick, then allow native xySat work to finish.
    deadline = time.monotonic() + 96
    ready = []
    while time.monotonic() < deadline:
        ready = event_jobs(ids["watch-ready"])
        if ready:
            break
        time.sleep(3)
    check(bool(ready), "TRUE fixture allowed real native plugin-source job")
    job_id = ready[0].get("id")
    check(bool(job_id), "launched job has independently inspectable identity")
    job = wait_done(job_id)
    check(job.get("code") == 0 and (job.get("complete") or job.get("state")=="complete"),
          "native allowed shell job completed", {"exit_code": job.get("code")})
    check("synthetic-trigger-marker" in stdout(job_id),
          "allowed job stdout independently verified")

    # A nonzero wait ensures all same-minute batched trigger decisions applied.
    time.sleep(9)
    results = {key: len(event_jobs(id_)) for key, id_ in ids.items()}
    for key in ("watch-false", "watch-unknown", "watch-accepted"):
        check(results[key] == 0, "suppressed "+key+" job", {"count": results[key]})
    check(results["watch-ready"] >= 1, "launch observed for TRUE fixture")
    for id_ in ids.values():
        api("/api/app/update_event/v1", {"id": id_, "enabled": False})
    return {"status":"PASS", "checks":CHECKS, "counts":results,
            "classification":"NATIVE_TRIGGER_BOOLEAN_GATE_ONLY",
            "repeat_true_dedup":"NOT_PROVEN_REQUIRES_OWNER_LEDGER",
            "native_task_changed":False, "agent_dispatch_called":False}

if __name__ == "__main__":
    result = {"status": "FAIL"}
    try:
        result = run()
    except Exception as ex:
        result = {"status":"FAIL", "checks": CHECKS, "reason":str(ex)[:500]}
    (EVIDENCE/"xyops-native-trigger-gate.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["status"]=="PASS" else 1)
