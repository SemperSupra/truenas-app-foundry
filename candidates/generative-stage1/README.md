# Public generative-app Stage 1 — source proposals only

This is **V1 public-safe pre-candidate scaffolding**, not published TrueNAS Apps, source-rendered iX catalog entries, tested upstream containers, or authorized releases. It contains four separate Compose-based app proposals: `comfyui-app`, `swarmui-app`, `invokeai-app`, and `ace-step-app`. The images are deliberately **unset**, so the app definitions cannot boot accidentally with unreviewed upstream images. Do not treat the CPU fixture as proof that those apps boot.

## Source and execution boundary

- Public upstream application links and ports are recorded in per-app `definition.json`; each `compose.yaml` binds to host loopback, drops capabilities, sets a non-root UID, and uses managed volumes rather than host paths.
- Per-app storage destinations and fixed UIDs are **unqualified proposals**. Some upstream images will need different UID, path, writable model/cache, command and authentication behavior. A profile-specific package/review must resolve those differences before runtime admission.
- No owner-specific host address, API credentials, model checkpoints, workload prompts, private repos, private evaluation logic, or private results belong here. No GPU reservation is included, and public runners never contact a private host.
- Public validation checks JSON contract/schema invariants and normalized Docker Compose config. The initial scaffold OCI build and CPU HTTP boot check exercise only a small, independently written **synthetic fixture**. Separate upstream qualification workflows build actual public application source; see the lifecycle supplement for the required state-preserving progression. They do **not** exercise or qualify ComfyUI, SwarmUI, InvokeAI, ACE-Step, GPU passthrough, inference, or native TrueNAS runtime realization.

## Reproduce (Docker Engine + Docker Compose plugin + Python 3)

```sh
python3 -m unittest discover -s candidates/generative-stage1/tests -p 'test_*.py' -v
for app in comfyui-app swarmui-app invokeai-app ace-step-app; do
  APP_IMAGE='ghcr.io/example.invalid/public-safe/placeholder@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
    docker compose -f "candidates/generative-stage1/apps/$app/compose.yaml" config --format json > "/tmp/$app.json"
  python3 tools/validate_generative_stage1.py --app "$app" --compose-json "/tmp/$app.json"
done
docker build -f candidates/generative-stage1/fixtures/Containerfile -t foundry-generative-cpu-fixture:v1 candidates/generative-stage1/fixtures
```

## Gates before a real candidate

1. Pin the exact upstream source revision, dependency versions, OCI image digest and license/SBOM for each independent product.
2. Qualify actual upstream containers, including startup, writable-path discovery, persistent state, read-only disposable runtime, repeat/replace, state-preserving rollback and model/plugin boundaries. See [container-first lifecycle gate](lifecycle/README.md).
3. Derive real native iX `ix-dev` source candidates from the qualified runtime/storage contract; qualify version-compatible rendering, target lowering and the existing F0-F5 lifecycle before authorized GPU HIL at the private target. Inert source probes do not qualify actual app packages.
4. Retain private promotion/release and live deployment holds. A green public workflow does **not** grant promotion authority.

Tracking: the peer-review/offload assignment in the private governance DLE issue #256; public details here deliberately contain no private IaC source or assessment.
