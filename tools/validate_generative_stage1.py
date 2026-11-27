#!/usr/bin/env python3
"""Fail-closed static gates for public V1 pre-candidates, not TrueNAS runtime qualification."""
import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "candidates" / "generative-stage1"
EXPECTED = {"comfyui-app": 8188, "swarmui-app": 7801, "invokeai-app": 9090, "ace-step-app": 7860}
SCHEMA = "foundry.generative.stage1.v1"


def validate_definition(name: str) -> dict:
    if name not in EXPECTED:
        raise ValueError(f"unknown candidate {name}")
    path = ROOT / "apps" / name / "definition.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema") != SCHEMA or obj.get("name") != name or obj.get("phase") != "draft-source-only":
        raise ValueError(f"{name}: invalid identity or phase")
    upstream = obj.get("upstream", {})
    if upstream.get("container_port") != EXPECTED[name] or not re.fullmatch(r"https://github[.]com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", upstream.get("source_repository", "")):
        raise ValueError(f"{name}: invalid upstream source or port")
    if obj.get("runtime_target") != "truenas-scale-apps":
        raise ValueError(f"{name}: invalid runtime target")
    artifact = obj.get("artifact", {})
    if (artifact.get("source_type"), artifact.get("image_digest"), artifact.get("image_approval_required"), artifact.get("rootless_runtime_qualified")) != ("compose-proposal", None, True, False):
        raise ValueError(f"{name}: image must remain review-gated and runtime unqualified")
    b = obj.get("boundaries", {})
    if b != {"default_host_bind":"127.0.0.1", "host_path_mounts_allowed":False, "raw_credentials_allowed":False, "public_data_only":True}:
        raise ValueError(f"{name}: invalid admission boundary")
    q = obj.get("validation", {})
    for key, expected in {"upstream_image_boot":"not-qualified","gpu_hil":"local-only","native_ix_source_render":"not-qualified","private_promotion":"not-authorized","cpu_boot":"surrogate-only"}.items():
        if q.get(key) != expected:
            raise ValueError(f"{name}: false qualification claim: {key}")
    return obj


def validate_compose(name: str, data: dict) -> None:
    if name not in EXPECTED:
        raise ValueError(f"unknown candidate {name}")
    services = data.get("services", {})
    if set(services) != {"app"}:
        raise ValueError(f"{name}: unexpected service set")
    app = services["app"]
    if not app.get("read_only") or app.get("privileged") or app.get("user") != "10001:10001":
        raise ValueError(f"{name}: invalid runtime privilege boundary")
    if "ALL" not in app.get("cap_drop", []) or not any(str(x).startswith("no-new-privileges") for x in app.get("security_opt", [])):
        raise ValueError(f"{name}: missing cap/security opt")
    if app.get("network_mode") == "host":
        raise ValueError(f"{name}: host networking forbidden")
    ports = app.get("ports", [])
    if len(ports) != 1 or str(ports[0].get("host_ip")) != "127.0.0.1" or int(ports[0].get("target", -1)) != EXPECTED[name]:
        raise ValueError(f"{name}: port or interface drift")
    mounts = app.get("volumes", [])
    if len(mounts) != 2 or any(x.get("type") != "volume" or x.get("source") not in ("models","outputs") for x in mounts):
        raise ValueError(f"{name}: unexpected volume mount")
    if not any(x.get("source") == "models" and x.get("read_only") for x in mounts):
        raise ValueError(f"{name}: models volume not read only")
    if any(str(k).endswith("_KEY") or "TOKEN" in str(k) for k in app.get("environment", {})):
        raise ValueError(f"{name}: inline secret environment forbidden")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--app", choices=sorted(EXPECTED), required=True)
    p.add_argument("--compose-json", type=pathlib.Path)
    args = p.parse_args()
    validate_definition(args.app)
    if args.compose_json:
        validate_compose(args.app, json.loads(args.compose_json.read_text(encoding="utf-8")))
    print(f"PASS public Stage 1 {args.app}: proposal contract" + (" + normalized Compose boundary" if args.compose_json else ""))

if __name__ == "__main__":
    main()
