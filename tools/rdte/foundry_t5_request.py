#!/usr/bin/env python3
"""Fail-closed request admission for ONE native TrueNAS platform T5 guest.

This is an explicit source-contract gate, not an authorization to migrate an
Agent Dispatch App or to modify any physical TrueNAS/OCI installation.
"""
import argparse,json,pathlib,re,sys
ROOT=pathlib.Path(__file__).resolve().parents[2]
SCHEMA="foundry-native-truenas-platform-t5-request/v1"
def validate(obj):
 failures=[]
 if not isinstance(obj,dict):return ["request must be JSON object"]
 expected={"schema","request_id","version","rung","t3_run_id","t3_head_sha","t3_artifact_id","scope"}
 if set(obj)!=expected:failures.append("unknown/missing fields")
 if obj.get("schema")!=SCHEMA:failures.append("schema mismatch")
 if obj.get("scope")!="public-disposable-platform-nginx-only":failures.append("physical/product scope forbidden")
 if obj.get("version")!="25.04.2.6" or obj.get("rung")!="t5":failures.append("exact version/rung required")
 if not re.fullmatch(r"fndry-t5-25-04-2-6-[a-z0-9-]{8,64}",str(obj.get("request_id",""))):failures.append("request identifier invalid")
 if not isinstance(obj.get("t3_run_id"),int) or obj["t3_run_id"]<=0:failures.append("accepted T3 run ID missing")
 if not re.fullmatch("[0-9a-f]{40}",str(obj.get("t3_head_sha",""))):failures.append("T3 source SHA missing")
 if not isinstance(obj.get("t3_artifact_id"),int) or obj["t3_artifact_id"]<=0:failures.append("T3 evidence artifact missing")
 return failures
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--request",type=pathlib.Path,required=True)
 a=p.parse_args()
 expected_root=ROOT/"tools/rdte/requests/native-t5"
 # An explicit single owned path only: no arbitrary runner input.
 if a.request.resolve().parent!=expected_root.resolve():raise SystemExit("request outside bounded path")
 try: obj=json.loads(a.request.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError) as e:raise SystemExit("bad request:"+e.__class__.__name__)
 fail=validate(obj)
 print(json.dumps({"classification":"BLOCKED" if fail else "SOURCE_REQUEST_ADMITTED",
                   "not_real_t5_acceptance":True,"errors":fail,"request_id":obj.get("request_id")},sort_keys=True))
 return 2 if fail else 0
if __name__=="__main__":sys.exit(main())
