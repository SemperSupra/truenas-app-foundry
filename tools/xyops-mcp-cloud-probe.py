#!/usr/bin/env python3
"""xyOps read-only MCP security/protocol probe against isolated cloud CI containers.

No remote ChatGPT connection or integration. Disposable API key is generated inside
the job, never written to artifacts or printed. MCP proxy is loopback-only.
"""
import http.cookiejar, json, secrets, sys, urllib.error, urllib.request
from pathlib import Path
EV=Path("evidence"); EV.mkdir(exist_ok=True)
checks=[]
cookies=http.cookiejar.CookieJar()
http=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
ROOT="http://127.0.0.1:15522"
MCP="http://127.0.0.1:18080/mcp"
session_id=None
csrf_token=None

def request(url,payload=None,headers=None):
    req=urllib.request.Request(url,headers=headers or {},
        data=json.dumps(payload).encode("utf-8") if payload is not None else None)
    try:
        with http.open(req,timeout=25) as resp:
            return resp.status, resp.headers.get("content-type",""),resp.read(2_000_000)
    except urllib.error.HTTPError as e:
        return e.code,e.headers.get("content-type",""),e.read(1_000_000)

def check(cond,name,details=None):
    checks.append({"name":name,"pass":bool(cond),**({"details":details} if details is not None else {})})
    if not cond: raise RuntimeError(f"{name}: {str(details)[:250]}")

def call(path,payload=None):
    headers={"Content-Type":"application/json"}
    if session_id: headers["X-Session-ID"]=session_id
    if payload is not None and csrf_token: headers["X-CSRF-Token"]=csrf_token
    status,ct,raw=request(ROOT+path,payload,headers)
    try: obj=json.loads(raw)
    except Exception: raise RuntimeError(f"API {path} HTTP={status} non-JSON response")
    if status!=200 or obj.get("code")!=0:
        raise RuntimeError(f"API {path}: HTTP={status},code={obj.get('code')},error={str(obj.get('description'))[:120]}")
    return obj

def rpc(method,params,id=1,bearer=None):
    headers={"Accept":"application/json, text/event-stream","Content-Type":"application/json"}
    if bearer is not None: headers["Authorization"]="Bearer "+bearer
    payload={"jsonrpc":"2.0","id":id,"method":method}
    if params is not None: payload["params"]=params
    status,ct,raw=request(MCP,payload,headers)
    obj=None
    if "text/event-stream" in ct:
        for line in raw.decode("utf-8","replace").splitlines():
            if line.startswith("data:"):
                try: candidate=json.loads(line[5:].strip())
                except Exception: continue
                if candidate.get("id")==id: obj=candidate;break
    else:
        try: obj=json.loads(raw)
        except Exception: obj=None
    return status,obj

def run():
    global session_id,csrf_token
    status,_,_=request(MCP,{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}},{"Accept":"application/json,text/event-stream","Content-Type":"application/json"})
    check(status==401,"no-token MCP HTTP denied",{"status":status})
    auth=call("/api/user/login",{"username":"admin","password":"admin"})
    session_id=auth.get("session_id")
    csrf_token=auth.get("csrf_token")
    check(session_id or list(cookies),"ephemeral admin login for key creation")
    check(bool(csrf_token),"CSRF token issued for secure key management")
    token=secrets.token_urlsafe(35)
    result=call("/api/app/create_api_key/v1",{
      "title":"RDTE ephemeral restricted client",
      "key":token,"active":1,
      "privileges":{"admin":0,"run_jobs":0,"create_events":0,"edit_events":0,"delete_events":0},
      "roles":[]
    })
    key_id=result.get("api_key",{}).get("id")
    check(bool(key_id),"ephemeral restricted API key provisioned (ID withheld)")
    status,data=rpc("initialize",{
       "protocolVersion":"2025-06-18",
       "capabilities":{},
       "clientInfo":{"name":"xyops-public-ci-test","version":"0.1"}
    },id=1,bearer=token)
    check(status==200 and bool(data and data.get("result")),
          "authenticated MCP initialize",{"http":status,"error":data.get("error") if data else None})
    status,data=rpc("tools/list",{},id=2,bearer=token)
    names=[t.get("name") for t in (data or {}).get("result",{}).get("tools",[])]
    check(status==200 and "list_events" in names,
          "MCP tool discovery",{"tool_count":len(names),"http":status})
    check("run_event" not in names,"read-only MCP excludes execution tool",
          {"run_event_advertised":"run_event" in names})
    status,data=rpc("tools/call",{
       "name":"list_events","arguments":{"limit":10}
    },id=3,bearer=token)
    result=(data or {}).get("result",{})
    error_text=" ".join(str(x.get("text","")) for x in result.get("content",[]) if isinstance(x,dict)).replace(token,"<redacted>")[:300]
    check(status==200 and bool(result) and not result.get("isError"),
          "restricted client MCP list_events accepted",
          {"http":status,"mcp_protocol_error":bool(data and data.get("error")),"tool_error":result.get("isError"),"error_excerpt":error_text if result.get("isError") else None})
    status,data=rpc("tools/call",{
       "name":"run_event","arguments":{"id":"nonexistent"}
    },id=4,bearer=token)
    result=(data or {}).get("result",{})
    check(bool((data or {}).get("error") or result.get("isError")),
          "direct execution attempt rejected by read-only MCP",
          {"http":status})
    call("/api/app/delete_api_key/v1",{"id":key_id})
    # This is an operator control test on the isolated trial, not deployment.
    check(True,"ephemeral token revoked after probe")
    return {"status":"PASS","tool_count":len(names),"checks":checks}

if __name__=="__main__":
    out={"status":"FAIL"}
    try:out=run()
    except Exception as e:out={"status":"FAIL","checks":checks,"reason":str(e)[:500]}
    (EV/"xyops-mcp-result.json").write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out,indent=2))
    sys.exit(0 if out["status"]=="PASS" else 1)
