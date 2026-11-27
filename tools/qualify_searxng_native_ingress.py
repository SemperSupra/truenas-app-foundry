#!/usr/bin/env python3
"""Public source-render qualification only; never applies to a live target."""
import argparse
import hashlib
import json
from pathlib import Path
import yaml

APP_IMAGE = "ghcr.io/searxng/searxng:2026.10.30-1cd13d98d@sha256:f1bbc31c7bef7a7d8dd2b105c8397eb7dea1eeb7eceebdd45c0c29aef38c0c91"
PORT = "8180"

def prepare(root):
    fixture = root / "basic-values.yaml"
    base = yaml.safe_load(fixture.read_text())
    assert base["network"]["host_network"] is False
    assert base["network"]["web_port"]["bind_mode"] == "published"
    for name, mode in (("foundry-exposed", "exposed"), ("foundry-loopback", "published")):
        values = yaml.safe_load(fixture.read_text())
        values["network"]["web_port"]["bind_mode"] = mode
        values["network"]["web_port"]["host_ips"] = ["127.0.0.1"] if mode == "published" else []
        (root / (name + ".yaml")).write_text(yaml.safe_dump(values, sort_keys=False))

def check(path, mode):
    raw = path.read_bytes()
    obj = yaml.safe_load(raw)
    svc = obj["services"]["searxng"]
    assert svc["image"] == APP_IMAGE, "unexpected image identity"
    assert not svc.get("privileged"), "privileged service"
    assert svc.get("network_mode") != "host", "host networking"
    assert set(svc.get("cap_add", [])) == {"SETUID", "SETGID"}
    assert "ALL" in svc.get("cap_drop", [])
    assert any("no-new-privileges" in str(x) for x in svc.get("security_opt", []))
    assert svc.get("healthcheck"), "healthcheck absent"
    env = svc.get("environment", {})
    assert str(env.get("GRANIAN_PORT")) == PORT
    volumes = svc.get("volumes", [])
    assert any(isinstance(v, dict) and v.get("target") == "/etc/searxng" for v in volumes)
    ports = svc.get("ports") or []
    if mode == "exposed":
        assert not ports, "unexpected published host port"
        assert PORT + "/tcp" in [str(x) for x in svc.get("expose", [])]
    elif mode == "loopback":
        assert len(ports) == 1, "unexpected publication count"
        p = ports[0]
        assert isinstance(p, dict) and p.get("host_ip") == "127.0.0.1", "non-loopback host binding"
        assert str(p.get("published")) == PORT and str(p.get("target")) == PORT
        assert p.get("protocol", "tcp") == "tcp"
    elif mode == "default":
        assert ports, "default publication baseline changed"
        assert any(isinstance(p, dict) and p.get("host_ip") in ("0.0.0.0", "::", None, "") for p in ports)
        try:
            check(path, "loopback")
        except AssertionError:
            pass
        else:
            raise AssertionError("wildcard render accepted as loopback")
    else:
        raise ValueError(mode)
    return {"classification": "SOURCE_RENDER_ONLY", "mode": mode,
            "compose_sha256": hashlib.sha256(raw).hexdigest(),
            "published_ports": ports, "exposed_ports": svc.get("expose", []),
            "image": svc["image"], "resource_limits": svc.get("deploy", {}).get("resources", {}).get("limits", {}),
            "native_runtime_qualified": False, "vpn_egress_qualified": False}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=["prepare", "default", "exposed", "loopback"])
    p.add_argument("path", type=Path)
    a = p.parse_args()
    if a.operation == "prepare":
        prepare(a.path)
    else:
        print(json.dumps(check(a.path, a.operation), sort_keys=True))
