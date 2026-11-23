#!/usr/bin/env bash
# Public-safe RDTE: instantiate a source-pinned registry image on a disposable
# GHA runner, using the SAME security/options as the planned QEMU guest fixture.
# Proves local registry's real OCI image capacity and immutable content pulls.
# Does NOT interact with any TrueNAS VM, app middleware, private host or GHCR.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source_sha="$(PYTHONPATH="$repo_root/tests/consumers/model_compass" python3 -c 'from native_guest_registry import PRODUCT_SOURCE_SHA;print(PRODUCT_SOURCE_SHA)')"
registry_ref="$(PYTHONPATH="$repo_root/tests/consumers/model_compass" python3 -c 'from native_guest_registry import REGISTRY_REF;print(REGISTRY_REF)')"
port="$(PYTHONPATH="$repo_root/tests/consumers/model_compass" python3 -c 'from native_guest_registry import HOST_PORT;print(HOST_PORT)')"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKED: source SHA not pinned";exit 2; }
[[ "$registry_ref" =~ ^registry@sha256:[0-9a-f]{64}$ ]] || { echo "BLOCKED: registry digest not pinned";exit 2; }
[[ "$port" == 15431 ]] || { echo "BLOCKED: registry port drift";exit 2; }

state="${RUNNER_TEMP:-$(mktemp -d)}/compass-guest-registry-transport"
mkdir -p "$state/checkout"
cleanup() {
 docker rm -f compass-native-guest-registry-fixture compass-guest-pulled-check >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Public exact source only. No secrets/SSH keys, private model data, or image publication.
git -C "$state/checkout" init -q
git -C "$state/checkout" remote add origin https://github.com/SemperSupra/model-spelunker.git
git -C "$state/checkout" fetch --no-tags --depth=1 origin "$source_sha" -q
actual="$(git -C "$state/checkout" rev-parse FETCH_HEAD)"
test "$actual" = "$source_sha"
git -C "$state/checkout" checkout --quiet --detach "$actual"

docker run --detach --name compass-native-guest-registry-fixture \
  --read-only --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 64 --memory 256m \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  -e REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY=/tmp/registry \
  -p "127.0.0.1:$port:5000" \
  "$registry_ref" >/dev/null

ready=0
for rep in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 2 "http://127.0.0.1:$port/v2/" >/dev/null 2>&1; then ready=1;break;fi
  sleep 1
done
if test "$ready" -ne 1; then docker logs compass-native-guest-registry-fixture;exit 1;fi
test "$(docker inspect compass-native-guest-registry-fixture --format '{{.HostConfig.ReadonlyRootfs}}')" = "true"
test "$(docker inspect compass-native-guest-registry-fixture --format '{{index .HostConfig.PortBindings "5000/tcp" 0}}')" != "0.0.0.0"
echo "PASS: guest-shape registry source image booted read-only on runner loopback, no privileged daemon edits"

tag="127.0.0.1:$port/compass-guest-fixture:${source_sha:0:12}"
docker build -f "$state/checkout/deploy/model-compass/Dockerfile" \
  --build-arg SOURCE_REVISION="$source_sha" \
  -t "$tag" "$state/checkout"
docker push "$tag"
immutable="$(docker image inspect "$tag" --format '{{index .RepoDigests 0}}')"
[[ "$immutable" =~ ^127[.]0[.]0[.]1:15431/compass-guest-fixture@sha256:[0-9a-f]{64}$ ]] || {
 echo "BLOCKED: local registry did not return content-addressed image ref";exit 1;
}
printf '%s\n' "$immutable" > "$state/runner-oci-ref.txt"
docker image rm -f "$tag" >/dev/null
docker pull "$immutable"
if docker pull '127.0.0.1:15431/compass-guest-fixture@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' >/dev/null 2>&1;then
 echo "SECURITY FAIL: registry supplied unknown content digest";exit 1
fi
echo "PASS: full exact combined image push, discard mutable tag, digest-only pull, bad-digest rejection"

# The registry and pulled image are both disposable test fixtures; no private model calls.
mkdir -p "$state/state"
printf '%s\n' '{"schema":"synthetic","receipt":"guest-transport-test-only"}' > "$state/state/snapshot.json"
printf '%064d\n' 3 > "$state/token"
printf 'Authorization: Bearer %064d\n' 3 > "$state/auth-header"
sudo chown -R 65532:65532 "$state/state" "$state/token"
sudo chmod 0400 "$state/token"
docker run --detach --name compass-guest-pulled-check \
  --read-only --user 65532:65532 --cap-drop=ALL \
  --security-opt no-new-privileges:true --pids-limit 64 --memory 256m \
  -p 127.0.0.1:18096:8088 \
  -v "$state/state:/state:ro" -v "$state/token:/run/secrets/compass_token:ro" \
  "$immutable" >/dev/null
ready=0
for rep in $(seq 1 30); do
 if curl --fail --silent --show-error --max-time 2 http://127.0.0.1:18096/healthz >/dev/null 2>&1;then ready=1;break;fi
 sleep 1
done
if test "$ready" -ne 1;then docker logs compass-guest-pulled-check;exit 1;fi
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18096/v1/snapshot)" = 401
curl -fsS -H @"$state/auth-header" http://127.0.0.1:18096/v1/snapshot | grep -q guest-transport-test-only
echo "PASS: digest-pulled integrated product starts with external state and bearer protection"

docker rm -f compass-guest-pulled-check compass-native-guest-registry-fixture >/dev/null
test "$(cat "$state/state/snapshot.json")" = '{"schema":"synthetic","receipt":"guest-transport-test-only"}'
test "$(docker ps --filter name=compass-native-guest-registry-fixture --format '{{.Names}}' | wc -l)" = 0
echo "PASS: bounded guest-shape transport fixture fully removed; actual native QEMU guest F2-F6 NOT_RUN"
