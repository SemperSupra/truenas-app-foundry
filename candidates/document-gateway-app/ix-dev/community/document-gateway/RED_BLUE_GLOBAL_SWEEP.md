# Document Gateway red/blue team and multilingual concept sweep

Status: candidate architecture guidance. This document records findings and
qualification obligations; it does not claim all listed capabilities are
implemented.

## System boundary

The gateway should be treated as a small document-routing fabric:

```
input -> immutable artifact -> routed job -> per-leg transform -> output channel
                                      |             |
                                      +-> state/events/provenance
```

CUPS/IPP is the page-oriented print adapter, not the domain model. One user
intent can fan out into independently tracked route legs such as:

- physical print;
- archive/save;
- email copy;
- fax outbox;
- format/export derivative.

A failure or retry on one leg must not duplicate a leg that already succeeded.

## Blue-team target architecture

### Stable resources

- **artifact**: immutable content plus digest, MIME type, provenance, and
  transformation lineage;
- **job**: client-selected stable id plus submitted intent;
- **route leg**: one output of one job;
- **destination**: stable endpoint configuration;
- **output profile**: rendering/media/transformation policy;
- **plugin**: versioned actuator/renderer interface;
- **attempt**: one delivery attempt for one leg;
- **event**: append-only lifecycle evidence.

Desired state and observed state remain separate. Frontends never call CUPS or
plugins directly; they use the common control API.

### Output channels

Near-term:

- physical IPP printer;
- archive/file;
- email;
- fax outbox;
- PDF/image/export.

Later when a use case earns them:

- SFTP/FTP;
- object storage;
- cloud document store;
- webhook;
- e-reader/device delivery;
- secure print/release station.

Network-capable channels are separate trust boundaries and are disabled until
their egress and credential policies are qualified.

## Print + email copy

Email is a first-class route leg, not a CUPS notification side effect.

Example user intent:

```json
{
  "job_id": "01K...",
  "routes": [
    {"id": "paper", "destination": "brother-office", "profile": "office-a4"},
    {"id": "archive", "destination": "documents", "profile": "archive-pdfa"},
    {"id": "mail", "destination": "email-me", "profile": "email-pdf"}
  ]
}
```

Each leg gets independent `queued/rendering/delivering/succeeded/failed/deferred`
state and its own attempt history.

An email sender plugin should progress through:

1. `null` sender: validates and observes, never transmits;
2. local SMTP test sink;
3. SMTP/TLS backend;
4. optional provider backends only when justified.

Email controls include stable Message-ID/delivery identity, header-injection
prevention, TLS verification, rate limits, attachment/message-size limits,
recipient/domain policy, loop prevention, secrets excluded from logs, and
idempotent retry.

## Page/media and physical-output capability

Do not hard-code an A4/Letter-only worldview. Query and project observed IPP
capabilities such as:

- `media-supported`;
- `media-ready`;
- `media-col-database`;
- printable margins;
- `sides-supported`;
- `print-color-mode-supported`;
- `printer-resolution-supported`;
- input trays/media types;
- output bins;
- finishings where present.

The UI should prioritize **loaded/ready** media and progressively disclose other
supported media.

Profiles should support where the destination allows:

- ISO A/B sizes;
- Letter/Legal/Ledger and other North American media;
- JIS and other standardized regional media;
- envelopes, cards, photo stock;
- labels and custom media;
- roll/receipt/large-format media;
- portrait/landscape;
- fit, fill/crop, preserve-size;
- explicit margins;
- simplex/duplex/binding edge;
- copies/collation;
- page ranges;
- N-up;
- booklet/imposition;
- reverse order;
- resolution/quality;
- color/grayscale/monochrome;
- finishing operations.

The canonical machine representation should use standard PWG/IPP identifiers
where possible. Human UIs may display localized names and units without changing
the identifiers.

## Screen/e-reader output profiles

Page geometry and reading intent are separate concepts.

Possible profiles:

- phone/small screen: responsive/reflowable, single-column bias;
- tablet;
- desktop;
- e-reader: EPUB/reflow plus navigation metadata;
- large display/signage;
- large-print accessibility;
- fixed-layout/high-fidelity page output.

A source can simultaneously retain a page-faithful PDF and a reflowable
HTML/EPUB derivative.

## Artifact/format families

### High-confidence page/image

- PDF;
- PDF/A;
- PNG/JPEG page images;
- multipage TIFF;
- thumbnails/previews.

