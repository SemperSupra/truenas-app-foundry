# V2 render/install adapter preparation

This branch prepares, but does not yet execute, the V2 TrueNAS-native
render/install qualification rung.

The upstream pinned `truenas/apps` CI script owns the behavior we want to
preserve: library copy, template rendering, Compose validation, container
start/health assessment, diagnostics, and cleanup.

The only unqualified seam in that script is its hard-coded floating validator
image:

`ghcr.io/truenas/apps_validation:latest`.

`tools/patch_truenas_ci_for_exact_validator.py` fail-closes unless the
audited upstream image constant and `pull_app_catalog_container()` body match
exactly. It then:

1. replaces the floating image constant with a local
   `foundry/apps-validation:<exact-commit-prefix>` tag;
2. replaces the network pull with `docker image inspect` of that prebuilt
   image;
3. leaves the rest of the upstream CI script byte-for-byte unchanged.

The V2 execution workflow is deliberately not added on this preparation branch.
V1 native dev-catalog validator qualification under private authority #274 must
be accepted first.
