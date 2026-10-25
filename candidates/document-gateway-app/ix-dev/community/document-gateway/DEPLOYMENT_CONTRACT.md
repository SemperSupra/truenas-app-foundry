# Document Gateway deployment contract

Status: candidate multi-materializer contract.

## Product/runtime boundary

Document Gateway is one product with multiple deployment materializers.

Preferred/reference deployment:

- TrueNAS App, maintained so it can be promoted toward the official TrueNAS
  Apps catalog.

Supported portable deployment targets:

- Docker Compose;
- Podman Compose;
- Podman Quadlet/systemd;
- plain OCI containers for advanced operators.

A deployment model MUST NOT fork the control API, job model, plugin ABIs,
document semantics, or qualification criteria.

## Hard invariant: stateless disposable runtimes

Every runtime container/process is replaceable compute only.

A container restart, recreation, image upgrade, host reboot, or complete
replacement of the runtime filesystem MUST NOT lose or redefine persistent
configuration or user data.

All durable state lives outside the runtime image/container on explicit
persistent stores or external secret/config providers.

Durable classes include:

- desired gateway configuration and generations;
- destination/queue definitions;
- output profiles/presets and routing policy;
- user documents and derived artifacts;
- print/scan/fax/email outboxes and queued jobs;
- delivery/retry state that must survive restart;
- event/provenance journals according to retention policy;
- CUPS queue state/PPDs needed by qualified legacy paths;
- stable gateway/printer identity and TLS key material;
- plugin configuration and qualified plugin-selection state;
- persistent normalization/import ledgers;
- credentials/secrets, via an external secret/config mechanism rather than the
  writable container filesystem.

The runtime filesystem MAY contain only:

- immutable application code and packaged dependencies;
- generated caches/scratch files that are safe to discard;
- process-local temporary files;
- derived runtime configuration that is deterministically regenerated from
  external durable/bootstrap state on every start.

If loss of a file inside a container changes durable behavior after recreation,
that file is in the wrong place.

### Persistent logical roots

The current candidate uses three explicit durable roots:

- `/config` — CUPS persistent configuration, PPD state, stable TLS/identity
  material, and other deployment-owned persistent service configuration;
- `/spool` — gateway desired/reconciliation state and durable work queues or
  ledgers that must survive runtime replacement;
- `/data` — user documents, inboxes/outboxes, artifacts, machine-readable
  status/event/provenance data, and retained delivery state.

Future project-owned images MAY refine these into narrower mounts, but may not
move durable state back into the image/container layer.

External read-only inputs such as a scanner/fax share remain external sources
and are not copied into runtime-local persistence.

### Runtime replacement qualification

Every materializer MUST pass a disposable-runtime test:

1. materialize external persistent stores;
2. start fresh runtime instances;
3. create representative persistent configuration and user/job state;
4. verify normal operation;
5. destroy the runtime instances **without deleting persistent stores**;
6. create new instances from the same or upgraded qualified image;
7. verify desired state, identities, documents, outboxes, ledgers and
   reconciliation recover correctly;
8. verify no hidden container-local state was required;
9. separately test explicit backup/restore into fresh persistent stores.

A materializer cannot be called supported if it only passes restart-in-place.

## Stable runtime contract

All materializers expose the same logical services:

- `cups` — IPP/CUPS projection and physical/virtual print queues;
- `control` — Document Gateway WebUI/API;
- `normalizer` — networkless document intake/normalization;
- `fax-sender` — currently the networkless null sender;
- future renderer/sender workers under their versioned plugin ABIs.

Stable interfaces:

- `document-gateway.control/v1`;
- `document-gateway.renderer/v1`;
- `document-gateway.fax-sender/v1`;
- durable document/job/event storage model;
- IPP/DNS-SD projection contract.

## Materializer-specific responsibilities

### TrueNAS App

Owns:

- questions/install UI;
- ixVolume/host-path/CIFS mapping;
- ports/bind addresses;
- USB/device mapping;
- external LAN/macvlan selection;
- TrueNAS Web Portal metadata;
- resource limits;
- official catalog metadata.

It does not own a separate runtime behavior.

### Docker Compose

Owns:

- Compose-compatible volumes/bind mounts;
- environment/secrets injection;
- bridge/host/macvlan networking;
- published ports;
- restart policy and resource limits.

### Podman Compose

Uses the same logical Compose model where supported. Qualification must detect
provider differences instead of assuming Docker behavior.

### Podman Quadlet

Provides a native systemd-managed Podman projection for users who prefer
declarative host services without a Compose provider.

Expected properties:

- deterministic container dependencies;
- named volumes or operator-selected host paths;
- restart via systemd;
- explicit network mode;
- secrets via Podman/systemd facilities rather than committed files.

### Plain OCI

Document the minimum container, mount, network, capability, secret and health
contract so advanced runtimes can reproduce the service graph.

## One runtime identity

The end-state packaging direction is a versioned Document Gateway image set in
GHCR with exact OCI digests.

This replaces the prototype's current practice of embedding project scripts
inside the TrueNAS template and reusing one upstream CUPS image for every
service.

Desired image split:

- privileged-needs-minimized CUPS image/service;
- non-root gateway control/normalizer/worker image;
- optional renderer images only when a converter dependency justifies
  isolation.

Benefits:

- identical code across TrueNAS/Docker/Podman;
- smaller TrueNAS templates;
- non-root workers;
- easier SBOM/provenance/signing;
- digest-pinned reproducibility;
- independent plugin qualification.

## Transitional materialization

Until the project-owned images exist, portable CI bundles MAY be mechanically
derived from the same TrueNAS candidate template/runtime blocks. They are
qualification artifacts, not the final operator UX.

No runtime script may be manually copied into an alternate deployment tree
without a deterministic equivalence check.

## Capability model

Materializers declare what the environment can faithfully provide:

- persistent storage;
- published IPP;
- host mDNS;
- dedicated LAN identity/macvlan;
- USB;
- CIFS/remote fax intake;
- systemd lifecycle;
- secret store;
- resource limits.

Unsupported features fail closed or are clearly omitted. A portable
materializer does not silently emulate a network/discovery mode it cannot
faithfully provide.

## Configuration ownership

Bootstrap/deployment settings:

- storage paths/volumes;
- bind/published ports;
- network mode;
- device passthrough;
- bootstrap/admin secret source;
- resource constraints.

Dynamic runtime state:

- destinations;
- queues;
- output profiles/presets;
- jobs;
- routing;
- outboxes;
- plugin runtime policy.

Dynamic state always belongs to the common control API, regardless of
materializer.

## Portable operator UX

Each portable package should eventually include:

- `.env.example` containing no secrets;
- Compose or Quadlet files;
- documented secret injection;
- health/readiness commands;
- backup/restore paths;
- upgrade/rollback procedure;
- discovery-network examples;
- rootless limitations where applicable;
- machine-readable deployment manifest.

## Cross-materializer equivalence gate

For every supported materializer, compare:

- service inventory;
- exact image digests;
- command/entrypoint identity;
- mounted logical paths and access modes;
- Linux capabilities/privilege;
- network exposure;
- API version;
- plugin ABI versions;
- persisted state paths;
- advertised IPP attributes;
- conformance test results.

Materializer-specific differences must be declared and justified.

## Promotion rule

A deployment option is only called **supported** after its public-safe hosted
qualification passes and any environment-specific HIL gate is identified.

Before that it is a **candidate materializer**.
