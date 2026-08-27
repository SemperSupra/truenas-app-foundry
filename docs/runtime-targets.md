# Runtime targets and future materialization roadmap

This document records the Foundry's runtime-target model. Terminology is defined canonically in `docs/terminology.md`.

The Foundry accepts TrueNAS App Store-compatible source applications, performs source rendering into a normalized deployment IR, lowers that IR into a target-specific deployment artifact, and then qualifies runtime realization on an exact target profile.

## Current target status

| Materialization class | Runtime target | Status | Current claim |
| --- | --- | --- | --- |
| Native | TrueNAS SCALE Apps | Active MVP target | Source rendering and provider-side deployment generation exist; live capacity-one HIL qualification is pending. |
| Compose-family | Docker Compose | Partial mechanics | Used for normalized IR and focused container smoke evidence. General source-application runtime qualification is not yet implemented. |
| Compose-family | Podman Compose | Future | No target adapter or qualification claim. |
| OCI service | Podman Quadlet/systemd | Future | No target adapter or qualification claim. |
| OCI service | nerdctl/containerd | Possible future | Pursue only if a concrete consumer justifies the adapter/qualification cost. |
| Orchestrator | Kubernetes | Future | Requires substantial semantic lowering; no support claim. |
| Orchestrator | k3s | Future | Likely reuses Kubernetes lowering with a concrete homelab-oriented target profile; no support claim. |
| Orchestrator | Nomad | Possible future | No target adapter or qualification claim. |

## Native TrueNAS target

The native target has the smallest semantic distance from the source ecosystem, but it still has two distinct upstream compatibility surfaces:

1. `truenas/apps` defines the source-side application/catalog model and rendering behavior.
2. `truenas/middleware` implements the runtime-side Apps APIs and lifecycle semantics on TrueNAS SCALE.

Native compatibility should therefore be proven with a versioned compatibility profile rather than inferred from a marketing/version string alone.

A future native profile should bind at least:

```yaml
source_profile:
  repository: truenas/apps
  commit: <exact commit>
  ix_library_version: <exact version>
  ix_library_hash: <exact hash>

runtime_target_profile:
  runtime: truenas-scale
  version: <reported target version>
  middleware_ref: <release ref>
  middleware_commit: <exact commit>
  platform: linux-amd64

ir:
  schema: normalized-compose
  version: <foundry IR version>

adapter:
  identity: <native lowering/realization adapter version>

qualification:
  evidence: <exact evidence identities>
  semantic_gaps: []
```

During the terminology/compatibility review, the public `truenas/middleware` branch `release/25.04.1` was observed at `74ab5a2d373be4097dece257d00e1086376333ba`. Treat that as an upstream reference point, not as proof about a specific deployed host. The HIL preflight must record the actual system version and reconcile it deliberately.

## Target-lowering rules

Every non-native target adapter must be explicit about semantic preservation. At minimum it must assess:

- persistent storage and TrueNAS ix-volume semantics;
- host paths and bind mounts;
- devices and GPU allocation;
- certificates and secret material;
- networking, published ports, ingress/service discovery;
- privileged mode, capabilities, user/group and security options;
- health checks and restart/reconciliation semantics;
- helper/init/permissions containers;
- dependencies/order of startup;
- target-specific APIs or middleware assumptions.

A target adapter must not silently discard unsupported semantics. Unsupported mappings should produce a compatibility finding and fail closed where the result would otherwise be unsafe or materially incorrect.

## Suggested future order

Future work should remain demand-driven, but the likely cost/benefit order is:

1. **Docker Compose target qualification** — closest to the current normalized IR and useful as an off-TrueNAS reference runtime.
2. **Podman Compose or Quadlet/systemd** — useful for rootless/server deployments; choose based on an actual consumer rather than implementing both preemptively.
3. **k3s/Kubernetes** — high-value if a concrete cluster consumer emerges, but requires a real semantic adapter rather than syntax conversion.
4. **Nomad or nerdctl/containerd** — only when a concrete deployment need justifies the maintenance burden.

## Non-claims

The presence of a runtime in this roadmap does not mean it is supported.

Docker Compose normalization does not by itself establish Docker Compose runtime qualification.

A successful target lowering does not by itself establish runtime realization or behavior.

TrueNAS source compatibility does not by itself prove a specific target host matches the selected compatibility profile; HIL/target evidence remains authoritative for that claim.

Tracking issues:
- #5 — upstream TrueNAS compatibility profiles.
- #6 — multi-runtime target lowering adapters.
