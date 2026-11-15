# Agent Dispatch Foundry synthetic source contract (qualification-only)

Authority: private Foundry #353, #274, #290; Agent Dispatch private #748; disposable TrueNAS #396.

This fixture covers the public-safe *shape* of the planned control/worker App:
same image identity, no root or privileged mode, no host/container socket, control
loopback ingress only, custody read-only, effect ledger read-write and data retained
across App removal. The image host `registry.invalid` is intentionally non-pullable.
No private source/image digest, token, ZFS path or physical App state is contained here.

**Source and container evidence accepted (public synthetic only):**

- Public-synthetic two-service structural guardrail: [Foundry PR #167](https://github.com/SemperSupra/truenas-app-foundry/pull/167), source CI 43684217126 PASS.
- Generic source lifecycle identity/foreign replay hardening: [Foundry PR #166](https://github.com/SemperSupra/truenas-app-foundry/pull/166), lifecycle CI 43684075779 PASS.
- Runnable *synthetic Go*, nonprivileged OCI + Compose 2× teardown/recreate external state: [Foundry PR #168](https://github.com/SemperSupra/truenas-app-foundry/pull/168), run 43684427791 PASS. Local-only image ID `sha256:2a160c9dcd84717434f5d50bf65130c58b8ba2a7d10e136caebccb16d6397823`, not published.
- **Official upstream TrueNAS Apps source-render** of `ix-dev/community/agent-dispatch-synthetic`: [Foundry PR #169](https://github.com/SemperSupra/truenas-app-foundry/pull/169), corrected head `ed239e1d7a8bf3b5bfa3137c3b09aa9a1ad17dcb`, native public [GHA run 43685303220](https://github.com/SemperSupra/truenas-app-foundry/actions/runs/43685303220) PASS. Upstream `truenas/apps@532236882212e8c5e51d5b49cfe2c6ce3dd5675e`, iX 2.3.4, normalized Compose `sha256:c3f8626b8bbdea7c1dc66904c5db84e39b668a7dc104995e85ff81aeff208a2c`. Original run 43684899137 RED (unquoted dummy image digest), first correction run 43685093998 RED (temporary root-owned render cleanup); both retained in governing private DLE #353. This is a source-render PASS, **not native Apps execution**.

**Still not qualified:** Foundry per-product F0–F5 on exact native TrueNAS versions, actual private Go image/registry pull, physical host-path UID/ACL and custody/ledger, cross-host fencing, state-preserving cutover/rollback, official catalog submission. This candidate is intentionally nonpullable: it must never be deployed as-is, and is not yet a fully admitted Foundry product inventory entry.

Next independent batches: create an immutable publicly usable harmless Go fixture image or transportable OCI archive; consume existing Agent Dispatch #396 one-heavyweight-slot disposable native TrueNAS KVM; prove product F0–F5 with exact middleware evidence and teardown; then separately qualify the actual private image and reversible site migration. Production host mutation and credentials remain private/independently governed.
