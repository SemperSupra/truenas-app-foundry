"""Read-only public GitHub run+artifact evidence gate for native TrueNAS T5.

No GitHub token, plugin, dispatcher, or private content. Deny foreign/stale or
missing T3 evidence. This does not itself constitute native T3 qualification.
"""
import json
import urllib.request

REPO="SemperSupra/truenas-app-foundry"
NAME="Foundry direct native TrueNAS T3 ZFS (no AD)"
ARTIFACT="foundry-native-25-04-2-6-t3-zfs"

class EvidenceError(ValueError):pass

def require(request,run,artifacts):
    if run.get("id")!=request["t3_run_id"] or run.get("head_sha")!=request["t3_head_sha"]:
        raise EvidenceError("unmatched T3 run identity")
    if run.get("status")!="completed" or run.get("conclusion")!="success" or run.get("name")!=NAME:
        raise EvidenceError("T3 terminal successful workflow absent")
    repo=(run.get("repository") or {}).get("full_name")
    if repo!=REPO:
        raise EvidenceError("T3 run from foreign repository")
    available=(artifacts or {}).get("artifacts",[])
    match=[a for a in available if a.get("id")==request["t3_artifact_id"]]
    if len(match)!=1:raise EvidenceError("T3 evidence artifact identity absent")
    a=match[0]
    if a.get("name")!=ARTIFACT or a.get("expired") is not False or a.get("size_in_bytes",0)<=0:
        raise EvidenceError("T3 receipt missing, expired or empty")
    if ((a.get("workflow_run") or {}).get("id"))!=request["t3_run_id"]:
        raise EvidenceError("T3 receipt not attached to accepted run")
    return True

def get(url):
    req=urllib.request.Request(url,headers={
        "Accept":"application/vnd.github+json",
        "User-Agent":"foundry-public-t5-evidence-gate"})
    with urllib.request.urlopen(req,timeout=20) as response:
        return json.load(response)

def verify(request):
    rid=request["t3_run_id"]
    url=f"https://api.github.com/repos/{REPO}/actions/runs/{rid}"
    run=get(url)
    artifacts=get(url+"/artifacts?per_page=100")
    return require(request,run,artifacts)
