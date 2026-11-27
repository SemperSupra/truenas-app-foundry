#!/usr/bin/env python3
"""Two actual ComfyUI workers, one immutable model-view fixture, independent app state.

Runs only on a disposable public CI Docker engine. Tiny synthetic safetensors
are enumeration/hash fixtures, NOT executable model compatibility claims.
"""
import argparse
import hashlib
import json
import uuid

from qualify_comfyui_state import (
    BASE, LABEL, container_exists, docker, exec_python, inspect, owned_volume,
    receipt, run_app, verify_runtime, volume_exists, HTTP_SETUP,
)

CATEGORIES = ("checkpoints", "loras", "vae", "controlnet", "embeddings",
              "text_encoders", "clip_vision", "upscale_models", "diffusion_models",
              "background_removal", "audio_encoders", "frame_interpolation")
FILE = "family/fixture.safetensors"


def seed(image, volume, source):
    docker("run", "--rm", "--network", "none", "--pull", "never", "--read-only",
           "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "CHOWN",
           "--cap-add", "FOWNER", "--security-opt", "no-new-privileges",
           "--mount", f"type=volume,src={volume},dst=/seed,volume-nocopy",
           "--entrypoint", "python", image, "-c", source)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    image = docker("image", "inspect", "--format", "{{.Id}}", args.image)
    assert image.startswith("sha256:") and len(image) == 71
    owner = uuid.uuid4().hex[:16]
    prefix = "foundry-comfy-shared-" + owner
    names = [prefix + "-a", prefix + "-b"]
    shared = prefix + "-models"
    bindings = [{**{slot: f"{name}-{slot}" for slot in ("user", "input", "output")},
                 "models": shared} for name in names]
    volume_names = {v for binding in bindings for v in binding.values()}
    created = []
    # Deliberately non-default hierarchy: actual extra_model_paths configuration must
    # work or the API enumeration assertions will fail.
    config = "fixture_view:\n  base_path: /opt/comfy/models/projection\n"
    config += "".join(f"  {category}: {category}\n" for category in CATEGORIES)
    payload = ("import os; assert not os.listdir('/seed'); "
               "os.chown('/seed',10001,10001); os.chmod('/seed',0o750)")
    ids = []
    try:
        assert not any(container_exists(n) for n in names)
        assert not any(volume_exists(v) for v in volume_names)
        receipt("observe/discover", shared_view_present=False, runtime_count=0, image_id=image)
        receipt("plan", action="create-two-independent-workers-one-readonly-model-view",
                durable_slots=len(volume_names), categories=list(CATEGORIES))
        for volume in sorted(volume_names):
            docker("volume", "create", "--label", f"{LABEL}={owner}", volume)
            created.append(volume)
            assert owned_volume(volume, owner)
            if volume == shared:
                # A valid tiny safetensors container, distinct contents per category;
                # deliberately not valid weights for any generative architecture.
                source = "import os; assert not os.listdir('/seed')\n" + r'''
from pathlib import Path
import json, struct
for i, category in enumerate(CATEGORIES):
    path = Path("/seed/projection") / category / "family" / "fixture.safetensors"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps({"fixture":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}).encode()
    header += b" " * ((-len(header)) % 8)
    path.write_bytes(struct.pack("<Q",len(header)) + header + struct.pack("<f",float(i)))
    path.chmod(0o444)
p = Path('/seed/extra_model_paths.yaml')
p.write_text(CONFIG, encoding='utf-8')
p.chmod(0o444)
os.chmod('/seed', 0o555)
'''
                seed(image, volume, "CATEGORIES=" + repr(CATEGORIES) + "\nCONFIG=" + repr(config) + "\n" + source)
            else:
                seed(image, volume, payload)
        for name, binding in zip(names, bindings):
            ids.append(run_app(name, owner, image, binding, extra_args=(
                "--extra-model-paths-config", BASE + "/models/extra_model_paths.yaml")))
        receipt("apply", runtime_count=2, shared_model_volume=True)
        scan = HTTP_SETUP + "\nimport hashlib\n"
        scan += "categories=" + repr(CATEGORIES) + "\n"
        scan += r'''
result={}
for category in categories:
    listing = json.loads(req("/models/" + category))
    assert "family/fixture.safetensors" in listing, (category, listing)
    path = Path("/opt/comfy/models/projection") / category / "family/fixture.safetensors"
    result[category] = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        path.write_bytes(b"forbidden")
    except OSError:
        pass
    else:
        raise AssertionError("shared model bytes unexpectedly writable")
print(json.dumps(result, sort_keys=True))
'''
        hashes = [json.loads(exec_python(name, scan)) for name in names]
        assert hashes[0] == hashes[1] and set(hashes[0]) == set(CATEGORIES)
        assert len(set(hashes[0].values())) == len(CATEGORIES), "fixture identity collision"
        for idx, name in enumerate(names):
            value = "worker-" + str(idx)
            code = HTTP_SETUP + "\nreq('/settings', json.dumps({'foundry.fixture.worker':" + repr(value) + "}).encode(), 'application/json')"
            exec_python(name, code)
        for idx, name in enumerate(names):
            code = HTTP_SETUP + "\nassert json.loads(req('/settings'))['foundry.fixture.worker']==" + repr("worker-" + str(idx))
            exec_python(name, code)
            assert verify_runtime(name, owner, image, bindings[idx]) == ids[idx]
        receipt("verify", both_workers_list_same_assets=True, exact_sha256_equal=True,
                shared_model_write_denied=True, independent_settings=True,
                categories=list(CATEGORIES), fixture_hashes=hashes[0])
        receipt("observe/discover", image_id=image, both_workers_unchanged=True)
        receipt("plan", action="NOOP")
        assert all(verify_runtime(n, owner, image, b) == i for n, b, i in zip(names, bindings, ids))
        assert json.loads(exec_python(names[0], scan)) == hashes[0]
        receipt("verify", action="NOOP", same_runtime_ids=True, same_asset_hashes=True)
    except Exception:
        for name in names:
            if container_exists(name):
                output = docker("logs", "--tail", "80", name, check=False)
                print(output.stdout + output.stderr, flush=True)
        raise
    finally:
        for name in names:
            if container_exists(name):
                inspect(name, owner)
                docker("rm", "-f", name)
        for volume in reversed(created):
            if volume_exists(volume):
                assert owned_volume(volume, owner)
                docker("volume", "rm", volume)
        assert not any(container_exists(n) for n in names)
        assert not any(volume_exists(v) for v in created)
    receipt("PASS", claim="two-actual-comfy-workers-shared-readonly-asset-enumeration",
            non_claims=["model inference", "SwarmUI compatibility", "InvokeAI compatibility",
                        "actual model acquisition", "GPU residency", "TrueNAS realization"])


if __name__ == "__main__":
    main()
