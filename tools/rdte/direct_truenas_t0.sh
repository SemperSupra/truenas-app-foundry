#!/usr/bin/env bash
# Standalone Foundry public GHA T0, adapted from proven public reference:
# SemperSupra/agent-dispatch@experiment/gha-kvm-system-rdte
# scripts/gha_kvm_truenas_rdte.sh (source blob aee419c4a97829da4d2d7e833aa070d943b2f66e).
# No Agent Dispatch source, runtime, dispatcher, workflow or site access is needed.
set -euo pipefail

usage() { echo 'usage: direct_truenas_t0.sh --out FILE [--state-dir DIR]' >&2; }
OUT=''
STATE_DIR=''
while (( $# )); do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done
[[ -n "$OUT" ]] || { usage; exit 2; }
[[ -n "$STATE_DIR" ]] || STATE_DIR="$(mktemp -d -t foundry-truenas-t0.XXXXXX)"
mkdir -p "$STATE_DIR" "$(dirname "$OUT")"
STATE_DIR="$(realpath "$STATE_DIR")"
OUT="$(realpath -m "$OUT")"
[[ "$OUT" != "$STATE_DIR/"* ]] || { echo "evidence must survive disposable teardown" >&2; exit 2; }

# Exact TrueNAS target and vendor SHA sidecar, preserved from AD public registry.
VERSION="25.04.2.6"
ISO_NAME="TrueNAS-SCALE-25.04.2.6.iso"
ISO_URL="https://download.truenas.com/TrueNAS-SCALE-Fangtooth/25.04.2.6/${ISO_NAME}"
SHA_URL="${ISO_URL}.sha256"
EXPECTED_VERSION="TrueNAS-25.04.2.6"
REF_SOURCE="SemperSupra/agent-dispatch experiment/gha-kvm-system-rdte scripts/gha_kvm_truenas_rdte.sh"
SOURCE_BLOB_SHA="aee419c4a97829da4d2d7e833aa070d943b2f66e"
RAM_MIB=8192
VCPUS=2
EXPECTED_SHA=""
OBSERVED_SHA=""
GRUB_PATH=""
QEMU_PID=""
PHASE="preflight"
DETAIL=""
CLASSIFICATION="HARNESS_FAILURE"
ORACLE="false"
QEMU_ALIVE="false"
SERIAL_MARKER="false"
STARTED="$(date +%s)"

receipt() {
  local rc=$?
  trap - EXIT INT TERM
  # Never confuse process cleanup with a TrueNAS guest acceptance verdict.
  if [[ -n "$QEMU_PID" ]]; then
    sudo -n kill "$QEMU_PID" >/dev/null 2>&1 || true
    sleep 1
    sudo -n kill -9 "$QEMU_PID" >/dev/null 2>&1 || true
  fi
  local zero_residue="true"
  [[ ! -d "$STATE_DIR" ]] || {
    sudo -n rm -rf -- "$STATE_DIR" || zero_residue="false"
  }
  export RDTE_OUT="$OUT" RDTE_VERSION="$VERSION" RDTE_CLASS="$CLASSIFICATION"
  export RDTE_ORACLE="$ORACLE" RDTE_PHASE="$PHASE" RDTE_DETAIL="$DETAIL"
  export RDTE_EXPECTED="$EXPECTED_SHA" RDTE_OBSERVED="$OBSERVED_SHA"
  export RDTE_GRUB="$GRUB_PATH" RDTE_QEMU_ALIVE="$QEMU_ALIVE"
  export RDTE_SERIAL="$SERIAL_MARKER" RDTE_ZERO_RESIDUE="$zero_residue"
  export RDTE_STARTED="$STARTED" RDTE_SOURCE_BLOB="$SOURCE_BLOB_SHA"
  python3 - <<'PY'
import json, os, pathlib, time
e=os.environ
value={
 "schema":"foundry-standalone-native-truenas-t0/v1",
 "classification":e["RDTE_CLASS"],
 "oracleSatisfied":e["RDTE_ORACLE"]=="true",
 "rung":"T0",
 "target_version":e["RDTE_VERSION"],
 "expected_system_version":"TrueNAS-25.04.2.6",
 "phase":e["RDTE_PHASE"],
 "detail":e["RDTE_DETAIL"][:400],
 "vendor_iso_sha256_expected":e["RDTE_EXPECTED"] or None,
 "vendor_iso_sha256_observed":e["RDTE_OBSERVED"] or None,
 "grub_source":e["RDTE_GRUB"] or None,
 "qemu_alive_at_gate":e["RDTE_QEMU_ALIVE"]=="true",
 "serial_trueNAS_marker":e["RDTE_SERIAL"]=="true",
 "zero_residue":e["RDTE_ZERO_RESIDUE"]=="true",
 "guest_profile":{"vcpu":2,"memory_mib":8192,"boot_disk":"24G","firmware":"bios","network":"qemu-user-isolated"},
 "reference":{"repository":"SemperSupra/agent-dispatch","branch":"experiment/gha-kvm-system-rdte","script_blob_sha":e["RDTE_SOURCE_BLOB"]},
 "agent_dispatch_runtime_used":False,
 "trueNAS_installed":False,
 "native_app_f0_f5_accepted":False,
 "elapsed_s":int(time.time())-int(e["RDTE_STARTED"]),
}
pathlib.Path(e["RDTE_OUT"]).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps(value,sort_keys=True))
PY
  if [[ "$zero_residue" != true ]]; then
    echo "ERROR: disposable state residue detected" >&2
    exit 2
  fi
  if [[ "$ORACLE" != true ]]; then
    echo "T0 ${CLASSIFICATION}: ${PHASE}: ${DETAIL}" >&2
    exit 2
  fi
  exit 0
}
trap receipt EXIT

fail() { CLASSIFICATION="$1"; PHASE="$2"; DETAIL="$3"; exit 2; }

for cmd in curl sha256sum qemu-img qemu-system-x86_64 xorriso python3 sudo; do
  command -v "$cmd" >/dev/null 2>&1 || fail ENVIRONMENT_FAILURE preflight "missing prerequisite $cmd"
done
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail ENVIRONMENT_FAILURE preflight "not Linux x86_64"
sudo -n test -r /dev/kvm && sudo -n test -w /dev/kvm ||
  fail ENVIRONMENT_FAILURE preflight "KVM sudo boundary unavailable"
(( $(nproc) >= VCPUS )) || fail SKIPPED_GUARDRAIL preflight "insufficient vCPUs"
mem_kib="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
free_kib="$(df -Pk "$STATE_DIR" | awk 'NR==2 {print $4}')"
(( mem_kib >= 11*1024*1024 )) || fail SKIPPED_GUARDRAIL preflight "less than 11 GiB available RAM"
(( free_kib >= 28*1024*1024 )) || fail SKIPPED_GUARDRAIL preflight "less than 28 GiB free disk"

PHASE="vendor-acquisition"
curl --fail --location --retry 3 --retry-max-time 90 --connect-timeout 15 --max-time 150 \
  --silent --show-error "$SHA_URL" -o "$STATE_DIR/vendor.sha256" ||
  fail ENVIRONMENT_FAILURE vendor-acquisition "vendor SHA sidecar unavailable"
EXPECTED_SHA="$(grep -Eo '[0-9a-fA-F]{64}' "$STATE_DIR/vendor.sha256" | head -n1 | tr 'A-F' 'a-f')"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]] || fail HARNESS_FAILURE vendor-acquisition "malformed vendor SHA256"
ISO="$STATE_DIR/$ISO_NAME"
curl --fail --location --retry 3 --retry-max-time 180 --connect-timeout 20 --max-time 750 \
  --silent --show-error "$ISO_URL" -o "$ISO" ||
  fail ENVIRONMENT_FAILURE vendor-acquisition "exact vendor ISO unavailable"
