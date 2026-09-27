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

## Destination model

A destination is a stable resource, not just a CUPS queue.

Suggested kinds:

- `physical-print`
- `archive`
- `fax-outbox`
- `export`

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
- `PUT /api/v1/fax/jobs/{job-id}`: client-selected job id prevents duplicate
  fax enqueue on retry.
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
- `PUT /api/v1/fax/jobs/{job-id}`
- `PUT /api/v1/settings/{section}`

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
