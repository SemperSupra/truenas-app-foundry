# TrueNAS App Foundry terminology

This document is the canonical vocabulary for the Foundry and the related GARM/TrueNAS repositories. Use these terms consistently in issues, pull requests, code comments, architecture documents, and qualification evidence.

## Core terms

**Source application** — a TrueNAS App Store-compatible application/package used as canonical Foundry input. It includes application metadata, schema/defaults, templates, and the iX library behavior needed to render the application.

**Materialization control** — a known-good source application used to validate source rendering/materializer behavior. A control is test input, not a runtime target. The initial controls are `community/forgejo-runner` and `community/ntfy`.

**Source materializer** — the pinned logic/toolchain that resolves a source application plus selected values into a concrete deployment model. For the current TrueNAS source ecosystem this includes the exact `truenas/apps` revision, its iX library, upstream rendering logic, and normalization steps.

**Source rendering** — the transformation from source application + values through the source materializer into the normalized deployment intermediate representation. Use this term when no runtime-specific deployment semantics have yet been applied.

**Normalized deployment IR** — the normalized intermediate representation between source rendering and target-specific lowering. The current practical IR is normalized Docker Compose JSON. Treat this as an implementation-stage IR, not a promise that every future target can preserve every Compose semantic exactly.

**Target lowering** — target-specific translation from normalized deployment IR into the representation and semantics required by a runtime target. Lowering must identify unsupported or lossy mappings rather than silently discard source semantics.

**Deployment artifact** — the target-specific output produced by target lowering, such as Compose, Quadlet/systemd units, Kubernetes resources, or Nomad jobspecs. A deployment artifact is not evidence that the workload has actually run.

**Runtime realization** — creation/startup of the target-specific workload from a deployment artifact in the selected runtime environment. Use this term for `app.create`, `docker compose up`, Kubernetes apply/reconcile, and similar operations that actually instantiate work.

**Runtime target** — a runtime family on which a source application may ultimately execute after source rendering and any required target lowering. Examples include TrueNAS SCALE Apps, Docker Compose, Podman, Kubernetes, k3s, or Nomad. Source applications such as `ntfy` are not runtime targets.

**Target profile** — a specific, qualified variant of a runtime target, including version/platform constraints that materially affect behavior. Examples: `truenas-scale/25.04.1/linux-amd64`, `docker-compose/v2/linux-amd64`, or a future `kubernetes/<version>` profile.

**Materialization** — the umbrella process spanning source rendering, target lowering, and production of a target-specific deployment artifact. Do not use this word alone when the distinction between rendering, lowering, and runtime realization matters.

**Materialization class** — a category of runtime targets with similar semantic distance and lowering strategy from the normalized IR. Current/future classes are defined below.

**Qualification** — evidence that an exact source/application/materializer/adapter identity behaves correctly on an exact target profile. Syntax conversion alone is not runtime qualification.

**Hardware-in-loop (HIL) qualification** — qualification performed against the actual runtime target when behavior cannot be established from mocks or hosted CI alone.

**Compatibility profile** — a versioned Foundry record that binds source-rendering and runtime semantics to exact upstream identities and target-profile assumptions. For the native TrueNAS path this should eventually include the exact `truenas/apps` revision/iX library identity, the exact release-specific `truenas/middleware` ref/commit, IR version, target adapter identity, and qualification evidence.

## Pipeline model

```text
TrueNAS App Store-compatible source application
        |
        | source rendering
        | pinned truenas/apps + iX library
        v
normalized deployment IR
(currently normalized Compose JSON)
        |
        | target lowering
        v
target-specific deployment artifact
        |
        | runtime realization
        v
runtime target / target profile
        |
        | execute + observe
        v
qualification evidence
```

## Materialization classes

### Native materialization

The source ecosystem and runtime target share the same native application model.

Current target:
- TrueNAS SCALE Apps.

The native path should be compatibility-anchored to both the source/application implementation in `truenas/apps` and the runtime/lifecycle implementation in `truenas/middleware`.

