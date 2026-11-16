#!/usr/bin/env bash
# Thin Foundry-owned entrypoint; leave the upstream T2/T6 KVM vendor source byte-for-byte pinned.
# This guard prevents a known missing product oracle from consuming a native KVM runner.
# It is not an F0-F5 product or host-qualification receipt.
set -euo pipefail

usage() {
  echo "Usage: guard_garm_controller_f0f5.sh --target-version VERSION --foundry-control-dir DIR --foundry-commit SHA --out RECEIPT [--state-dir DIR]"
  echo "Admits only existing T6 garm-controller-f0f5 vendor selector after native oracle exists."
}
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then usage; exit 0; fi

# Avoid later argv overriding the scope injected into the vendor entrypoint.
for arg in "$@"; do
  case "$arg" in
    --rung|--rung=*|--t6-product|--t6-product=*)
      echo "HOLD_GARM_F0F5_SELECTOR_OVERRIDE: selector is fixed by this entrypoint" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$SCRIPT_DIR/vendor/truenas-kvm/scripts"
VENDOR_ENTRYPOINT="$VENDOR_DIR/gha_kvm_truenas_rdte.sh"
NATIVE_PROBE="$VENDOR_DIR/truenas_middleware_garm_f0_f5_probe.py"

if [[ ! -f "$NATIVE_PROBE" || ! -f "$VENDOR_ENTRYPOINT" ]]; then
  echo "HOLD_NATIVE_GARM_F0F5_ORACLE_MISSING: vendor native probe/entrypoint absent; no KVM run admitted" >&2
  exit 2
fi

# The original vendor entrypoint still owns exact target/version, KVM, admission,
# oracle receipts and zero-residue cleanup. This thin guard grants no authority.
exec bash "$VENDOR_ENTRYPOINT" --rung t6 --t6-product garm-controller-f0f5 "$@"