### Semantic/extracted

- plain text;
- searchable PDF;
- hOCR;
- ALTO XML;
- HTML;
- Markdown;
- EPUB;
- JSON/JSONL metadata and structure.

Markdown/HTML/EPUB produced only from a print stream/PDF are reconstructed
derivatives: printing can lose headings, links, logical reading order, table
semantics, footnotes and source styles. The API and UI must expose provenance
and confidence rather than presenting them as source-equivalent.

### Specialized profiles to consider only with a real use case

- tagged/accessible PDF;
- PDF/X for prepress;
- PDF/R or equivalent raster-document profile;
- digitally signed/encrypted deliverables.

## Typography, shaping and font substitution

Font failure is a preflight state, not an invisible rendering detail.

For each artifact/profile:

- inventory embedded/referenced fonts;
- verify glyph coverage for used Unicode code points;
- preserve embedded fonts when permitted;
- use mature shaping engines for Arabic, Indic, Southeast Asian, CJK and other
  complex scripts;
- define missing-font behavior: `fail`, `warn-and-substitute`, or
  `substitute`;
- record substitutions and missing-glyph findings in provenance;
- provide script-aware fallback chains;
- never silently accept missing-glyph/tofu substitution for archival, legal,
  multilingual or high-fidelity profiles.

Color-management/ICC profiles should be a separate rendering concern rather
than being hidden inside destination-specific code.

## Useful transform plugins

Opt-in transforms that fit the architecture:

- OCR with explicit language sets and confidence;
- orientation detection/rotation;
- deskew/dewarp/crop;
- blank-page removal;
- split/merge/reorder;
- barcode/QR separation;
- Bates/sequence numbering;
- watermark/stamp;
- thumbnail/preview;
- compression/downsampling;
- metadata extraction/indexing;
- redaction with destructive verification;
- signature/hash verification.

OCR/model classification is observation/metadata by default. It must not
silently authorize an external delivery destination.

## Human UI/UX

### TrueNAS installation/edit form

This is deployment/bootstrap UI, not the operational console.

Follow TrueNAS catalog conventions:

- app-specific configuration group;
- Network Configuration;
- Storage Configuration;
- Resources Configuration;
- sensible defaults;
- clear field descriptions;
- conditional fields hidden with `show_if`;
- private fields marked private, while remembering this is UI masking only;
- Web Portal entries when applicable.

Queue creation, routine destination editing, jobs, route rules, outboxes,
profiles, events, and plugin state belong in the Document Gateway WebUI/API.

### Document Gateway WebUI

Purpose-oriented navigation:

- Overview;
- Destinations;
- Jobs;
- Presets / Output Profiles;
- Inputs;
- Email/Fax Outboxes;
- Plugins;
- Events / Provenance;
- Settings;
- Advanced diagnostics.

Human affordances:

- status in text, never color alone;
- loaded media shown before merely supported media;
- source/destination preview before external delivery;
- clear retry vs resubmit semantics;
- explicit destructive confirmation;
- external links/handoffs identifiable;
- copy actions for API endpoints, ids and checksums where useful;
- progressive disclosure for advanced CUPS, custom drivers and networking;
- empty/error/offline/reconciling states designed explicitly;
- no assumption that "printer offline" means the gateway itself is unhealthy.

### Printer dialog / native device surface

Advertise:

- `printer-info`;
- `printer-location`;
- `printer-more-info` pointing to the corresponding gateway WebUI resource;
- `printer-icons` where practical;
- accurate media/duplex/color/resolution/finishing capabilities.

With DNS-SD discovery, also advertise an `adminurl` equivalent where the
service stack supports it.

A client may surface this as "Printer Web Page", "More Info", "Open Printer
Utility", or similar. It is a best-effort affordance: the gateway cannot force
every operating-system print dialog to show or launch it.

Never put an authentication token in the advertised URL.

## Automation DX

Automation consumes stable contracts, not rendered HTML.

Required properties:

- versioned REST API;
- OpenAPI/JSON Schema;
- JSON on every read;
- stable ids;
- structured errors;
- capability discovery;
- idempotent `PUT`/delete;
- client-selected job id;
- ETag/If-Match or equivalent for concurrent writers;
- paginated/filterable job/event collections;
- deterministic dry-run/plan for routing-policy changes;
- explicit desired vs observed generations;
- machine-readable plugin and side-effect declarations.