### Compose-family materialization

The normalized Compose IR is close to the runtime's own deployment model, so lowering should normally be small but still explicit.

Possible targets:
- Docker Compose;
- Podman Compose.

Docker Compose is already used for normalization and focused smoke evidence, but general source-application runtime qualification is not yet claimed.

### OCI service materialization

The runtime is still OCI/container based but uses service/unit semantics rather than Compose as the authoritative deployment model.

Possible future targets:
- Podman Quadlet + systemd;
- nerdctl/containerd profiles where a concrete consumer justifies them.

These require explicit lowering for restart policy, networking, storage, health/lifecycle, dependencies, secrets, and service ownership.

### Orchestrator materialization

The runtime target has a materially different reconciliation/deployment model and therefore requires a richer semantic adapter.

Possible future targets:
- Kubernetes;
- k3s;
- Nomad.

These are not simple syntax converters. Storage, helper services, init/permission behavior, probes, service discovery, ingress/ports, security contexts, devices/GPUs, secrets, and restart/reconciliation semantics must be mapped deliberately.

## Upstream TrueNAS compatibility anchors

The Foundry should avoid maintaining a private reinterpretation of “TrueNAS-compatible” when the relevant upstream implementations are public.

Use these public source families as compatibility anchors:

- `truenas/apps` — source application/catalog metadata, questions/schema, templates, shared iX library behavior, known-good catalog controls, and upstream rendering/CI machinery.
- `truenas/middleware` — native TrueNAS Apps runtime implementation, including Apps CRUD, custom-App handling, Compose plumbing, ix-volume/storage behavior, lifecycle/state handling, and other middleware semantics relevant to runtime realization.

For a native TrueNAS target profile, prefer release-specific refs and immutable commits over floating `master`. Example: the public `truenas/middleware` branch `release/25.04.1` was observed at commit `74ab5a2d373be4097dece257d00e1086376333ba` during this design pass. That commit is an upstream source anchor, not proof that every deployed 25.04.x system runs that exact build; HIL must record the actual target host version and reconcile it against the compatibility profile.

Both `truenas/apps` and `truenas/middleware` expose public LGPL-3.0 source trees. License-sensitive reuse must still honor file-level notices and any separately licensed portions; compatibility testing can usually pin, execute, and compare upstream behavior without copying implementation into Foundry.

## Current status

- Source ecosystem: TrueNAS App Store-compatible packages.
- Materialization controls: `community/forgejo-runner` and `community/ntfy`.
- Source materializer: pinned public `truenas/apps` renderer plus Docker Compose normalization.
- Current practical IR: normalized Compose JSON.
- Native runtime target: TrueNAS SCALE Apps; live HIL qualification is still pending for the GARM runner path.
- Docker Compose: normalization and focused runtime smoke are already used, but general source-application target lowering/runtime qualification remains a future feature.
- Podman Compose, Quadlet/systemd, Kubernetes, k3s, Nomad, and nerdctl/containerd: possible future features only.
- Upstream compatibility profiles spanning `truenas/apps` + `truenas/middleware`: planned future capability.

## Usage rules

Do not call a source application or test fixture a “materialization target.” Call it a **source application** or **materialization control**.

Use **source rendering** for source application → normalized IR.

Use **target lowering** for normalized IR → target-specific deployment artifact.

Use **runtime realization** for actually creating/starting the workload in a runtime target.

Use **materialization** as the umbrella term only when the finer distinction is not material to the claim.

Do not call successful rendering or lowering a runtime qualification. Execution and observation on a target profile establish runtime qualification.

When discussing portability, name both the runtime target and target profile when the version/platform affects the claim.

When a lowering adapter cannot preserve a source semantic—storage, host paths, devices, certificates, networking, privileges, GPU allocation, helper containers, or TrueNAS-specific behavior—it must report the gap explicitly and fail closed where safety or correctness would otherwise be ambiguous.
