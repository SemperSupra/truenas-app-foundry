# Native official-catalog upgrade fixture

Authority: `SemperSupra/truenas-app-foundry-private#281`.

This fixture is separate from the universal native-catalog lifecycle control.

Its sole purpose is to create deterministic source evidence for a **real native
`app.upgrade` execution** instead of treating `upgrade_available=false` as proof that
the upgrade lifecycle itself works.

## Exact generated catalog pair

The fixture binds generated `truenas/apps` catalog state, not only the editable source
metadata:

- from: `c751f183ab5203ae06aae0573f5484fc5cff5a40`
  - generated ntfy catalog version `1.1.20`
  - generated app_versions blob `2534b330a8b70eb5a75c2afd7a4ec3b2b8d4da35`
- to: `c60d966e198721ab1e84cf815d969acf8bb11a0b`
  - generated ntfy catalog version `1.1.21`
  - generated app_versions blob `4b37e81949d84a2d491de8685022bea7c8ade9de`

Both sides are ntfy `v2.28.0`, app library `2.3.4`, with the same library hash.
That deliberately isolates the catalog-package version transition.

## Claim boundary

Passing this source gate does **not** mean native upgrade works on any TrueNAS target.

A runtime row is qualified only when a disposable target:

1. consumes the exact older generated catalog source;
2. installs native catalog ntfy `1.1.20`;
3. independently reads back that identity;
4. transitions its official catalog view to the exact newer generated source;
5. observes `upgrade_available=true`;
6. executes native `app.upgrade`;
7. verifies catalog version `1.1.21`, native lineage, health, and desired config;
8. re-plans to NOOP;
9. performs final owned-state cleanup.

If a target cannot deterministically expose the two exact generated catalog states,
that is a fixture/materialization gap, not an executed-upgrade PASS.
