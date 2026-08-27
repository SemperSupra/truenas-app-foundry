# TrueNAS compatibility and testing strategy

## Decision

Use the real upstream TrueNAS source contract, real runner workload execution, and a deliberately small amount of real hardware-in-loop (HIL) testing.

Do **not** build a general `truenas-sim` or require a nested full TrueNAS VM in GitHub Actions at this stage.

This decision follows a red-team review of the cost/benefit of increasingly elaborate TrueNAS emulation.

## Why not a general TrueNAS simulator now

A simulator capable of meaningfully standing in for TrueNAS middleware would need to reproduce or track:

- JSON-RPC schemas and authentication/RBAC behavior;
- asynchronous middleware job behavior;
- Apps lifecycle states and progress;
- Custom App create/update/delete behavior;
- storage and ixVolume semantics;
- Docker Compose behavior;
- observed active-workload state;
- Containers and VM lifecycle semantics as those backends are added.

The more faithful such a simulator becomes, the more expensive it is to maintain. The less faithful it is, the less confidence it provides. A simulator can therefore become a second, weaker authority that still requires real HIL afterward.

Revisit a richer simulator only if the portfolio reaches a point where several consumers/backends share the same middleware integration, HIL is materially scarce/expensive, and the number of scenarios makes physical qualification impractical.

## Why not nested TrueNAS VM CI now

A full TrueNAS VM inside GitHub-hosted CI is an experimental possibility, not a dependable promotion gate. It adds nested-virtualization, boot/storage, performance, and runner-environment variability while still requiring real TrueNAS qualification afterward.

A future diagnostic experiment may explore this, but it is explicitly outside the current required test path.

## Current testing pyramid

### 1. Upstream source compatibility

Foundry pins exact public upstream identities and verifies the source-level assumptions consumed by the integration.

Current first profile:

- runtime target: TrueNAS SCALE Apps;
- TrueNAS version profile: 25.04.1;
- exact `truenas/middleware` commit;
- exact middleware source blobs for Apps CRUD, Custom App, Compose, lifecycle, and observed workload/state behavior;
- semantic markers for create/delete/state behavior.

The profile is `.foundry/truenas-compatibility/25.04.1-apps.json` and is validated by `tools/validate_truenas_source_contract.py`.

This is a **profile-update gate**: when a compatibility profile is moved to another TrueNAS release/commit, the update must prove that the assumptions still exist or deliberately revise them.

### 2. Provider contract/state tests from iX-derived fixtures

Provider tests should use fixtures and state expectations derived from the exact upstream compatibility profile rather than hand-invented TrueNAS behavior.

High-value fixture surfaces include:

- known App states;
- observed `active_workloads` fields;
- Custom App create inputs;
- delete options and the distinction between Compose-volume removal and conditional ixVolume dataset deletion;
- middleware job/result/error shapes that the provider actually consumes.

This remains normal unit/contract testing. It is not a middleware emulator.

### 3. Real workload execution

Run the provider-generated runner workload against a real Docker engine in public CI where possible.

This validates the actual container payload, runner bootstrap, runner tool checksum/version contract, Node runtime, security envelope, and process behavior without pretending Docker itself is TrueNAS.

### 4. Minimal real TrueNAS HIL

Real HIL remains authoritative for behavior that depends on a deployed TrueNAS system:

- authentication and minimum RBAC/API-key scope;
- JSON-RPC transport behavior;
- middleware job timing and cancellation/reconciliation behavior;
- real App lifecycle and observed state;
- networking and image-pull/cache behavior;
- App-pool/ZFS behavior;
- cleanup/orphan handling;
- resource pressure/admission behavior;
- future Containers and VM runtime behavior.

The objective is not to eliminate HIL. The objective is to make HIL small, focused, and unsurprising because cheaper gates already eliminated source, protocol-model, and workload defects.

## Relationship to the three TrueNAS GARM backends

The same testing strategy applies independently to each runtime-realization backend:

1. **Apps** — current implementation and current HIL target.
2. **Containers** — future; first establish an exact release-specific middleware compatibility profile, then implement/provider-test, then HIL.
3. **VMs** — future; first establish an exact release-specific `vm.*` compatibility profile, then implement/provider-test, then HIL.

Do not implement Incus/QEMU-backed emulation before the corresponding provider backend exists and there is evidence that such integration testing adds value beyond source contracts plus HIL.

## Deferred experiments

The following are explicitly deferred and are not required for promotion:

- general JSON-RPC `truenas-sim`;
- Docker-backed TrueNAS lifecycle simulation;
- Incus-backed TrueNAS Containers simulation;
- QEMU-backed TrueNAS VM simulation;
- full nested TrueNAS VM in GitHub Actions.

These may become worthwhile later, but must be justified against the maintenance cost and the fact that real TrueNAS remains the final authority.

## Promotion principle

A TrueNAS integration change should progress through the cheapest useful evidence first:

```text
pinned upstream source contract
        -> provider unit/contract tests
        -> real workload/runtime smoke where applicable
        -> minimal real TrueNAS HIL
```

Do not add a more elaborate test layer merely because it is technically possible. Add it only when it catches a demonstrated class of defects more economically than the layers above.
