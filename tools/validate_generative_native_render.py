#!/usr/bin/env python3
"""Render-only probes with the established pinned iX materializer."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

from validate_truenas_materialization import checkout_upstream, load_pin, normalize_rendered, security

ROOT = pathlib.Path(__file__).resolve().parents[1] / "candidates" / "generative-stage1" / "native"
CASES = json.loads((ROOT / "contracts.json").read_text())["cases"]
RENDERER_IMAGE = "ghcr.io/truenas/apps_validation@sha256:92fa1b88da88c30fbacc7dcbbea68e7bfc63c5924ae6d1018ed620b92d0a6058"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", choices=sorted(CASES), required=True)
    parser.add_argument("--ci-reclaim-generated-ownership", action="store_true",
                        help="Public disposable CI only: reclaim the exact generated directory after upstream root renderer")
    args = parser.parse_args()
    name = args.app
    expected = CASES[name]
    pin = load_pin()
    with tempfile.TemporaryDirectory(prefix="foundry-native-render-") as temp:
        checkout = checkout_upstream(pathlib.Path(temp), pin)
        # The pinned upstream script uses a mutable :latest renderer reference.
        # Make a single recorded substitution in this disposable checkout.
        ci = checkout / ".github" / "scripts" / "ci.py"
        source = ci.read_text(encoding="utf-8")
        old = 'CONTAINER_IMAGE = "ghcr.io/truenas/apps_validation:latest"'
        assert source.count(old) == 1, "upstream renderer declaration drift"
        ci.write_text(source.replace(old, f'CONTAINER_IMAGE = "{RENDERER_IMAGE}"'), encoding="utf-8")
        dest = checkout / "ix-dev" / pin["train"] / name
        assert not dest.exists(), "refuse to overwrite upstream catalog app"
        shutil.copytree(ROOT / "ix-dev" / "community" / name, dest)
        lib = "base_v" + pin["library_version"].replace(".", "_")
        shutil.copytree(checkout / "ix-dev" / "community" / "ntfy" / "templates" / "library" / lib,
                        dest / "templates" / "library" / lib)
        rendered = dest / "templates" / "rendered"
        try:
            compose = normalize_rendered(checkout, pin, {"app":name, "test_file":"basic-values.yaml"})
        finally:
            # Upstream creates this directory as root; reclaim only this generated
            # subtree in the private temporary checkout, never the source tree or host paths.
            if rendered.is_symlink():
                raise RuntimeError("renderer produced an unexpected symlink")
            if rendered.exists():
                assert rendered.resolve() == rendered and rendered.is_dir()
                assert rendered.is_relative_to(pathlib.Path(temp))
                if args.ci_reclaim_generated_ownership:
                    subprocess.run(["sudo", "-n", "chown", "-R", "-h", "-P", "--",
                                    f"{os.getuid()}:{os.getgid()}", str(rendered)], check=True)
                elif not os.access(rendered, os.W_OK | os.X_OK):
                    raise RuntimeError("generated directory requires explicit disposable CI ownership cleanup")
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
        receipt = {"app": name, "upstream_materializer": pin["ref"], "library_hash": pin["library_hash"],
                   "renderer_image": RENDERER_IMAGE,
                   "compose_sha256": hashlib.sha256(json.dumps(compose,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
                   "claim": "native-ix-source-render-inert-fixture-only"}
    # Only emit PASS evidence after TemporaryDirectory teardown succeeds.
    print(json.dumps(receipt, sort_keys=True))

if __name__ == "__main__":
    main()
