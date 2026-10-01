# V2 exact-validator render/install qualification

V1 native development-catalog validation is accepted under
`SemperSupra/truenas-app-foundry-private#274`.

V2 now qualifies the next native TrueNAS Apps oracle: the exact pinned
`truenas/apps` render/install lifecycle.

The upstream pinned `truenas/apps` CI script remains authoritative for:

- library copy;
- template rendering;
- Compose validation;
- container start;
- health assessment;
- failure diagnostics;
- cleanup.

The only substituted seam is the upstream floating validator image acquisition.

`tools/patch_truenas_ci_for_exact_validator.py` fail-closes unless the audited
upstream image constant and `pull_app_catalog_container()` body match exactly.
It replaces only:

1. `ghcr.io/truenas/apps_validation:latest` with the local validator image
   built from the exact V1 `apps_validation` commit and resolved middleware
   base digest; and
2. the network pull with `docker image inspect` of that exact local image.

The V2 workflow then runs the exact pinned upstream `.github/scripts/ci.py`
against the `community/element-web` `basic-values.yaml` control.

A V2 PASS proves the reproducible native render/install harness. It does not by
itself make a Foundry app catalog-ready. F6 requires an actual Foundry bootstrap
candidate to pass both V1 source validation and V2 render/install before catalog
export readiness may be asserted.

Authority: `SemperSupra/truenas-app-foundry-private#274`.
