#!/usr/bin/env bash
# Only operates on a disposable hosted runner; never connects to TrueNAS or GHCR.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"
work="$(mktemp -d)"
export SYNTH_CUSTODY="$work/custody"
export SYNTH_LEDGER="$work/ledger"
cleanup() {
  docker compose -f compose.yaml down --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
go version
go test -count=1 ./...
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o "$work/agent-dispatch-synthetic" .
docker build --no-cache -t foundry-ad-synthetic:local -f Containerfile "$work"
mkdir "$SYNTH_CUSTODY" "$SYNTH_LEDGER"
printf 'public-synthetic\n' > "$SYNTH_CUSTODY/source.txt"
chmod 755 "$SYNTH_CUSTODY"
chmod 777 "$SYNTH_LEDGER"  # disposable synthetic test data, never a production pattern
docker compose -f compose.yaml config --quiet

for generation in 1 2; do
  docker compose -f compose.yaml up -d
  ready=false
  for attempt in $(seq 1 60); do
    if curl --fail --silent --max-time 1 http://127.0.0.1:18091/readyz > /dev/null; then
      ready=true
      break
    fi
    sleep 0.3
  done
  if [[ "$ready" != true ]]; then
    docker compose -f compose.yaml ps -a
    echo "synthetic readiness failed" >&2
    exit 1
  fi
  actual="$(cat "$SYNTH_LEDGER/count")"
  if [[ "$actual" != "$generation" ]]; then
    echo "synthetic persistence failure: expected $generation, saw $actual" >&2
    exit 1
  fi
  echo "PUBLIC_SYNTHETIC_GENERATION_${generation}_PASS"
  docker compose -f compose.yaml down --remove-orphans
done

docker image inspect foundry-ad-synthetic:local --format 'PUBLIC_SYNTHETIC_IMAGE_ID={{.Id}}'
echo "PUBLIC_SYNTHETIC_CONTAINER_LIFECYCLE_PASS no private image, no TrueNAS guest, no deployment"
