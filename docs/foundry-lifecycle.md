# Profile-driven Foundry lifecycle

Authority: `SemperSupra/truenas-app-foundry-private#274`.
Target/profile authority: `SemperSupra/truenas-app-foundry-private#267`.

This public contract turns the Foundry lifecycle requirement into explicit desired-state
planning while preserving the existing:

`observe -> discover -> plan -> apply -> verify`

architecture.

It does **not** contact or mutate a TrueNAS host.

## Adapters

Two realization adapters share the same ownership, profile-fingerprint, planning and
postcondition model:

- `foundry-custom`: Foundry/pre-catalog source is rendered to an immutable deployment
  artifact and realized through the qualified Custom App path. Image/app changes are
  normal materialization `UPDATE` actions. Native `app.upgrade` is not used.
- `official-catalog`: native TrueNAS catalog semantics remain intact. Native
  `app.upgrade` may be planned only when the exact target exposes it and an upgrade is
  actually observed.

This distinction prevents a catalog lifecycle test from being "passed" by silently
turning the catalog application into a Custom App.

## Desired-state operations

The v2 lifecycle intent supports:

- `ENSURE_RUNNING`
- `ENSURE_STOPPED`
- `ENSURE_ABSENT`
- `REDEPLOY`
- `UPGRADE` for `official-catalog` only
- `REINSTALL`

START/STOP/DELETE/UPGRADE converge to `NOOP` when the independently observed state
already satisfies the intent.

REDEPLOY and REINSTALL are event-like operations, so they require a durable
`operation_token`. Replaying a token already observed complete yields `NOOP`.

REINSTALL is deliberately compositional:

`owned presence -> DELETE_FOR_REINSTALL -> verify absence -> CREATE_HANDOFF -> normal materialization plan/apply/verify -> mark token complete -> NOOP`

No special reinstall mutation bypasses the ordinary create/delete or ownership gates.

## Ambiguous/interrupted operations

Observation carries an operation state:

- `stable`
- `in-flight`
- `ambiguous`

Any `in-flight` or `ambiguous` state blocks mutation and requires fresh
reconciliation. Blind retry is not a valid lifecycle transition.

This is the public planning counterpart to the private executors' existing
`AMBIGUOUS_AFTER_MUTATION` and `retry_allowed_without_reconciliation=false`
receipts.

## Persistent-data boundary

Generic delete and reinstall are currently `retain-data` only.

App ownership is not persistent-storage ownership. The generic contract does not infer
authority to delete ixVolumes or other persistent data from App ownership.

## F0-F5 acceptance recipe

A TrueNAS exact target is Foundry-qualified only after the same Foundry-owned source and
artifact identity complete:

- **F0** exact observed target/profile/source/capability fingerprint;
- **F1** inventory resolution + immutable materialization identity;
- **F2** clean create + independent RUNNING/health verification;
- **F3** stop/start + configuration update/read-back + applicable native upgrade +
  redeploy/persistence;
- **F4** re-plan to NOOP + deterministic reconciliation after ambiguous/interrupted
  operations;
- **F5** retain-data delete/absence + reinstall + owned-state verification.

The full recipe is machine-readable through:

`python3 tools/foundry_lifecycle.py recipe`

This contract does not make any currently registered target `apply_qualified`; runtime
promotion still requires accepted exact-version evidence.
