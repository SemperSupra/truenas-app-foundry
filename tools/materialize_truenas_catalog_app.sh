#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat >&2 <<'EOF'
usage: materialize_truenas_catalog_app.sh \
  --source <ix-dev app dir> --train <train> --app <name> \
  --apps-commit <40-hex> --validator <image@sha256:digest> \
  --source-date-epoch <unix-seconds> --output <dir>
EOF
  exit 64
}

SOURCE=""
TRAIN=""
APP=""
APPS_COMMIT=""
VALIDATOR=""
OUTPUT=""
SOURCE_DATE_EPOCH_VALUE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --train) TRAIN="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --apps-commit) APPS_COMMIT="$2"; shift 2 ;;
    --validator) VALIDATOR="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --source-date-epoch) SOURCE_DATE_EPOCH_VALUE="$2"; shift 2 ;;
    *) usage ;;
  esac
done

[[ -n "$SOURCE" && -n "$TRAIN" && -n "$APP" && -n "$APPS_COMMIT" && -n "$VALIDATOR" && -n "$OUTPUT" && -n "$SOURCE_DATE_EPOCH_VALUE" ]] || usage
[[ "$SOURCE_DATE_EPOCH_VALUE" =~ ^[0-9]{9,}$ ]] || { echo "invalid source date epoch" >&2; exit 78; }
[[ "$APPS_COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid apps commit" >&2; exit 78; }
[[ "$VALIDATOR" =~ @sha256:[0-9a-f]{64}$ ]] || { echo "validator must be digest-pinned" >&2; exit 78; }
[[ "$TRAIN" =~ ^[a-z][a-z0-9_-]*$ ]] || { echo "invalid train" >&2; exit 78; }
[[ "$APP" =~ ^[a-z]([-a-z0-9]*[a-z0-9])?$ ]] || { echo "invalid app name" >&2; exit 78; }
[[ -d "$SOURCE" && -f "$SOURCE/app.yaml" && -f "$SOURCE/questions.yaml" && -f "$SOURCE/templates/docker-compose.yaml" ]] || {
  echo "source is not an ix-dev app directory" >&2
  exit 78
}

for cmd in git docker python3 sha256sum awk find cp; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "missing command: $cmd" >&2; exit 78; }
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/foundry-catalog-materialize.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
REPO="$WORK/apps"
DEST="$REPO/ix-dev/$TRAIN/$APP"

git init -q "$REPO"
git -C "$REPO" remote add origin https://github.com/truenas/apps.git
git -C "$REPO" fetch -q --depth=1 origin "$APPS_COMMIT"
git -C "$REPO" checkout -q --detach FETCH_HEAD
[[ "$(git -C "$REPO" rev-parse HEAD)" == "$APPS_COMMIT" ]]

rm -rf -- "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -a "$SOURCE" "$DEST"

lib_version="$(awk '$1 == "lib_version:" {print $2; exit}' "$DEST/app.yaml")"
lib_hash="$(awk '$1 == "lib_version_hash:" {print $2; exit}' "$DEST/app.yaml")"
[[ "$lib_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$lib_hash" =~ ^[0-9a-f]{64}$ ]] || {
  echo "candidate has invalid library identity" >&2
  exit 78
}

base_dir="base_v${lib_version//./_}"
lib_dest="$DEST/templates/library/$base_dir"
if [[ ! -d "$lib_dest" ]]; then
  lib_source=""
  while IFS= read -r candidate_dir; do
    candidate_hash="$(find "$candidate_dir" -type f -exec sha256sum {} + | sort | awk '{print $1}' | sha256sum | awk '{print $1}')"
    [[ "$candidate_hash" == "$lib_hash" ]] || continue
    lib_source="$candidate_dir"
    break
  done < <(find "$REPO/ix-dev" -type d -path "*/templates/library/$base_dir" | sort)
  [[ -n "$lib_source" ]] || {
    echo "no exact TrueNAS library source matches $lib_version / $lib_hash" >&2
    exit 78
  }
  mkdir -p "$(dirname "$lib_dest")"
  cp -a "$lib_source" "$lib_dest"
fi

