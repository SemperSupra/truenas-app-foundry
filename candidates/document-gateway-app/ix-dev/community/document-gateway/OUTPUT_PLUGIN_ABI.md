# Document Gateway output/renderer plugin ABI

Status: candidate ABI.  The purpose is to freeze the core boundary before
individual converters are selected.

## ABI identity

`document-gateway.renderer/v1`

Renderer plugins are **pure artifact transformers**.  They do not send mail,
dial fax, call webhooks, modify printer queues, or choose destinations.  Delivery
side effects belong to sender/output-channel plugins.

This distinction is intentional:

```
artifact -> renderer/export plugin -> derived artifact -> sender/destination
```

A single route leg may invoke zero or more renderers before the output-channel
plugin consumes the resulting artifact.

## Plugin manifest

Each renderer exposes a machine-readable manifest:

```json
{
  "abi": "document-gateway.renderer/v1",
  "id": "example.pdfa",
  "version": "1.0.0",
  "inputs": ["application/pdf"],
  "outputs": ["application/pdf"],
  "fidelity": ["page-faithful"],
  "deterministic": true,
  "network": "none",
  "side_effects": "artifact-only",
  "options_schema": "schemas/example.pdfa.options.json"
}
```

Required manifest fields:

- `abi` — exact ABI identifier;
- `id` — stable machine-safe plugin id;
- `version` — plugin implementation version;
- `inputs` — accepted MIME types;
- `outputs` — produced MIME types;
- `fidelity` — one or more semantic classes below;
- `deterministic` — whether identical qualified inputs/options are expected to
  produce byte-identical outputs;
- `network` — `none` by default; a renderer requiring network is a separate
  security-review class;
- `side_effects` — MUST be `artifact-only` for this ABI;
- `options_schema` — JSON Schema for plugin-specific options.

## Fidelity vocabulary

- `source-native` — original semantic source preserved;
- `page-faithful` — page appearance is the primary invariant;
- `semantic-native` — semantic structure originates in the supplied source;
- `semantic-reconstructed` — structure was inferred from page/image content;
- `image-faithful` — image pixels/appearance are the primary invariant;
- `metadata-only` — no user-visible document body is produced.

The core MUST expose this value to humans, automation, and agents.  A Markdown
or EPUB artifact reconstructed from a print/PDF source must never be represented
as source-native.

## Render request

The core provides a request directory containing `request.json` and read-only
input artifacts.  The plugin receives a writable output directory.

Example request:

```json
{
  "abi": "document-gateway.renderer/v1",
  "request_id": "01K...",
  "job_id": "01K...",
  "route_leg_id": "archive",
  "input": {
    "artifact_id": "sha256:...",
    "media_type": "application/pdf",
    "path": "input/document.pdf",
    "sha256": "..."
  },
  "target": {
    "media_type": "application/pdf",
    "profile": "archive-pdfa"
  },
  "options": {
    "conformance": "PDF/A-2b",
    "font_policy": "fail"
  },
  "locale": "en-US"
}
```

The plugin MUST treat all paths as sandbox-relative and MUST NOT follow input
symlinks outside the request root.

## Render result

The plugin writes `result.json` atomically when complete.

```json
{
  "abi": "document-gateway.renderer/v1",
  "request_id": "01K...",
  "status": "succeeded",
  "artifacts": [
    {
      "role": "primary",
      "path": "output/document.pdf",
      "media_type": "application/pdf",
      "sha256": "...",
      "bytes": 123456,
      "fidelity": "page-faithful"
    }
  ],
  "warnings": [],
  "provenance": {
    "plugin": "example.pdfa",
    "plugin_version": "1.0.0",
    "options_sha256": "..."
  }
}
```

Allowed terminal states:

- `succeeded`;
- `failed`;
- `unsupported`;
- `resource-exhausted`;
- `policy-rejected`.

Partial outputs are never promoted to the artifact store.

## Artifact roles

A renderer may return more than one artifact:

- `primary`;
- `page-image`;
- `thumbnail`;
- `text`;
- `layout`;
- `metadata`;
- `accessibility-report`.

Every returned artifact has its own MIME type and digest.

## Core output families

The ABI is deliberately MIME-driven rather than enum-limited.  Initial families
to qualify incrementally:

### Page/archive

- `application/pdf`;
- PDF/A profiles represented as PDF plus explicit conformance metadata;
- future PDF/X or accessible/tagged PDF only after a use case and validator
  exist.

### Image

- `image/png`;
- `image/jpeg`;
- `image/tiff` including multipage TIFF where supported.

### Text/layout

- `text/plain`;
- `text/html`;
- hOCR;
- ALTO XML;
- structured JSON.

### Reflow/semantic

- `text/markdown`;
- `application/epub+zip`;
- `text/html`.

Markdown/HTML/EPUB generated from page-only input default to
`semantic-reconstructed`.

## Pipeline composition

The core, not the plugin, owns pipeline construction.

Example:

```
PDF
 ├─> OCR/searchable-PDF
 ├─> OCR/layout -> Markdown
 └─> OCR/layout -> semantic HTML -> EPUB
```

Rules:

- pipelines are finite DAGs;
- the core validates MIME compatibility before execution;
- no plugin may recursively invoke another plugin;
- no implicit network access;
- cycles are rejected;
- every edge produces a content-addressed artifact with provenance.

This keeps plugins small and independently qualifiable.

## Idempotency and caching

A render request has a cache identity derived from:

- input artifact digest;
- plugin id + qualified version;
- normalized options;
- relevant core ABI version.

If `deterministic=true`, a retry MAY reuse an existing matching artifact.  A
plugin must not embed wall-clock timestamps, random ids, hostnames, or other
volatile data into a supposedly deterministic artifact unless the profile
explicitly includes that data and therefore changes the cache identity.

## Font/shaping contract

Renderers that touch text must report:

- embedded fonts retained;
- fonts substituted;
- missing glyphs;
- shaping/script warnings;
- language/OCR model selections where relevant.

Profile policies:

- `fail`;
- `warn-and-substitute`;
- `substitute`.

Silent substitution is not permitted for archival/high-fidelity profiles.

## Resource and security contract

Default execution envelope:

- no network;
- read-only input;
- private writable scratch/output;
- CPU, memory, wall-clock and output-size limits;
- no host filesystem;
- no Docker socket;
- no device access unless a plugin class explicitly requires and qualifies it;
- untrusted document parsers isolated from sender credentials.

Plugins do not receive mail, fax, printer, cloud, or management credentials.

## Capability projection

The control API exposes renderer manifests through `GET /api/v1/plugins` and
derives supported conversions from the manifest graph.

Humans see purpose-oriented choices such as:

- Archive PDF/A;
- Page images;
- Searchable PDF;
- Extract text;
- Markdown;
- HTML;
- EPUB.

Automation/agents see exact MIME paths, fidelity classes, schemas, plugin
versions and qualification state.

## Qualification rule

An ABI-compatible plugin is not automatically a qualified plugin.

Qualification records must identify:

- exact plugin/container digest;
- exact dependencies;
- supported input/output pairs;
- deterministic/non-deterministic behavior;
- multilingual/font corpus coverage;
- malformed/hostile-document tests;
- resource-limit tests;
- fidelity checks;
- reproducibility evidence where claimed.
