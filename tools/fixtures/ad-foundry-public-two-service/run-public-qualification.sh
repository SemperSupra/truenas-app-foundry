#!/usr/bin/env bash
# Public standalone GHA Docker behavioral surrogate, NEVER a private Agent Dispatch image.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"
work="$(mktemp -d -t ad-foundry-public-two-service.XXXXXX)"
export SYNTH_CUSTODY="$work/custody"
export SYNTH_LEDGER="$work/ledger"
cleanup() {
  docker compose -f compose.yaml -p foundrytwoservice down --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$work"
}
trap cleanup EXIT INT TERM
mkdir -m 755 "$SYNTH_CUSTODY"
mkdir -m 777 "$SYNTH_LEDGER" # public disposable test data ONLY, not production pattern
printf 'PUBLIC_SYNTHETIC_READY\n' > "$SYNTH_CUSTODY/readyz"

docker pull busybox:1.36.1
export SYNTH_IMAGE="$(docker image inspect busybox:1.36.1 --format '{{index .RepoDigests 0}}')"
{ [[ "$SYNTH_IMAGE" == busybox@sha256:* ]] || [[ "$SYNTH_IMAGE" == docker.io/library/busybox@sha256:* ]]; } &&
  [[ "${SYNTH_IMAGE##*@sha256:}" =~ ^[a-f0-9]{64}$ ]] ||
  { echo 'cannot bind exact public OCI digest' >&2; exit 2; }
docker compose -f compose.yaml -p foundrytwoservice config --quiet
docker compose -f compose.yaml -p foundrytwoservice config --format json > "$work/rendered.json"
python3 - "$work/rendered.json" "$SYNTH_IMAGE" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
c,w=d["services"]["control"],d["services"]["worker"]
for x in (c,w):
 assert x["image"]==sys.argv[2]
 assert x["user"]=="65532:65532"
 assert x["read_only"] is True
 assert "ALL" in x["cap_drop"]
 assert "no-new-privileges:true" in x["security_opt"]
 assert len(x["volumes"])==2
 assert sorted((m["target"],m["read_only"]) for m in x["volumes"])==[("/custody",True),("/ledger",False)]
assert c["ports"]==[{"mode":"ingress","target":8080,"published":"18092","protocol":"tcp","host_ip":"127.0.0.1"}]
assert not w.get("ports")
print("PUBLIC_SYNTHETIC_TWO_SERVICE_SOURCE_CONTRACT_PASS")
PY
for generation in 1 2; do
  docker compose -f compose.yaml -p foundrytwoservice up -d
  ok=false
  for n in $(seq 1 60); do
    if curl --fail --silent --max-time 1 http://127.0.0.1:18092/readyz | grep -qx PUBLIC_SYNTHETIC_READY &&
       [[ -f "$SYNTH_LEDGER/count" ]]; then ok=true;break;fi
    sleep 0.3
  done
  [[ "$ok" == true ]] || { docker compose -f compose.yaml -p foundrytwoservice ps;exit 2; }
  [[ "$(cat "$SYNTH_LEDGER/count")" == "$generation" ]] ||
    { echo "ledger generation mismatch" >&2;exit 2; }
  docker compose -f compose.yaml -p foundrytwoservice down --remove-orphans
  echo "PUBLIC_SYNTHETIC_TWO_SERVICE_GENERATION_${generation}_PASS"
done
echo "PUBLIC_SYNTHETIC_PULLABLE_DIGEST=$SYNTH_IMAGE"
echo "NOT_GO_IMAGE_NOT_NATIVE_TRUENAS_F0_F5"
