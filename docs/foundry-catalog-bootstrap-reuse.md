# Foundry Catalog CP3 bootstrap reuse — contract rehearsal

Authority: private Foundry #328, independent red/blue #329. This is a **reusable
bootstrap contract rehearsal** on the public Foundry plane, not product source
or a deployable image.

## Reuse instead of a new app installer

The Catalog App image will be created and released from a **product-owned**
repository. The currently connected GitHub action set cannot create that
repository. Until a repository is available, Foundry can test the generic
install contract without pretending to ship the product.

The existing **canonical** operator pipeline already provides:

1. `tools/bind_truenas_site.py` — hash-bound exact changes to a normalized
   Compose template; declarative host directories and file-only secret
   references with ownership, permissions and retain-on-remove policy;
2. `tools/package_truenas_deployment_artifact.py` — deterministic
   `truenas-foundry-deployment-artifact/v1` identity and native TrueNAS
   `app.create(custom_app=true)` payload;
3. `tools/foundry_lifecycle.py` plus the separately governed private executor
   — site-capability/ownership-bound observe → plan → apply → verify. A
   successful artifact **does not** grant a target mutation.

`tests/test_foundry_catalog_bootstrap_rehearsal.py` passes an intentionally
**unresolvable** image URI (`registry.invalid`) through the first two steps.
It proves the existing interfaces can express a least-privilege read-only
controller, a catalog-index directory and a token-file reference without
capturing the secret, with retained data by default.

A real product image digest, runtime HTTP interface, data/secret provisioning,
portal, restart/health checks, rollback, and F0–F5 target qualification are
**not** proven by that test. Never use its sample digest or host paths as an
operator-ready deployment manifest.

## Deployment promotion sequence

- P0: independent product repository and source; build and unit-test the real
  read-only API service in its production Python image.
- P1: reproducibly build/publish immutable image digest; prove that the image
  embeds/attests the exact accepted federation/read-server source revision.
- P2: replace all deliberately invalid fixture identities with product release
  identities, and use existing exact site binding only. Store private bearer
  token in an independently provisioned owner-only file; the declarative
  resource spec must not contain the value.
- P3: deploy on disposable TrueNAS 25.04.2.6 via the existing generic operator,
  using separately accepted RDTE mutation authority; test cold start, native
  Apps listing, HTTP/portal reachability, stored secret permissions, recovery
  and safe replica/controller upgrade. Keep native catalog overlay experiments
  entirely out of the bootstrap.
- P4: stop/restart/reconcile/reinstall and retained-volume checks, plus a
  **separate external recovery path** after deliberately breaking the
  controller image. Fail closed on unsupported TrueNAS exact versions.
- P5: qualify UI and agent/API parity, no host Docker socket, no direct root
  middleware patch, and an independent red-team verdict; only then release an
  installable artifact from the product repo.
- P6: physical deployment is still HOLD under private Foundry #291, until
  separately authorized. No GHA passing result changes this.

## Open design issue: browser exposure

The reference read API deliberately binds only to `127.0.0.1`. Binding
that address **inside** a default Compose container does not make a published
container port reachable. Do not claim the conceptual Compose fixture provides
Web UI access. Product networking must either use a small proven authenticated
proxy boundary and independent TLS/CSRF controls, or move the service's
authenticated listener onto the container interface **only** after its
production access-control boundary passes adversarial HTTP tests. This is a
deployment acceptance gate, not a reason to make the test-only gateway public.

We will not introduce an extra scheduler, database, IaC-owned app installer,
second lifecycle engine or a permanent controller merely to bootstrap the
catalog.
