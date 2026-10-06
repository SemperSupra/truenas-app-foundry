# TrueNAS catalog alignment

Status: candidate audit against the current TrueNAS Apps contribution guidance.
This is a promotion gate, not a claim that the Foundry candidate is ready for
submission to the official catalog.

## Principle

Keep two qualification lanes separate:

1. **Foundry/runtime qualification** — prove the architecture, rendering,
   runtime behavior, security boundaries and HIL on the user's TrueNAS system.
2. **Official-catalog readiness** — rebase the proven app onto current TrueNAS
   contribution/library conventions and satisfy current metadata/review rules.

Do not weaken the first lane merely to look catalog-shaped, and do not call the
candidate official-catalog-ready merely because it renders on a pinned library.

## Current TrueNAS contribution conventions to inherit

The current TrueNAS Apps contributor guide emphasizes:

- new contributions target the `community` train;
- use the latest non-v1 rendering library;
- `questions.yaml` uses familiar app/network/storage/resources grouping;
- sensible defaults and clear descriptions;
- `show_if` hides irrelevant settings;
- private fields are UI masking, not a secret store;
- web applications expose TrueNAS Web Portal links;
- run non-root where the application permits it;
- minimize Linux capabilities;
- define health checks;
- prefer GHCR over Docker Hub for images;
- use `ix_volume` as the easy default storage where appropriate;
- test storage paths under `/opt/tests/**`;
- test conditional/enum paths, not only the default;
- semver the catalog package and increment it for changes;
- app icons/screenshots are hosted on the TrueNAS CDN after review;
- document special network/device/storage requirements.

## What already aligns

- community train;
- task-oriented labels/descriptions;
- standard Document Gateway / Network / Storage / Resources group names;
- `show_if` for conditional networking/storage fields;
- private password fields;
- `ix_volume` easy defaults with host-path option for shared documents;
- health checks for network-facing services;
- no privileged containers;
- capabilities dropped and only selectively restored for CUPS;
- multiple render fixtures;
- Web Portal entries for the gateway and CUPS;
- explicit hardware/network/HIL non-claims.

## Candidate gaps before official submission

### App image and version identity

Current state:

- application code is embedded in the TrueNAS template;
- all services reuse `chuckcharlie/cups-avahi-airprint:2.1.3`;
- `app_version` therefore names the upstream CUPS image rather than a
  versioned Document Gateway product;
- Docker Hub is used.

Promotion direction:

- build a versioned Document Gateway image (or narrowly separated images) in
  GHCR;
- pin exact OCI identities in qualification;
- make `app_version` represent the Document Gateway release;
- retain upstream CUPS/OpenPrinting provenance separately.

### Privilege separation

Current state:

- the CUPS service requires root initialization in the selected upstream image;
- normalizer, fax-sender and control service currently reuse that image and
  therefore also run as root even though their functions do not inherently
  require it.

Promotion direction:

- isolate CUPS into the smallest service that needs elevated startup behavior;
- run normalizer, control API and sender/renderer workers as non-root;
- preserve networkless workers where possible;
- document any remaining root/capability exception.

### Library/materializer

Current Foundry qualification deliberately pins an older TrueNAS Apps source
and library for reproducibility.

Official-catalog readiness requires a fresh rebase against the then-current
TrueNAS Apps master and latest non-v1 library, followed by full render/runtime
requalification.

### Maintainer metadata

The current candidate lists SemperSupra. Current TrueNAS contribution guidance
uses TrueNAS maintainer metadata for catalog submissions.

Treat this as submission-time metadata and do not rewrite the internal Foundry
authority model prematurely.

### Icon and screenshots

Current candidate uses the OpenPrinting CUPS icon and no screenshots.

This is not the desired final identity:

- Document Gateway should have its own truthful project identity;
- do not imply that OpenPrinting/CUPS is the entire product;
- prepare reviewed screenshots only after the WebUI stabilizes;
- official submission should use TrueNAS CDN URLs supplied through review.

### Test paths

Current public qualification uses `/tmp/document-gateway-ci/**`.
Official catalog fixtures should be converted to the current TrueNAS
`/opt/tests/**` convention and rerun before submission.

### Package version

The candidate remains `0.1.0` while Foundry work is moving quickly.
Before catalog submission, establish the catalog package/version bump workflow
and stop treating one candidate version as an indefinitely mutable release.

## TrueNAS form versus Document Gateway WebUI

The TrueNAS form owns deployment-time settings:

- storage and host mounts;
- ports/bind addresses;
- network/discovery mode;
- hardware/USB passthrough;
- bootstrap credentials;
- resource limits;
- any option that changes container topology or mounts.

The Document Gateway WebUI/API owns runtime operational state:

- destinations/queues;
- jobs;
- route presets;
- output profiles;
- fax/email outboxes;
- plugin configuration that does not require rematerialization;
- status/events/provenance;
- runtime policy.

Avoid maintaining the same setting independently in both places.

## Portals

Expose two clearly different TrueNAS portals:

- **Document Gateway** — normal management surface;
- **Advanced CUPS** — diagnostic/compatibility surface.

Do not make users infer that the CUPS UI is the gateway's primary source of
truth.

## Submission readiness gate

Before an official TrueNAS Apps PR:

- [ ] current TrueNAS Apps master/library rebase passes;
- [ ] current contributor validation passes;
- [ ] own versioned GHCR image(s) are qualified and digest-bound;
- [ ] non-root split is complete except documented CUPS exception;
- [ ] catalog app/version identity is correct;
- [ ] official maintainer metadata is correct;
- [ ] original project icon exists and CDN path is ready;
- [ ] reviewed WebUI screenshots exist and CDN paths are ready;
- [ ] test mounts use current TrueNAS conventions;
- [ ] every conditional/enum deployment path is tested;
- [ ] TrueNAS Web Portal opens the normal gateway UI;
- [ ] local TrueNAS HIL passes;
- [ ] Brother print/scan HIL passes;
- [ ] LAN discovery behavior is qualified for every advertised mode;
- [ ] security/UI/UX/DX surface gate passes;
- [ ] release notes clearly identify remaining nonclaims.
