# Document Gateway control plane and format model

## Principle

CUPS/IPP is a page-oriented ingress and physical-print transport adapter, not the
Document Gateway's domain model.  The gateway keeps transport, artifact
conversion, and management separate so humans, automation, and agents all see
the same resources and state.

## Format classes

### Canonical page artifact

PDF is the default canonical representation for anything that arrived through a
print dialog because it preserves page appearance and is broadly reusable.

The gateway SHOULD retain the original source artifact when one exists (for
example an API upload of DOCX, Markdown, HTML, or EPUB) instead of pretending a
rendered print stream can reconstruct the original semantics.

### Device transport formats

These are negotiated with an IPP destination and normally should not be kept as
the user's canonical document:

- application/pdf
- image/pwg-raster
- image/urf (Apple Raster / AirPrint)
- image/jpeg
- application/postscript where a legacy target needs it
- application/vnd.hp-pcl where a legacy target needs it

A destination reports its accepted formats and capabilities.  The gateway
selects the least-lossy compatible transport automatically.

### Reusable derived artifacts

An output profile MAY produce one or more derivatives:

- PDF: page-faithful default
- PDF/A: archival profile
- PNG/JPEG: individual rendered pages
- TIFF: multipage imaging/fax workflows
- plain text: OCR/text extraction
- hOCR or ALTO XML: OCR text plus layout coordinates
- Markdown: semantic/reflowable derivative
- HTML: semantic/reflowable derivative
- EPUB: reflowable reading derivative
- JSON: metadata, provenance, structure, and machine-facing extraction

Markdown, HTML, and EPUB are not CUPS-native output formats.  When the only
input is a print job they are reconstructed derivatives and therefore lossy:
printing normally destroys document structure such as headings, links, logical
reading order, footnotes, and source styles.  They become higher-confidence
outputs when the original semantic source is submitted directly to the
Document Gateway.

Do not build the conversion architecture around `cupsfilter`; it is a useful
compatibility tool but is deprecated.  Conversion providers belong behind a
gateway renderer/export plugin boundary.

## Routed job model

A gateway job represents one user intent and can fan out to multiple independent
delivery legs.  A single action such as **Print + archive + email me** MUST be
one job with three legs rather than three unrelated operations.

Core resources:

- **Artifact** — immutable original, canonical, or derived content with digest,
  MIME type, provenance, and transformation history.
- **Job** — immutable submitted intent plus stable client-selected job id.
- **Route leg** — one requested output from the job to one destination.
- **Destination** — stable endpoint configuration.
- **Output profile** — page/media/rendering/transformation policy.
- **Delivery attempt** — one try for one route leg.
- **Event** — append-only machine-facing lifecycle evidence.

Each leg has independent state such as `queued`, `rendering`, `delivering`,
`succeeded`, `failed`, or `deferred`.  Retrying one failed leg MUST NOT
duplicate already-successful legs.

Example:

```json
{
  "job_id": "01K...",
  "artifact": "sha256:...",
  "routes": [
    {"id": "paper", "destination": "brother-office", "profile": "office-a4"},
    {"id": "archive", "destination": "documents", "profile": "archive-pdfa"},
    {"id": "mail", "destination": "email-me", "profile": "email-pdf"}
  ]
}
```

This is the core abstraction that lets an ordinary desktop print operation
become a reusable document-routing action without coupling CUPS to email,
archive, fax, or future outputs.

## Email output channel

Email is a first-class output channel, not a CUPS notifier.  CUPS mail
notification features report job events; they are not the document-delivery
contract for this gateway.

An email destination should support a sender plugin boundary and a durable
outbox.  The route leg owns:

- recipients (To/Cc/Bcc according to policy);
- subject/body template;
- attachment profile (canonical PDF, archival PDF, original, or selected
  derivatives);
- stable delivery id/message identity for retry de-duplication;
- attachment-size and recipient policy;
- observed send/bounce/deferred state where the backend exposes it.

Initial implementation SHOULD use a non-transmitting `null` email sender before
SMTP or provider-specific backends are qualified.  Future backends can include
SMTP, Gmail, Microsoft Graph, or another mail relay without changing job
producers.

An email delivery failure MUST NOT change the success state of an already
completed physical print or archive leg, and vice versa.

## Destination model

A destination is a stable resource, not just a CUPS queue.

Suggested kinds:

- `physical-print`
- `archive`
- `fax-outbox`
- `email`
- `export`
- `file/archive`
- `webhook` (disabled by default until SSRF policy is explicitly configured)

Each destination publishes:

- stable id
- human display name
- kind
- accepted input MIME types
- produced artifact/transport MIME types
- option schema/capabilities
- availability and observed state
- implementation adapter/plugin

Page-oriented destinations MAY also be projected into CUPS/IPP so existing
desktop/mobile applications see normal printers.

Semantic exports such as Markdown and EPUB SHOULD primarily be API/WebUI/CLI
operations rather than fake printers.  A convenience virtual printer can be
offered later, but its output must be labeled as reconstructed/lossy.

## Fax sender plugin boundary

Fax output is a backend-neutral durable queue.

Plugin ABI: `document-gateway.fax-sender/v1`.

