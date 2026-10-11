# Autonomous TrueNAS Foundry 4RDTE: cloud-only execution contract

Authority: [Foundry #274](https://github.com/SemperSupra/truenas-app-foundry-private/issues/274) (lifecycle), [#282](https://github.com/SemperSupra/truenas-app-foundry-private/issues/282) (product/version matrix), [#281](https://github.com/SemperSupra/truenas-app-foundry-private/issues/281) (native catalog controls), [#290](https://github.com/SemperSupra/truenas-app-foundry-private/issues/290) (generic operator), and [Agent Dispatch #396](https://github.com/SemperSupra/agent-dispatch-private/issues/396)/[#480](https://github.com/SemperSupra/agent-dispatch-private/issues/480) (real-system compute/session authority).

## Outcome and nonnegotiable policy

One source-defined application **not yet in the official TrueNAS catalog** must go through the genuine TrueNAS Apps implementation on each version it declares support for: source validation, immutable materialization, create, independent RUNNING/health readback, stop/start, configuration update, redeploy, NOOP, interrupted-operation observation/reconciliation, data-policy bounded remove, reinstall, application-specific functional oracle, cleanup, and upstream catalog export validation. A successful full F0-F5 cell is evidence for the **exact product, source, image, profile, TrueNAS release and oracle** recorded, not other versions or products. F6 validates catalog-source/export readiness separately. Physical/production mutation and automatic publication are outside this RDTE's authority.

Primary free compute: existing **public standard GitHub Actions x64 KVM TrueNAS harness** `SemperSupra/agent-dispatch@experiment/gha-kvm-system-rdte`. No private-hosted Actions usage, paid or larger runners, external private secrets, user workstation, local NAS, or persistent cloud VM required. Public work is strictly public-safe. Agent Dispatch coordinates bounded execution and the one-heavyweight lane; it is not an additional product source of truth. GitHub is the durable authority. This contract does not grant a job or actor release/merge/physical-APPLY authority.

## Source-first, actual systems first

1. Read pinned upstream `truenas/middleware`, `truenas/apps` (including templates, schema, renderer, migrations, middleware Apps CRUD/upgrade/rollback) and the exact Foundry/Agent Dispatch producer/consumer source. Prefer actual release/source interfaces, not presumed common semantics.
2. Pure-parser/receipt/path/authorization component checks are **cheap refusal checks**, never proof of installation, native Apps lifecycle, catalog semantics or physical compatibility.
3. Deploy a **real TrueNAS ISO with verified identity** into disposable QEMU/KVM on public GHA. Call its real middleware methods. Assert independent runtime, app state, config, storage, network, upgrade/redeploy, product health and cleanup oracles. A green outer workflow is insufficient.
4. Reuse an installed guest for multiple **predeclared** independent capsules only after their individual baseline, namespace, port, dataset, memory/time admission, cleanup and post-capsule platform health barriers are proven; contamination aborts later mutating capsules.
5. Differentiate Foundry Custom App materialization parity and actual upstream native-catalog semantics. TrueNAS Custom App image upgrade does **not** prove versioned native catalog values/schema/migration/snapshot/rollback. Where possible, qualify catalog staging solely in a disposable guest with genuine middleware; never mutate a production catalog or claim an untested semantic equivalence.
6. Reuse accepted historical product/target receipts only at their **unchanged exact source/profile/artifact/oracle identity**; do not copy receipts between applications or release profiles.

## Smallest vertical implementation order

- **WP0: correct source defects / authority convergence.** Read latest HEADs. Correct private Foundry #310 comparator unsafe output-on-error defect; obtain independent exact-head source validation. Promote the existing accepted product matrix/validator from the divergent integration branch into public Foundry main via a reconciled PR, preserving all 8 accepted GARM/FolioRelay cells and OPEN states. Refuse silent omissions of candidates.
- **WP1: actual single-capsule equivalence.** Reuse existing `truenas_single_capsule_adapter.py`, `truenas_session_runner.py` and `truenas_existing_probe_capsule_executor.py`. One admitted exact-control run on the disposable real TrueNAS system; verify complete inner receipt plus zero residue. A synthetic component test is not acceptance.
- **WP2: actual two-capsule session.** Drive the existing session runner through two independent real app probes in one installed guest; no dependencies by default. Prove between-capsule isolation, post-cleanup native app/volume absence, platform health, session contamination stop, independently distinct retained receipts. Only one heavyweight job/session across all consumers.
- **WP3: generic Foundry lifecycle vertical slice.** Use app-agnostic observe/plan/apply/verify/reconcile; never invent per-product CREATE/UPDATE/DELETE scripts. Prove real create, configuration update, stop/start/redeploy, repeat NOOP, remove/reinstall on disposable TrueNAS. Observe after ambiguous mutating responses, never blind retry. No physical FolioRelay APPLY; its #291 capsule remains PREPARED/HOLD.
- **WP4: Foundry-born app.** Bootstrap a minimal real service from Foundry-owned source that is **absent from the pinned official catalog**. Include persistence plus an application-level semantic oracle. No hollow container-only PASS. Prove source/schema render independently of runtime realization.
- **WP5: native control and F6.** A representative real upstream catalog control exercises native installation and where available actual version transition/rollback semantics. Separate `UPGRADE_NOT_OFFERED` observations from positive upgrade coverage. Export Foundry candidate in official catalog-compatible source layout and run pinned upstream validation; never automatically publish.
- **WP6: exact target rollout.** After one complete vertical slice on 26.0.0-BETA.3, qualify the intended other exact targets 25.10.7, 25.04.2.6, 25.04.1. Product rows must declare support/exclusion rather than inheriting unrelated qualifications; any declared supported target missing F0-F5 is OPEN.
- **WP7: DLE/autonomy loop.** Missing exact proof -> bounded actor/provider admission -> typed public-safe run request -> one heavy GHA execution -> exact receipt reduction -> owning authority reconciliation -> next READY node. Distinct actors can implement/validate via authorized repo contexts (e.g. Jules) without requiring private GHA minutes. This is not a new scheduler/database. Wake mechanisms must be independently proven to execute and drain tasks unattended.

## Falsification/stop conditions

Fail closed on input/output evidence-tree overlap or symlinks, source/profile/hash drift, unowned application namespace, unexpected version, stale request replay, unavailable public credits, missing identity-bound immutable artifacts, runner-memory/disk floor, inconclusive oracle, data policy mismatch, incomplete cleanup, or guest contamination. No unsafe retry after partial CREATE/UPDATE/DELETE. Separate `HARNESS_FAILURE`, `ENVIRONMENT_FAILURE`, `ORACLE_FAILURE`, `SESSION_CONTAMINATED`, `NOT_EXECUTED`, and positive product evidence.

Current envelope: a single 8-GiB TrueNAS VM per standard public GHA job, one heavyweight job at a time, 50-minute maximum session contract, sparse disks, no privileged private host or product secrets. Gate source-only work ahead of costly live execution; amortize the expensive boot only with independent cleanup. Job status or Jules review does not confer source acceptance or release authority.

## Primitive decisions from dual-track prior art

- Adopt **Nix-like derivation identity** using Foundry's existing immutable materialization identity, not a Nix build service.
- Adopt **Helm chart-testing's changed-package and version-upgrade oracles**, not Kubernetes or Helm runtime.
- Adopt **OLM's sparse permitted-upgrade transition graph** to avoid Cartesian-product testing, without an operator manager.
- Adopt **openQA/Kola's one-live-guest ordered test modules** and **OBS's source-by-target evidence separation**, without their orchestration infrastructure.
- Adopt product-shipped application oracles, dependency-directed invalidation and source-bound portable receipts.
- Reject a simulator, broad mocking as runtime proof, second persistent catalog server/database, per-product installer, new CI workflow generator, or uncontrolled parallel heavyweight runs.

## Acceptance / promotion

A fully qualified Foundry product requires exact target T0-T5 substrate and a product-owned F0-F5 run with true application semantic oracle and zero unintended residue. Catalog-ready additionally requires F6 source/catalog checks and actual version-transition or documented non-applicability/recovery limits. Physical support needs separate explicit local HIL qualification. No merge, production APPLY, automatic release or catalog submission is inferred. Every failure must leave a cold-startable durable issue/receipt handoff.
