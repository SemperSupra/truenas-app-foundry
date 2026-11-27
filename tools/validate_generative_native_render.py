#!/usr/bin/env python3
"""Render-only probes with the established pinned iX materializer."""
import argparse
import hashlib
import json
import pathlib
import shutil
import tempfile

from validate_truenas_materialization import checkout_upstream, load_pin, normalize_rendered, security

ROOT = pathlib.Path(__file__).resolve().parents[1] / "candidates" / "generative-stage1" / "native"
CASES = json.loads((ROOT / "contracts.json").read_text())["cases"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", choices=sorted(CASES), required=True)
    args = parser.parse_args()
    name = args.app
    expected = CASES[name]
    pin = load_pin()
    with tempfile.TemporaryDirectory(prefix="foundry-native-render-") as temp:
        checkout = checkout_upstream(pathlib.Path(temp), pin)
        dest = checkout / "ix-dev" / pin["train"] / name
        assert not dest.exists(), "refuse to overwrite upstream catalog app"
        shutil.copytree(ROOT / "ix-dev" / "community" / name, dest)
        lib = "base_v" + pin["library_version"].replace(".", "_")
        shutil.copytree(checkout / "ix-dev" / "community" / "ntfy" / "templates" / "library" / lib,
                        dest / "templates" / "library" / lib)
        compose = normalize_rendered(checkout, pin, {"app":name, "test_file":"basic-values.yaml"})
        assert set(compose["services"]) == {name}, "unexpected service"
        svc = compose["services"][name]
        sec = security(svc)
        assert svc["image"] == expected["fixture_image"], "not the inert pinned fixture image"
        assert svc["entrypoint"] == ["/bin/false"], "render probe must be non-deployable"
        assert sec["user"] == "10001:10001" and not sec["privileged"]
        assert "ALL" in sec["cap_drop"] and sec["no_new_privileges"]
        assert svc.get("read_only") is True and svc.get("network_mode") != "host"
        ports = svc.get("ports", [])
        assert len(ports) == 1 and ports[0]["host_ip"] == "127.0.0.1"
        assert int(ports[0]["target"]) == expected["port"] and int(ports[0]["published"]) == expected["port"]
        volumes = {m["target"]: m for m in svc.get("volumes", []) if isinstance(m, dict)}
        assert set(volumes) == {expected["models"], expected["outputs"]}
        for kind, target in (("models", expected["models"]), ("outputs", expected["outputs"])):
            mount = volumes[target]
            assert mount["type"] == "bind" and mount["source"] == f"/opt/tests/mnt/{name}/{kind}"
            assert bool(mount.get("read_only", False)) == (kind == "models")
        assert any(str(x).startswith("/tmp:") for x in svc.get("tmpfs", [])), "tmpfs missing"
        print(json.dumps({"app": name, "upstream_materializer": pin["ref"], "library_hash": pin["library_hash"],
                          "compose_sha256": hashlib.sha256(json.dumps(compose,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
                          "claim": "native-ix-source-render-inert-fixture-only"}, sort_keys=True))

if __name__ == "__main__":
    main()