OBSERVED_SHA="$(sha256sum "$ISO" | awk '{print $1}')"
[[ "$OBSERVED_SHA" == "$EXPECTED_SHA" ]] ||
  fail ORACLE_FAILURE vendor-acquisition "vendor media SHA mismatch"

PHASE="serial-observable-iso"
for candidate in /boot/grub/grub.cfg /EFI/BOOT/grub.cfg /efi/boot/grub.cfg; do
  if xorriso -osirrox on -indev "$ISO" -extract "$candidate" "$STATE_DIR/grub.cfg" >/dev/null 2>&1; then
    GRUB_PATH="$candidate"
    break
  fi
done
[[ -n "$GRUB_PATH" ]] || fail HARNESS_FAILURE serial-observable-iso "missing vendor GRUB configuration"
chmod u+w "$STATE_DIR/grub.cfg"
python3 - "$STATE_DIR/grub.cfg" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1])
data=p.read_text(encoding="utf-8",errors="replace")
prefix="insmod serial\nserial --unit=0 --speed=115200 --word=8 --parity=no --stop=1\nterminal_input serial\nterminal_output serial\nset timeout=0\n"
lines=[]
changed=False
for line in data.splitlines():
    s=line.lstrip()
    if (s.startswith("linux ") or s.startswith("linuxefi ")) and "console=ttyS0" not in line:
        line+=" console=ttyS0,115200"
        changed=True
    lines.append(line)
