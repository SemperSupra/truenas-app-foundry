# Document Gateway candidate

A public-safe TrueNAS App candidate that turns CUPS into a small home document gateway:

- **Save to Documents** virtual PDF printer -> normalized files in `/data/output`;
- optional **physical Brother/other printers** -> CUPS queues, driverless IPP by default;
- **scanner inbox** -> `/data/incoming/scan`;
- **FRITZ!Box fax inbox** -> main data folder, a read-only TrueNAS host path, or a read-only SMB/CIFS share;
- **Fax Outbox** -> backend-neutral durable fax jobs with a pluggable sender API; the public candidate ships only a non-transmitting `null` sender;
- deterministic naming, collision handling, checksums, optional JSON sidecars, and an always-on hidden JSONL event journal.

See [CONTROL_PLANE.md](CONTROL_PLANE.md) for the format/export model and the planned common idempotent management API used by WebUI, CLI, API clients, MCP, and future native GUIs.

## Three audiences

### Humans

The TrueNAS form is organized around tasks rather than CUPS internals. The safe default is explicit IPP access on a published TrueNAS port. AirPrint/mDNS can be enabled later with a dedicated LAN identity or host-network compatibility mode.

For a normal Brother network printer, add a Physical Printer and use its `ipp://...` or `ipps://...` URI with **IPP Everywhere / driverless**. Legacy printers can use an installed CUPS model.

For scanner intake, expose the selected Document Library through the normal TrueNAS SMB service and configure the scanner to write into:

`incoming/scan`

Received fax files can use `incoming/fax`, an existing host path, or a direct read-only FRITZ!Box SMB/CIFS source.

Outbound fax is deliberately separate from FRITZ!Box transmission. Jobs are queued under `outgoing/fax/pending/<job-id>`. The initial `null` sender validates and reports them but never transmits, deletes, or marks them sent. A later FRITZ!Box sender can implement the same sender ABI.

CUPS also exposes its native administration WebUI on the CUPS portal. It is useful for low-level printer/job diagnostics, but the Document Gateway control plane is intended to be the normal source of truth so WebUI, CLI, API, MCP, automation, and agents do not each implement their own management behavior.

### Automation

Stable paths and config keys are intentional API surface:

| Contract | Path |
|---|---|
| PDF print spool | `/spool/pdf` |
| scanner ingress | `/data/incoming/scan` |
| data-folder fax ingress | `/data/incoming/fax` |
| outbound fax pending | `/data/outgoing/fax/pending/<job-id>` |
| fax sender status | `/data/.document-gateway/fax-sender.json` |
| normalized output | `/data/output` |
| runtime contract | `/data/.document-gateway/contract.json` |
| status | `/data/.document-gateway/status.json` |
| event journal | `/data/.document-gateway/events.jsonl` |

The normalizer waits for files to stop changing before importing them and writes output atomically.

### Agents

Agents should prefer `contract.json`, `status.json`, and `events.jsonl` over scraping human UI text. Runtime logs are JSON lines. Input/output paths are versioned contract surface and output names are deterministic.

Default readable filename form:

`YYYY-MM-DD_HH-mm-ss__<source>__<clean-original-name>.<ext>`

Sources are `print`, `scan`, and `fax`. Name collisions append `__02`, `__03`, and so on.

## Network modes

- **Published IPP** — safe default; CUPS is exposed on a chosen TrueNAS host port. Clients add the queue by address. No claim of automatic mDNS discovery.
- **Dedicated LAN identity** — best fit for AirPrint/Mopria discovery. Requires a pre-created external Docker/macvlan network and reserved IP; HIL qualification is required.
- **Host network mDNS** — compatibility fallback. Upstream warns that NAS-host Avahi and container Avahi can collide on UDP 5353, so this is not the default.

## Qualification boundary

Public CI validates source rendering, normalized Compose, UX contract, multiple network/fax profiles, and a live container smoke that exercises PDF print -> normalization plus scan/fax intake. It does **not** claim TrueNAS HIL, Brother hardware interoperability, FRITZ!Box interoperability, or LAN multicast behavior.

Before private promotion, bind the exact multi-arch OCI digest for `chuckcharlie/cups-avahi-airprint:2.1.3` and re-intake that exact source/deployment identity.
