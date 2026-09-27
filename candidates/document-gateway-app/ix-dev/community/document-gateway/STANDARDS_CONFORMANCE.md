# Document Gateway standards and conformance plan

Status: candidate qualification contract.

## Normative protocol baseline

The gateway's page-oriented printer projection targets open IETF/PWG standards
first. Platform marketing/certification claims are separate.

### Internet Printing Protocol

Normative/reference standards:

- RFC 8010 — IPP/1.1 Encoding and Transport;
- RFC 8011 — IPP/1.1 Model and Semantics;
- PWG 5100.12 — IPP/2.x;
- PWG 5100.14-2020 — IPP Everywhere v1.1;
- PWG 5100.20-2020 — IPP Everywhere v1.1 Printer Self-Certification Manual;
- PWG 5101.1 — PWG Media Standardized Names;
- PWG 5102.4 — PWG Raster;
- PWG 5100.15 — IPP FaxOut Service, for future FaxOut projection;
- PWG 5100.17 — IPP Scan Service, if/when the scanner input is exposed as an
  IPP Scan service rather than only file/SMB intake;
- PWG 5100.18 — IPP Shared Infrastructure Extensions, relevant to the gateway's
  intermediary/managed-print role.

IPP Everywhere v2.0 is under active standards development in 2026. It is useful
as a forward-looking observation target, but v1.1 remains the published
self-certification baseline until PWG replaces it.

### Discovery

- RFC 6762 — Multicast DNS;
- RFC 6763 — DNS-Based Service Discovery;
- IPP Everywhere DNS-SD requirements;
- AirPrint-compatible DNS-SD projection as a platform interoperability target.

## Official PWG conformance tools

PWG publishes the IPP Everywhere v1.1 Printer Self-Certification Tools and
defines three primary test groups:

1. DNS-SD discovery tests;
2. IPP protocol/attribute tests;
3. document-format/printing tests.

The current published v1.1 Update 4 tools are the authoritative submission
suite. Their source is Apache-2.0 in `istopwg/ippeveselfcert`; the
`v1.1-updates` branch is pinned for continuous CI.

Continuous CI MAY build the official source and run it as engineering evidence.
A formal PWG self-certification submission MUST be rerun using the exact
PWG-posted binary package and the PWG-prescribed isolated/quiescent network
procedure. Passing CI is never represented as certification.

Pinned continuous-test source:

```
repository: https://github.com/istopwg/ippeveselfcert
ref: af2b5887854e86888b8bed25bf2c0dd3c5c25614
line: v1.1 Update 4
```

## CUPS ipptool gate

OpenPrinting CUPS ships `ipptool` plus protocol test files including IPP
1.1/2.x, Get-Printer-Attributes, Validate-Job, Print-Job, and IPP Everywhere
tests.

This is the fast continuous gate:

- HTTP/IPP framing;
- required IPP operations;
- required/consistent attributes;
- print job submission;
- selected document formats.

It runs before the full PWG suite so protocol regressions fail quickly.

## TrueNAS catalog gate

TrueNAS catalog readiness is a separate packaging/contribution gate:

- render the app with the current TrueNAS Apps CI/materialization tooling;
- exercise every test-values path;
- use the current non-v1 TrueNAS app library at submission time;
- pass official repository validation;
- satisfy current contribution metadata, icon/screenshot, versioning, security,
  storage, portal, and test-path rules.

The preferred TrueNAS app and portable deployments MUST expose the same runtime
API, ABI and IPP behavior. Catalog-specific questions/materialization are not
allowed to create a second functional implementation.

## Apple, Android/Mopria and Windows

### Apple AirPrint

Use open IPP/DNS-SD conformance plus Apple-documented discovery/TXT semantics.
Final macOS/iOS behavior remains HIL because the client controls discovery,
option presentation and the management-link affordance.

Do not claim Apple certification unless such a program is actually completed.

### Android / Mopria

IPP Everywhere conformance is a strong protocol foundation for the Android
Default Print Service/Mopria path. Mopria certification is a distinct formal
program and must not be claimed from PWG test results.

Android discovery/install/print remains a real-device HIL gate.

### Windows

Windows Ready Print / Microsoft IPP Class Driver compatibility is layered on
the standards baseline. Validate:

- directed IPP installation;
- Add Device discovery;
- Windows Protected Print Mode when applicable;
- printer capabilities and management-link behavior.

Where Microsoft's strongest compatibility claims depend on Mopria
certification, keep the claim as interoperability-tested rather than certified.

## Deployment-independent qualification

Protocol conformance targets a running gateway endpoint, not a packaging
format.

Every supported materializer must run the same qualification contract:

```
materialize
  -> start
  -> health/readiness
  -> management API contract
  -> IPPTool protocol tests
  -> PWG self-cert engineering suite
  -> print/document smoke
  -> shutdown
  -> idempotent restart
```

Target materializers:

- TrueNAS App (reference/preferred);
- Docker Compose;
- Podman Compose;
- Podman Quadlet/systemd;
- plain OCI container deployment where the operator supplies equivalent
  networking/storage/secrets.

## CI evidence classes

### Tier 0 — deterministic source

- schemas;
- renderer/sender ABI;
- TrueNAS render;
- Compose normalization;
- security invariants;
- UI/API contract.

### Tier 1 — runtime smoke

- queue creation;
- API idempotency;
- PDF print;
- scan/fax import;
- null sender behavior;
- restart/reconciliation.

### Tier 2 — protocol conformance

- CUPS `ipptool` suites;
- PWG IPP Everywhere source-built engineering run;
- DNS-SD service/TXT checks in a suitable hosted network namespace.

### Tier 3 — cross-materializer

Run Tier 0-2 against each supported deployment model on public GHA where the
runner can faithfully emulate the model.

### Tier 4 — hardware/client HIL

- TrueNAS host;
- Brother printer/scanner;
- FRITZ!Box;
- Windows;
- macOS;
- Linux desktop;
- Android;
- iOS/iPadOS;
- LAN multicast/VLAN topology.

### Tier 5 — formal external certification/submission

Only when useful:

- official PWG self-certification using PWG-posted binaries;
- TrueNAS official catalog PR/review;
- Mopria or other vendor certification programs if their value earns their
  cost.

## Result vocabulary

Use precise states:

- `PASS` — the named test actually passed;
- `FAIL` — tested and failed;
- `BLOCKED` — required environment/capability unavailable;
- `UNSUPPORTED` — intentionally outside the claimed target;
- `HIL_REQUIRED` — cannot be established faithfully in hosted CI;
- `NOT_RUN` — no evidence.

Never convert `BLOCKED` or `HIL_REQUIRED` into PASS.