A future CLI is a thin API client and must have JSON output. It must not contain
management logic unavailable through the API.

## Agent DX

Agents use the same authority surface as automation plus orientation metadata.

Useful surfaces:

- `/api/v1/capabilities`;
- `/api/v1/openapi.json`;
- schemas;
- current status;
- event stream/query;
- plugin manifests;
- side-effect/risk metadata;
- future MCP adapter over the API;
- optional concise `/llms.txt`-style orientation where it adds value.

Agent-only resources do not need to clutter human primary navigation.

Material mutations should expose preview/dry-run and explicit side-effect
boundaries. Credentials must be scoped; "can read job status" must not imply
"can email externally" or "can change printers".

## Red team: security and safety

### SSRF / destination abuse

Printer URIs, webhooks, remote imports, CIFS and future cloud connectors can
become server-side request primitives.

Controls:

- stable administrator-approved destinations instead of arbitrary per-job URLs;
- scheme allowlists;
- destination allowlists/trusted networks;
- redirect restrictions;
- plugin-specific egress;
- networkless renderer/normalizer workers;
- webhooks disabled by default.

### Discovery spoofing

Automatic mDNS/IPP discovery can provide attacker-controlled metadata.

Controls:

- discovery is observe-only;
- administrator approval before managed destination creation;
- IPP Everywhere first;
- no automatic arbitrary PPD/filter installation;
- identity/address/certificate changes surface as drift.

### Legacy print filters/custom drivers

These enlarge the executable attack surface.

Controls:

- driverless default;
- custom drivers advanced/admin-only;
- pinned reviewed packages;
- separate qualification per legacy path;
- no arbitrary upload-and-run driver UX.

### Hostile documents

PDF, PostScript, image, OCR and archive parsers need resource boundaries.

Controls:

- MIME sniffing plus extension consistency;
- limits on file size/page count/dimensions/decoded pixels/DPI;
- CPU/memory/wall-clock limits;
- parser workers without network;
- read-only source + staged output;
- restrictive Ghostscript/ImageMagick policies;
- quarantine anomalies;
- pinned converter versions.

### Filesystem attacks

- content-addressed immutable storage ids;
- separate display filename from storage identity;
- Unicode normalization;
- case/collision tests;
- no path traversal;
- no attacker-controlled symlink following;
- atomic finalization;
- incomplete upload quarantine.

### Management plane

Current Basic-over-HTTP candidate authentication is only acceptable as
trusted-LAN qualification scaffolding.

Before broader exposure:

- TLS or protected reverse-proxy termination;
- session/CSRF protection for browser credentials or a carefully bounded
  Basic-auth-over-TLS design;
- separate scoped API tokens for automation/agents;
- rate limiting;
- auth-event audit;
- secret redaction;
- bind-address controls;
- no management credentials in mDNS/IPP metadata.

### External delivery / data loss

Email/fax/cloud outputs can exfiltrate sensitive documents.

Controls:

- explicit destination objects and recipient policy;
- external-delivery preview;
- optional allowlists;
- side-effect-aware credentials;
- no routing from untrusted document instructions;
- immutable evidence of who/what requested each route;
- safe retry identity.

### Privacy and retention

The gateway can accumulate sensitive documents, OCR text and metadata.

Controls:

- configurable retention by artifact/job/event class;
- minimum logs by default;
- no document body in logs;
- redact addresses/credentials where appropriate;
- delete lifecycle with clear archive implications;
- machine contracts say what is retained.

## Reliability red team

Qualification must cover:

- restart during import;
- restart during reconciliation;
- duplicate submit/retry;
- partial upload;
- same filename/case/Unicode collisions;
- printer offline/recovery;
- destination address change;
- renderer timeout;
- full disk;
- read-only destination;
- invalid fax/email job;
- plugin crash;
- event/status file corruption;
- hundreds/thousands of jobs;
- simultaneous human/API/agent writers;
- clock/timezone changes;
- destination removal while jobs are queued.

One failure already found by public CI: CUPS can report scheduler readiness
before `lpadmin` is actually usable, producing transient bad-file-descriptor
errors. Administration is therefore retried/reconciled rather than treated as a
one-shot startup action.

## UI/UX/DX evidence gate

Borrow the proven portfolio method, not a project-specific visual identity.

Automated browser evidence:

