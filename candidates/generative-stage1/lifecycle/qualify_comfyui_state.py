#!/usr/bin/env python3
"""Disposable, public-only actual ComfyUI persistent-state replacement probe.

This is an experiment/oracle, not a second Foundry lifecycle controller.
Never use it on an operator's data, private host, or production container.
"""
import argparse
import json
import subprocess
import time
import uuid

UID = "10001"
LABEL = "foundry.public-lifecycle-probe"
SLOTS = ("user", "input", "output", "models")
BASE = "/opt/comfy"
WORKFLOW = {"nodes": [], "links": [], "version": 0.4}
SETTINGS = {"foundry.synthetic.persistence": "fixture-v1"}


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True,
                            timeout=180, check=False)
    if check and result.returncode:
        raise RuntimeError(f"docker {args[0]} failed ({result.returncode}): {result.stderr[-3000:]}")
    return result.stdout.strip() if check else result


def receipt(phase, **fields):
    print(json.dumps({"phase": phase, **fields}, sort_keys=True), flush=True)


def container_exists(name):
    return name in docker("ps", "-a", "--format", "{{.Names}}").splitlines()


def volume_exists(name):
    return name in docker("volume", "ls", "--format", "{{.Name}}").splitlines()


def owned_volume(name, owner):
    return json.loads(docker("volume", "inspect", name))[0]["Labels"].get(LABEL) == owner


def inspect(name, owner):
    value = json.loads(docker("container", "inspect", name))[0]
    assert value["Config"]["Labels"].get(LABEL) == owner, "foreign container"
    return value


def verify_runtime(name, owner, image, volumes):
    observed = inspect(name, owner)
    host = observed["HostConfig"]
    assert observed["Image"] == image
    assert observed["State"]["Running"]
    assert observed["Config"]["User"] == UID + ":" + UID
    assert host["ReadonlyRootfs"] and host["NetworkMode"] == "none"
    assert "ALL" in host["CapDrop"] and not host["Privileged"]
    assert any(x.startswith("no-new-privileges") for x in host["SecurityOpt"])
    mounts = {x["Destination"]: x for x in observed["Mounts"] if x["Type"] == "volume"}
    assert set(mounts) == {f"{BASE}/{s}" for s in SLOTS}, "extra or missing durable mount"
    for slot, volume in volumes.items():
        mount = mounts[f"{BASE}/{slot}"]
        assert mount["Name"] == volume and mount["RW"] == (slot != "models")
        assert owned_volume(volume, owner)
    assert set(host["Tmpfs"]) == {"/tmp", "/home/probe"}
    return observed["Id"]


def exec_python(name, source):
    return docker("exec", name, "python", "-c", source)


def healthy(name):
    code = ('import json,urllib.request; '
            'r=json.load(urllib.request.urlopen("http://127.0.0.1:8188/system_stats",timeout=3)); '
            'assert r["devices"] and r["devices"][0]["type"]=="cpu"')
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = docker("exec", name, "python", "-c", code, check=False)
        if not result.returncode:
            return
        if not json.loads(docker("container", "inspect", name))[0]["State"]["Running"]:
            break
        time.sleep(3)
    raise RuntimeError("actual application did not reach CPU HTTP readiness")


def run_app(name, owner, image, volumes):
    assert not container_exists(name)
    args = ["run", "-d", "--name", name, "--label", f"{LABEL}={owner}",
            "--network", "none", "--pull", "never", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", UID + ":" + UID, "--memory", "5g", "--pids-limit", "256",
            "--tmpfs", "/tmp:rw,nosuid,nodev,uid=10001,gid=10001,mode=1777,size=256m",
            "--tmpfs", "/home/probe:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700,size=128m"]
    for slot, volume in volumes.items():
        spec = f"type=volume,src={volume},dst={BASE}/{slot},volume-nocopy"
        if slot == "models":
            spec += ",readonly"
        args.extend(["--mount", spec])
    args += ["--entrypoint", "python", image, "main.py", "--cpu", "--listen", "127.0.0.1",
             "--port", "8188", "--offline", "--disable-all-custom-nodes", "--disable-auto-launch",
             "--disable-assets", "--disable-dynamic-vram", "--user-directory", BASE + "/user",
             "--input-directory", BASE + "/input", "--output-directory", BASE + "/output",
             "--models-directory", BASE + "/models", "--temp-directory", "/tmp",
             "--previews-directory", "/tmp/previews"]
    docker(*args)
    healthy(name)
    return verify_runtime(name, owner, image, volumes)


HTTP_SETUP = r'''
import json, urllib.request, urllib.error
from pathlib import Path

def req(path, data=None, content_type=None):
    request = urllib.request.Request("http://127.0.0.1:8188" + path, data=data,
                                     headers={"Content-Type":content_type} if content_type else {})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read()
'''

