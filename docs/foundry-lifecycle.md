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

## One-shot terminal observation (candidate)

`ENSURE_COMPLETED` is an observation-only operation for `foundry-custom` jobs.
It requires `operation_token` and `job_services`, a nonempty mapping of service
names to immutable `sha256:<64 lowercase hex>` image digests. The same exact
profile, ownership and materialization checks still apply. It never plans START,
REDEPLOY, DELETE or another retry: only a matching successful terminal readback
can produce NOOP; every other outcome is BLOCKED.

The independent target observer must supply `app.job` with the matching
`operation_token`, `materialization_identity`, and complete `containers` list.
Each container has a unique nonempty `id`, exact `service` and `image_digest`,
`state: exited`, and integer `exit_code: 0`. The app has exactly zero active
workloads. A stopped app, completed token, success log or product-written result
file alone is insufficient. Missing/extra/duplicate containers, failed jobs,
unknown exits, stale identity and ambiguous operations fail closed.

This is a proposed projection contract, **not a qualified TrueNAS observer**.
The exact native middleware fields and operation-token/container binding must
be qualified by the target adapter before a runtime verdict can rely on it.
The function only validates supplied evidence; it cannot establish that evidence
came from a live independent readback. No target/profile promotion follows.
Initial create and explicit restart remain separately admitted generic lifecycle
operations. Product integrity/retention and cleanup oracles remain separate.
Daemon ENSURE_RUNNING and the existing F0-F5 recipe are unchanged; do not apply
the daemon RUNNING oracle to a successfully completed job.