- Chromium, Firefox, WebKit desktop;
- narrow 320 px reflow;
- representative touch viewport;
- axe WCAG 2.2 A/AA checks;
- no console/page errors;
- no ordinary UI horizontal overflow;
- semantic landmarks/headings/forms;
- visible keyboard focus;
- target-size checks;
- System/Light/Dark behavior if themes are offered;
- forced-colors/high-contrast sampling;
- reduced-motion behavior;
- critical user journeys;
- deterministic external-handoff classification.

Manual evidence remains required for:

- screen-reader sampling;
- keyboard journey coherence;
- zoom/reflow;
- destructive action clarity;
- visual hierarchy;
- copy truthfulness;
- device print-dialog behavior.

Automation is evidence, not a claim of complete accessibility/usability
certification.

## Multilingual/global concept sweep

Searches in English plus German, French, Spanish, Japanese, Chinese, Arabic,
Russian and other regional terminology converge on a few durable patterns.

### Embedded Web Server / Web Config is a universal mental model

Across HP/Epson/Brother/Canon documentation in multiple languages, users are
routinely taught to administer scan-to-email, address books, fax/network
settings and defaults through an embedded web interface.

Implication: the Document Gateway WebUI is not an alien pattern. Present it as
the gateway's normal management console and expose it from TrueNAS and IPP
metadata.

### Quick profiles/presets reduce error

Enterprise MFP ecosystems commonly expose saved/default scan/email profiles,
address books and "send to my email/folder" shortcuts.

Implication: make **Presets / Output Profiles** first-class. A preset should be
reviewable declarative state and may be locked/admin-managed.

### Multichannel output management is established prior art

Output-management systems model one input with multiple destinations such as
print + email + document management/archive + fax, with retry queues,
traceability and rules.

Implication: routed jobs and route legs are the right abstraction; do not model
email as a CUPS trick.

### Web upload and email-to-print are established alternative ingress paths

Many systems permit web/mobile upload and some permit email-to-print.

Implication: Web Upload is a strong future ingress candidate. Email-to-print
should remain later because it has a larger authentication, malware, spam and
loop surface.

### File-format expectations are broader than PDF

Localized enterprise MFP documentation routinely exposes PDF, JPEG, TIFF,
multipage TIFF, PDF/A, searchable/OCR PDF, text/Unicode text, HTML and sometimes
CSV/RTF/XPS.

Implication: a renderer/export plugin family has real user precedent. Keep
page-faithful and semantic/reconstructed outputs clearly distinguished.

### Internationalization findings

- canonical technical ids, MIME types, PWG media names, schemas and URLs remain
  invariant;
- labels, units and explanatory copy can localize independently;
- SMTPUTF8 and Unicode filenames/names require explicit handling;
- fonts and shaping are functional correctness issues, not just aesthetics;
- do not create translated copies without a demonstrated synchronization need;
- test representative Latin, Cyrillic, Arabic/RTL, CJK and Southeast Asian
  filenames/content before claiming broad text safety.

## Opportunities worth preserving, but not all implementing now

- secure/PIN/held print using IPP capabilities;
- web upload;
- destination/address book;
- "email me" / "save to my folder" identity-aware presets;
- job scheduling/defer;
- batch fax;
- routing rules based on trusted metadata;
- quota/accounting/environmental reporting;
- scan-to-cloud adapters;
- notification hooks;
- searchable archive integration;
- Paperless/document-management handoff;
- large-format/label/receipt profiles;
- e-reader/mobile derivatives;
- accessibility/large-print profiles;
- plugin marketplace/registry only after plugin signing/provenance and trust
  model are defined.

## Anti-features / things not to add casually

- arbitrary shell/filter hooks;
- arbitrary URL output per job;
- automatic custom-driver installation;
- document-content instructions that trigger external actions;
- unbounded "AI route this for me" behavior;
- credentials embedded in jobs;
- separate WebUI-only state;
- separate MCP-only semantics;
- hidden defaults that silently alter document fidelity;
- silent font substitution;
- automatic destructive cleanup without an explicit retention contract.

## Qualification order

1. stabilize the common API/desired-state/CUPS reconciliation;
2. qualify the null fax sender and null email sender interfaces;
3. implement the browser/a11y/surface-contract gate;
4. qualify routing/fanout with all network delivery still null/local;
5. add renderer/export plugins incrementally;
6. perform local TrueNAS HIL;
7. perform real Brother discovery/print/scan HIL;
8. add and qualify FRITZ!Box sender separately;
9. add real email transport separately;
10. only then consider additional network/cloud output plugins.
