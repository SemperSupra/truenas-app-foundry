# TrueNAS catalog toolchain qualification

Foundry keeps catalog-authoring qualification separate from TrueNAS runtime
version qualification.

The exact catalog authoring toolchain is recorded in
`.foundry/truenas-catalog-toolchain.json`.

V1 proves the TrueNAS-native development-catalog validator against exact
`truenas/apps` and `truenas/apps_validation` Git commits.

The upstream validator Dockerfile currently declares the floating base
`ghcr.io/truenas/middleware:master`. Foundry does not treat that string as an
immutable dependency. The V1 workflow:

1. pulls that declared base;
2. resolves the observed image to an exact repo digest;
3. replaces the one audited Dockerfile FROM line with that digest;
4. builds the validator from the exact pinned validator Git commit;
5. runs the same `apps_dev_charts_validate validate --path` oracle used by
   the upstream TrueNAS Apps development-catalog workflow;
6. records the exact source refs, resolved base digest and built image identity.

This is a toolchain/oracle qualification. It does not prove a Foundry
candidate, render/install behavior, catalog readiness, or any TrueNAS runtime
version.

The next rung, V2, must remove the floating-image assumption from the upstream
render/install path and exercise candidate test-values through an exact
validator image before F6 catalog-ready export can be accepted.

Authority: `SemperSupra/truenas-app-foundry-private#274`.
