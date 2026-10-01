# Foundry lifecycle planning

This public-safe contract extends the existing exact-version target discovery
without broadening the site mutation executor.

Lifecycle intent is explicit and deterministic:

- START
- STOP
- REDEPLOY
- DELETE

The planner requires exact target discovery, an apply-qualified target, freshly
observed ownership, exact materialization identity, and the operation-specific
public middleware method.

START and STOP converge to NOOP when the observed state already satisfies the
intent. REDEPLOY remains explicit. DELETE currently supports only
`delete_policy=retain-data`.

App ownership is deliberately not treated as storage ownership. Generic
lifecycle DELETE therefore may remove the App while retaining ixVolume data.
Deleting owned persistent data requires a separately qualified storage
ownership/provenance contract.

Reinstall is composition rather than a special mutation:

`DELETE -> verify absent -> normal CREATE plan/apply -> verify -> re-plan NOOP`.

Private execution authority remains separate from this public planner.