The queue's canonical payload is PDF plus `job.json`.  A sender plugin owns
transport-specific conversion (for example TIFF/SFF/raster generation) because
those requirements are a property of the actual fax backend.

The initial `null` sender:

- validates queued jobs;
- reports them through status/events;
- has `can_transmit=false`;
- never moves, deletes, or marks a job sent.

A future `fritzbox` sender implements the same ABI without changing producers
or queue format.

## Common management core

All management clients MUST use one versioned control API.  No WebUI-only or
CLI-only business logic.

The control plane follows desired-state reconciliation:

1. client PUTs desired resource state;
2. API validates and persists the new generation atomically;
3. reconcilers observe desired state;
4. adapters make CUPS/plugins/runtime match it;
5. observed state is published separately;
6. clients can safely retry requests.

### Idempotency rules

- `PUT /api/v1/destinations/{id}`: complete idempotent create/update.
- `DELETE /api/v1/destinations/{id}`: idempotent removal; absent is success.
- `PUT /api/v1/output-profiles/{id}`: idempotent create/update.
- `PUT /api/v1/jobs/{job-id}`: client-selected job id prevents duplicate
  routed-job creation on retry.
- `PUT /api/v1/fax/jobs/{job-id}`: compatibility/convenience facade over a
  routed job with a fax-outbox leg.
- imperative actions, where unavoidable, require an `Idempotency-Key`.
- resources carry `generation`; observed resources carry
  `observed_generation`.
- updates SHOULD support ETag/If-Match to prevent lost concurrent edits.

### Initial API surface

Read:

- `GET /api/v1/capabilities`
- `GET /api/v1/destinations`
- `GET /api/v1/destinations/{id}`
- `GET /api/v1/jobs`
- `GET /api/v1/status`
- `GET /api/v1/events`
- `GET /api/v1/output-profiles`
- `GET /api/v1/plugins`

Write:

- `PUT /api/v1/destinations/{id}`
- `DELETE /api/v1/destinations/{id}`
- `PUT /api/v1/output-profiles/{id}`
- `PUT /api/v1/jobs/{job-id}`
- `PUT /api/v1/fax/jobs/{job-id}`
- `PUT /api/v1/settings/{section}`
- future `PUT /api/v1/policies/{id}` for reusable routing/security policy

## User interfaces

### WebUI

First-class initial management client.  It calls only the versioned API and
offers purpose-oriented views:

- Destinations / printers
- Jobs
- Document output profiles
- Scanner/fax intake
- Fax outbox and sender plugins
- Network/discovery
- Status/events

The existing CUPS WebUI remains available as an Advanced CUPS diagnostic view,
not as the gateway's source of truth.

### CLI

A thin client over the same API.  It SHOULD support JSON output on every read
operation and declarative apply from JSON/YAML.

Example future shape:

```
document-gateway destination get
document-gateway destination apply brother-office.yaml
document-gateway fax enqueue --id <id> --to <number> document.pdf
document-gateway status --json
```

### MCP

MCP is an adapter over the same API, not a second control implementation.
Tools map to stable resources/actions and return the same machine schemas.

### Native GUI

Any future desktop/mobile GUI consumes the same API and therefore has no
special management authority.

## Rendering and media capability policy

The gateway MUST keep **document/page intent** separate from **physical media**
and from **screen presentation**.

For physical IPP destinations, populate controls from observed capabilities
(`media-supported`, `media-ready`, `media-col-database`, sides, resolution,
finishings, color modes, output bins, etc.) rather than maintaining a
US/EU-centric hard-coded list.

Output profiles MAY specify:

- named or custom media size, orientation, margins and scaling;
- source tray/media type and output bin;
- simplex/duplex and binding edge;
- copies, collation, page ranges, N-up, booklet, reverse order;
- color/grayscale/monochrome, resolution and rendering intent;
- finishings such as staple, punch, fold and bind when observed as supported;
- roll/custom media for labels, receipts and large format;
- bleed/crop marks where a renderer/output workflow supports them.

For screen/reflow outputs, preserve semantics where they exist and prefer
responsive HTML or reflowable EPUB.  Fixed-layout PDF/EPUB remains appropriate
when exact page geometry is part of the content.

Font handling is a preflight concern.  Prefer embedded fonts.  A profile SHOULD
have an explicit missing-font policy (`fail`, `warn-and-substitute`, or
`substitute`) and record every substitution plus missing-glyph result in
provenance.  Silent substitution is not acceptable for archival, legal,
multilingual, or high-fidelity output.

## CUPS reconciliation

CUPS can expose IPP capabilities, printer/job status, and driverless printing.
The gateway controller should reconcile gateway destinations into CUPS rather
than allowing each frontend to execute `lpadmin` independently.

This gives one authority boundary and keeps network mode independent from the
management clients.

## Source of truth

TrueNAS App questions configure bootstrap/runtime necessities such as storage,
ports, credentials, and initial destinations.

Dynamic gateway state belongs to the control-plane desired-state store.
Runtime discovery/observed state is separate from desired state.  The WebUI,
CLI, API, MCP, and agents all mutate the same desired resources.
