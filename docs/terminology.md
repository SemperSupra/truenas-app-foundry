# TrueNAS App Foundry terminology

This document is the canonical vocabulary for the Foundry and the related GARM/TrueNAS repositories. Use these terms consistently in issues, pull requests, code comments, architecture documents, and qualification evidence.

## Core terms

**Source application** — a TrueNAS App Store-compatible application/package used as the canonical input to the Foundry. It includes the application metadata, schema/defaults, templates, and iX library behavior needed to render the application.

**Materialization control** — a known-good source application used to validate the materializer itself. A control is test input, not a runtime target. The initial controls are `community/forgejo-runner` and `community/ntfy`.

**Materializer** — the logic/toolchain that resolves a source application and selected values into a concrete deployment model. For the current TrueNAS source ecosystem this includes the pinned `truenas/apps` revision, its iX library, upstream rendering logic, and normalization steps.

**Intermediate representation (IR)** — the normalized deployment model produced after source rendering and before target-specific adaptation. The current practical IR is normalized Docker Compose JSON. Treat this as an implementation-stage IR, not a promise that every future target will preserve every Compose semantic exactly.

**Target adapter** — logic that converts the IR into the representation and semantics required by a materialization target. A target adapter must identify unsupported or lossy mappings rather than silently discard source semantics.

**Materialization target** — a runtime family on which a source application may ultimately execute after rendering and any required target adaptation. Examples include TrueNAS SCALE Apps, Docker Compose, Podman, or Kubernetes. Source applications such as `ntfy` are not materialization targets.

**Target profile** — a specific, qualified variant of a materialization target, including version/platform constraints that materially affect behavior. Examples: `truenas-scale/25.04/linux-amd64`, `docker-compose/v2/linux-amd64`, or a future `kubernetes/<version>` profile.

**Materialization** — the end-to-end process that takes a source application through rendering/normalization and target adaptation to produce a target-specific deployment artifact or workload definition. Use **render** for source-application → IR and **adapt/materialize** for IR → target-specific output.

**Qualification** — evidence that an exact source/application/toolchain/adapter identity behaves correctly on an exact target profile. Syntax conversion alone is not runtime qualification.

**Hardware-in-loop (HIL) qualification** — qualification performed against the actual target environment when behavior cannot be established from mocks or hosted CI alone.

## Pipeline model

```text
TrueNAS App Store-compatible source application
        |
        | render with pinned iX-compatible materializer
        v
normalized deployment IR (currently Compose JSON)
        |
        | target adapter
        v
materialization target / target profile
        |
        | execute + observe
        v
qualification evidence
```

## Current status

- Source ecosystem: TrueNAS App Store-compatible packages.
- Materialization controls: `community/forgejo-runner` and `community/ntfy`.
- Materializer: pinned public `truenas/apps` renderer plus Docker Compose normalization.
- Current practical IR: normalized Compose JSON.
- Native materialization target: TrueNAS SCALE Apps; live HIL qualification is still pending for the GARM runner path.
- Docker Compose is already used to normalize and smoke-test portions of the system, but general source-application runtime qualification on Docker Compose is a future feature until an explicit target adapter/qualification suite exists.

## Usage rules

Do not call a source application or test fixture a “materialization target.” Call it a **source application** or **materialization control**.

Do not call successful rendering a runtime qualification. Rendering can establish materializer evidence; execution on a target profile establishes runtime qualification.

When discussing portability, name both the materialization target and target profile when the version/platform affects the claim.

When an adapter cannot preserve a source semantic—storage, host paths, devices, certificates, networking, privileges, GPU allocation, helper containers, or TrueNAS-specific behavior—it must report the gap explicitly and fail closed where safety or correctness would otherwise be ambiguous.