actual_lib_hash="$(find "$lib_dest" -type f -exec sha256sum {} + | sort | awk '{print $1}' | sha256sum | awk '{print $1}')"
[[ "$actual_lib_hash" == "$lib_hash" ]] || { echo "library hash mismatch" >&2; exit 78; }

docker pull -q "$VALIDATOR" >/dev/null
validator_ref="$(docker image inspect "$VALIDATOR" --format '{{index .RepoDigests 0}}')"
[[ "${validator_ref##*@}" == "${VALIDATOR##*@}" ]] || { echo "validator identity mismatch" >&2; exit 78; }

# The official publisher determines changes relative to Git state.
git -C "$REPO" add -N "ix-dev/$TRAIN/$APP"

docker run --rm --platform linux/amd64 \
  -e FAKE_ENV=1 \
  -v "$REPO:/workspace" \
  "$VALIDATOR" \
  apps_dev_charts_validate validate --path /workspace --base_branch HEAD

docker run --rm --platform linux/amd64 \
  -e FAKE_ENV=1 \
  -v "$REPO:/workspace" \
  "$VALIDATOR" \
  apps_catalog_update publish --path /workspace

git -C "$REPO" config user.name "SemperSupra Foundry"
git -C "$REPO" config user.email "foundry@invalid.local"
git -C "$REPO" add -A
GIT_AUTHOR_DATE="@$SOURCE_DATE_EPOCH_VALUE" GIT_COMMITTER_DATE="@$SOURCE_DATE_EPOCH_VALUE" \
  git -C "$REPO" commit -q -m "Foundry materialization publish"

docker run --rm --platform linux/amd64 \
  -e FAKE_ENV=1 \
  -v "$REPO:/workspace" \
  "$VALIDATOR" \
  apps_catalog_update update --path /workspace

version="$(awk '$1 == "version:" {print $2; exit}' "$DEST/app.yaml" | tr -d "'\"")"
[[ -n "$version" ]] || { echo "candidate version not found" >&2; exit 78; }
runtime_dir="$REPO/trains/$TRAIN/$APP/$version"
[[ -d "$runtime_dir" && -f "$REPO/catalog.json" ]] || {
  echo "official publisher did not emit expected runtime catalog artifact" >&2
  exit 1
}

rm -rf -- "$OUTPUT"
mkdir -p "$OUTPUT/trains/$TRAIN/$APP"
cp -a "$runtime_dir" "$OUTPUT/trains/$TRAIN/$APP/$version"

python3 - "$REPO/catalog.json" "$TRAIN" "$APP" "$OUTPUT/catalog-entry.json" <<'PY'
import json, pathlib, sys
src, train, app, out = sys.argv[1:]
data = json.loads(pathlib.Path(src).read_text(encoding="utf-8"))
try:
    entry = data[train][app]
except (KeyError, TypeError):
    raise SystemExit("published catalog.json is missing requested app")
pathlib.Path(out).write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

tree_hash="$(
  cd "$OUTPUT"
  find "trains/$TRAIN/$APP/$version" -type f -print0 |
    sort -z |
    xargs -0 sha256sum |
    sha256sum |
    awk '{print $1}'
)"
entry_hash="$(sha256sum "$OUTPUT/catalog-entry.json" | awk '{print $1}')"

python3 - "$OUTPUT/materialization.json" "$APPS_COMMIT" "$VALIDATOR" "$TRAIN" "$APP" "$version" "$lib_version" "$lib_hash" "$tree_hash" "$entry_hash" "$SOURCE_DATE_EPOCH_VALUE" <<'PY'
import json, pathlib, sys
(out, apps_commit, validator, train, app, version, lib_version, lib_hash, tree_hash, entry_hash, source_date_epoch) = sys.argv[1:]
value = {
    "schema_version": 1,
    "record_type": "truenas-runtime-catalog-materialization",
    "status": "PASS",
    "truenas_apps_commit": apps_commit,
    "validator": validator,
    "source_date_epoch": int(source_date_epoch),
    "train": train,
    "app": app,
    "version": version,
    "lib_version": lib_version,
    "lib_version_hash": lib_hash,
    "runtime_tree_sha256": tree_hash,
    "catalog_entry_sha256": entry_hash,
    "secrets_captured": False,
}
pathlib.Path(out).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(value, sort_keys=True))
PY
