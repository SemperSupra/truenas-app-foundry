# Version-aware TrueNAS target reconciliation

Tracking authority: `SemperSupra/truenas-app-foundry-private#267`.
Real-system substrate qualification: `SemperSupra/agent-dispatch-private#396`.

The Foundry must not assume that a target is the same TrueNAS version, API shape, Apps
backend, storage topology, or site configuration as a previously-qualified appliance.
Native runtime realization therefore uses five explicit stages:

```text
observe -> discover -> plan -> apply -> verify
```

## Observe

Observation is read-only and site-local. The private site adapter records the exact
reported TrueNAS version/build/platform and only the capabilities/state needed for the
desired materialization. Sensitive certificate material, raw private paths, credentials,
and site inventory stay local.

The sanitized observation envelope supplied to public logic includes:

- `system.version` and platform identity;
- the public middleware methods actually observed for the operation;
- target App presence/state and a Foundry materialization identity when owned;
- an explicit ownership state: `absent`, `owned`, or `foreign`.

Exact version text is necessary but is not a sufficient runtime fingerprint. Each admitted
target also binds an exact compatibility-profile Git blob, middleware source commit/API
family, release-specific storage semantics, Apps-gate semantics, and a minimum public
method set. Discovery rejects mutation readiness when the observed public method set no
longer satisfies that exact profile.

## Discover

`tools/truenas_target_profile.py discover` matches the exact observed version against
`.foundry/truenas-target-tracks.json`.

Exact release identity is mandatory for mutation. A train/family match is useful for
qualification routing only. Unknown releases, anticipated RCs, and nightly builds are
never promoted from a floating selector into an apply claim.

For an exact target, discovery emits a content-bound profile identity and hashes both
the sanitized observation and selected profile identity. Planning carries those hashes
forward. Apply must re-observe immediately before mutation and refuse the operation if
the target/profile fingerprint changed.

The initial matrix tracks:

- 25.04.1 as an existing source-profile/deployed-legacy target;
- 25.04.2.6 as a prior consumer-specific HIL anchor;
- 25.10.7 as the current stable exact source anchor with a profile still to qualify;
- 26.0.0-BETA.3 as the current early-release real-system RDTE target, accepted through
  T3 while T4/T5 remain prerequisites for Foundry apply/verify qualification;
- exact 26/27 future builds as qualification-only until their exact profiles exist.

## Plan

Planning combines desired Foundry state with the discovered target profile and observed
owned state. It fails closed when:

- the exact version/profile is unknown;
- the profile is not apply-qualified;
- required public API methods are not observed;
- target state is foreign/unowned;
- desired materialization identity is absent.

For an apply-qualified profile, the convergent action is one of `CREATE`, `UPDATE`,
or `NOOP`. The plan requires version, method, and ownership re-observation immediately
before apply.

## Apply

Apply is private/site-local and remains under durable mutation authority. The public
repository does not contact private appliances. The private executor consumes the
public plan, rechecks its preconditions, and invokes only the exact API semantics bound
to the discovered profile. It may not adopt foreign state or broaden the plan.

## Verify

Verification independently observes the target again and compares the exact target
identity, ownership, materialization identity, App state, and active workload evidence
with desired state. A successful middleware call does not count as verification.

A second plan after successful verification should converge to `NOOP`.

## Qualification gates

A version is not `apply_qualified` merely because source inspection or a public
workflow is green. Promotion requires exact source/profile identity plus accepted
real-system runtime evidence. For 26.0.0-BETA.3, Agent Dispatch T4 Apps runtime and T5
lifecycle are required before generic Foundry apply/verify qualification can be
claimed.