if not changed:
    raise SystemExit("installer GRUB has no Linux command")
p.write_text(prefix+"\n".join(lines)+"\n",encoding="utf-8")
PY
SERIAL_ISO="$STATE_DIR/truenas-serial.iso"
cp --reflink=auto "$ISO" "$SERIAL_ISO"
chmod u+w "$SERIAL_ISO"
xorriso -boot_image any keep -dev "$SERIAL_ISO" \
  -map "$STATE_DIR/grub.cfg" "$GRUB_PATH" -commit >"$STATE_DIR/xorriso-stdout.log" 2>"$STATE_DIR/xorriso-stderr.log" ||
  fail HARNESS_FAILURE serial-observable-iso "failed to patch GRUB for serial guest observation"

PHASE="native-guest-boot"
qemu-img create -q -f qcow2 "$STATE_DIR/boot.qcow2" 24G ||
  fail HARNESS_FAILURE native-guest-boot "cannot allocate sparse boot disk"
: > "$STATE_DIR/serial.log"
sudo -n qemu-system-x86_64 \
  -enable-kvm -cpu host -smp "$VCPUS" -m "$RAM_MIB" \
  -drive "file=$STATE_DIR/boot.qcow2,if=virtio,format=qcow2" \
  -cdrom "$SERIAL_ISO" -boot order=d \
  -netdev "user,id=net0,restrict=on" -device "virtio-net-pci,netdev=net0,mac=52:54:00:54:4e:26,addr=0x3" \
  -display none -monitor none -serial "file:$STATE_DIR/serial.log" \
  -daemonize -pidfile "$STATE_DIR/qemu.pid" ||
  fail ENVIRONMENT_FAILURE native-guest-boot "QEMU could not start"
QEMU_PID="$(sudo -n cat "$STATE_DIR/qemu.pid")"
[[ "$QEMU_PID" =~ ^[0-9]+$ ]] || fail HARNESS_FAILURE native-guest-boot "missing QEMU PID"
for attempt in $(seq 1 220); do
  if grep -Eqi 'TrueNAS|truenas-installer|TrueNAS Installer|Install/Upgrade' "$STATE_DIR/serial.log" 2>/dev/null; then
    SERIAL_MARKER="true"
  fi
  if sudo -n kill -0 "$QEMU_PID" >/dev/null 2>&1; then
    QEMU_ALIVE="true"
  else
    QEMU_ALIVE="false"
    break
  fi
  [[ "$SERIAL_MARKER" == "true" ]] && break
  sleep 3
done
if [[ "$SERIAL_MARKER" == "true" && "$QEMU_ALIVE" == "true" ]]; then
  CLASSIFICATION="SUPPORTED"
  ORACLE="true"
  PHASE="installer-boot"
  DETAIL="exact vendor ISO verified and real native KVM TrueNAS installer marker independently observed"
elif grep -Eqi 'Linux version|systemd|Starting' "$STATE_DIR/serial.log" 2>/dev/null; then
  fail INCONCLUSIVE installer-boot "Linux boot observed but vendor TrueNAS marker absent"
else
  fail ORACLE_FAILURE installer-boot "no TrueNAS installer marker within bounded native guest"
fi