WRITE_STATE = HTTP_SETUP + r'''
req("/settings", json.dumps({"foundry.synthetic.persistence":"fixture-v1"}).encode(), "application/json")
data = json.dumps({"nodes":[],"links":[],"version":0.4}).encode()
req("/userdata/foundry-fixture.json?overwrite=false", data, "application/json")
# No actual inference: these are synthetic payloads for file-retention checks.
Path("/opt/comfy/input/foundry-input.txt").write_text("input-v1")
Path("/opt/comfy/output/foundry-output.txt").write_text("output-v1")
Path("/tmp/foundry-ephemeral").write_text("must disappear")
for path in ("/opt/comfy/foundry-root-write", "/opt/comfy/models/foundry-model-write"):
    try:
        Path(path).write_text("forbidden")
    except OSError:
        pass
    else:
        raise AssertionError("runtime or model store unexpectedly writable")
'''

VERIFY_STATE = HTTP_SETUP + r'''
assert json.loads(req("/settings"))["foundry.synthetic.persistence"] == "fixture-v1"
assert json.loads(req("/userdata/foundry-fixture.json")) == {"nodes":[],"links":[],"version":0.4}
assert Path("/opt/comfy/input/foundry-input.txt").read_text() == "input-v1"
assert Path("/opt/comfy/output/foundry-output.txt").read_text() == "output-v1"
'''

NO_CLOBBER = HTTP_SETUP + r'''
try:
    req("/userdata/foundry-fixture.json?overwrite=false", b"overwrite-attempt", "application/json")
except urllib.error.HTTPError as error:
    assert error.code == 409
else:
    raise AssertionError("existing workflow was overwritten")
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    image = docker("image", "inspect", "--format", "{{.Id}}", args.image)
    assert image.startswith("sha256:") and len(image) == 71
    owner = uuid.uuid4().hex[:16]
    name = "foundry-comfy-state-" + owner
    volumes = {slot: f"{name}-{slot}" for slot in SLOTS}
    created = []
    try:
        receipt("observe/discover", image_id=image, owned_container_present=container_exists(name),
                durable_volumes_present=[s for s, v in volumes.items() if volume_exists(v)])
        assert not container_exists(name) and not any(volume_exists(v) for v in volumes.values())
        receipt("plan", actions=["create-four-owned-volumes", "seed-empty-permissions",
                                 "create-immutable-readonly-runtime", "verify"])
        for slot, volume in volumes.items():
            docker("volume", "create", "--label", f"{LABEL}={owner}", volume)
            created.append(volume)
            assert owned_volume(volume, owner)
            # One-time initializer acts only on newly-created, empty test volumes.
            docker("run", "--rm", "--network", "none", "--pull", "never", "--read-only",
                   "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "CHOWN",
                   "--cap-add", "FOWNER", "--security-opt", "no-new-privileges",
                   "--mount", f"type=volume,src={volume},dst=/seed,volume-nocopy",
                   "--entrypoint", "python", image, "-c",
                   'import os; assert not os.listdir("/seed"); os.chown("/seed",10001,10001); os.chmod("/seed",0o750)')
        receipt("apply", action="create-runtime")
        first_id = run_app(name, owner, image, volumes)
        exec_python(name, WRITE_STATE)
        exec_python(name, VERIFY_STATE)
        exec_python(name, NO_CLOBBER)
        receipt("verify", action="create", read_only_runtime=True,
                settings_workflow_and_files=True, no_clobber=True)
        receipt("observe/discover", current_runtime=first_id, state="running")
        assert verify_runtime(name, owner, image, volumes) == first_id
        receipt("plan", action="NOOP", reason="observed exact image, runtime and durable bindings")
        exec_python(name, VERIFY_STATE)
        receipt("verify", action="NOOP", same_runtime=True)
        # Reobserve ownership, quiesce, verify stopped/absent, and retain volumes.
        receipt("observe/discover", current_runtime=first_id, durable_slots=list(SLOTS))
        assert verify_runtime(name, owner, image, volumes) == first_id
        receipt("plan", action="replace-runtime", retain_data=True, same_image_id=image)
        docker("stop", "--time", "20", name)
        assert not inspect(name, owner)["State"]["Running"]
        docker("rm", name)
        assert not container_exists(name)
        assert all(volume_exists(v) and owned_volume(v, owner) for v in volumes.values())
        receipt("apply", action="retired-runtime-retained-state")
        second_id = run_app(name, owner, image, volumes)
        assert second_id != first_id
        exec_python(name, VERIFY_STATE)
        exec_python(name, NO_CLOBBER)
        exec_python(name, 'from pathlib import Path; assert not Path("/tmp/foundry-ephemeral").exists()')
        receipt("verify", action="replace-runtime", new_runtime=True,
                retained_user_config_and_workflow=True, retained_input_output=True,
                transient_marker_absent=True, image_id=image)
    except Exception:
        if container_exists(name):
            print(docker("logs", "--tail", "100", name, check=False).stdout, flush=True)
        raise
    finally:
        # This is fixture teardown, not a production delete-data operation.
        if container_exists(name):
            inspect(name, owner)
            docker("rm", "-f", name)
        for volume in created:
            if volume_exists(volume):
                assert owned_volume(volume, owner)
                docker("volume", "rm", volume)
        assert not container_exists(name) and not any(volume_exists(v) for v in created)
    receipt("PASS", claim="actual-comfyui-readonly-runtime-same-image-replacement-public-fixture",
            non_claims=["cross-version migration", "snapshot/restore", "TrueNAS realization", "GPU", "inference"])


if __name__ == "__main__":
    main()
