# Foundry Catalog App — MVP implementation, deployment and qualification plan

Status: **APPROVED ARCHITECTURE; IMPLEMENTATION IN PROGRESS; NO PHYSICAL DEPLOYMENT AUTHORIZED** (2026-10-14)

Authority: [Foundry private #328](https://github.com/SemperSupra/truenas-app-foundry-private/issues/328). Existing shared authorities: private #274 (inventory), #267 (profiles), #290 (generic lifecycle), #291 (physical HOLD), #281 (native catalog), and Agent Dispatch private #396/#480 (disposable real TrueNAS).

## Goal and boundaries

Ship a standalone, recoverable TrueNAS SCALE Custom App called **Foundry Catalog**, offering one authenticated Web UI and one typed API/CLI/agent contract for discovering official TrueNAS, Foundry and explicitly registered compatible third-party catalogs; showing source/version/qualification; planning changes; and controlling *authorized owned* installs through existing generic Foundry lifecycle adapters. Bootstrapping cannot require Foundry, our personal IaC repository, host modification or an experimental middleware patch.

**Not the MVP:** native third-party catalog injection, Helm/TrueCharts conversion, full catalog format support, arbitrary user-script execution, automatic adoption of native apps, fleet scheduler/reconciler, always-on third-party polling, custom Docker socket orchestrator, resident database, auto-source trust, unattended physical mutation.

**Custody:**
- Product implementation and release belong to a dedicated product-owned repository under SemperSupra (name established before creating installable assets). This public Foundry repo owns the reusable federation/identity contracts, source materialization, target profiles and reusable test controls; private Foundry owns sensitive deployment adapters/qualification. A prototype in Foundry does not silently become production product code.
- IaC owns only site desired-state bindings, target and secret references; it calls Foundry's existing generic operator and NEVER reimplements lifecycle.
- Agent Dispatch owns disposable TrueNAS capacity/guest provisioning and sanitized execution receipts; Foundry owns exact-product qualification verdicts.
- Official native installs remain native-owned. Foundry/custom installs have separately established ownership. Unmanaged installs start read-only. No second writer for an IaC-managed instance.

## Critical path to MVP (hard dependencies)

| ID | Critical-path deliverable | Inputs and concrete implementation | Exit/gate |
| --- | --- | --- | --- |
| CP0 | Reconcile authority and risk | Existing #328 + #274/#290, select existing generic interfaces; adopt threat-test inventory in this plan | Zero duplicate lifecycle/backend or conflicting owner |
| CP1 | Minimal federated read model | Add strict provider/source/commit/manifest identity parser; preserve same app across publishers; consume native TrueNAS catalog and Foundry inventory read-only; one explicitly pinned external-compatible source | Deterministic 3-source list/show/resolve; wrong provider, conflict, unsafe URI all refuse; offline unit fixtures |
| CP2 | Unified plan interface | Adapt existing Foundry source-renderer/immutable artifact and generic observe/plan; one typed JSON/OpenAPI contract for clients, no independent mutation logic in UI | Same plan ID and source/profile/authority identity from API/CLI; no write credentials needed for discovery or PLAN |
| CP3 | Standalone product artifact/bootstrap | Package one TrueNAS Custom App from pinned image digest; native UI/YAML and bounded CLI bootstraps from **stock** TrueNAS; minimal local configuration/secret refs and Web portal | Fresh disposable guest installs/starts app without IaC, Foundry service, catalog-overlay or host root; stop/restart/offline bootstrap recovery |
| CP4 | Gated owned lifecycle | Reuse private generic observe→plan→apply→verify; official-catalog mode remains native; Foundry/custom mode uses Custom App materializer; no foreign adoption; retained-data default | One owned probe: CREATE→VERIFY→NOOP→UPDATE→START/STOP→DELETE retain-data; ambiguity reconciles before retry; operator intent + scope verified |
| CP5 | User/agent surfaces | Thin responsive browser UI (discovery, source qualifier, values, plan, confirmation, jobs) over same typed API; CLI wrapper uses identical operations | Human/API/CLI/agent produce same canonical intent and receipt; browser cannot pass raw shell/Compose/Docker socket; auth/CSRF and replay checks |
| CP6 | Exact-target qualification and release | Start cheap offline differential controls; select one admitted disposable TrueNAS exact version (25.04.2.6 presently apply-qualified), then other versions **independently** via #267/#282, never inherit | F0-F5 and product bootstrap/withdrawal/collision/recovery security oracles PASS for declared release envelope; signed/pinned artifact, reproducible docs, DLE evidence |

**Critical chain:** CP0 → CP1 → CP2 → CP3 → CP4 → CP5 → CP6. CP5's UI design and CP3 packaging proof may run in parallel with CP1–CP2, but acceptance cannot claim install/management without CP4; CP6 requires the built artifact and the exact-target adapter. An isolated native-catalog redirection study is **off critical path**.

## Independent parallel lanes (budgeted)

- P-A: Source seam survey for exact TrueNAS middleware versions. Test official catalog sync/cache/update and native UI discoverability *only in disposable guests*. Outcome may remain negative without blocking MVP.
- P-B: Red-team adversarial manifest/collision/withdrawal/authority fixtures. Offline in public GHA; no GHA heavyweight VM needed.
- P-C: One minimal product UI style/API mock with static fixtures. No false claim of functioning lifecycle until CP4.
- P-D: Agent Dispatch capacity/admission for one disposable real TrueNAS guest per heavy run, reuse same guest only across isolated receipts; avoid launching all exact versions simultaneously.

## Deployment modes and rollout

1. **Disposable RDTE:** Agent Dispatch launches a pinned TrueNAS VM; stock native Apps configured; apply pinned Custom App bootstrap; perform read-only catalog registration and fake/mocked discovery; enable scoped actuator only for owned test instance; collect sanitized evidence; remove and independently verify guest/volumes/residue. This is the first permitted mutation target.
2. **Standalone installation:** Operator obtains published pinned bootstrap artifact and source/attestation, installs through supported TrueNAS Custom App GUI/YAML, configures credential/endpoint separately and locally; read-only by default; opt-in scoped operations after exact-version capability verification. No account on our private GitHub/IaC required.
3. **IaC-managed installation:** IaC declares image digest/version, target, ports, datasets, source allowlist and site binding/secret *references*, then delegates to the canonical generic Foundry operator. IaC does not create its own App installer. Installed app's UI cannot independently mutate IaC-managed application state.
4. **Physical promotion:** separate authority and source/profile/product verification, second identical read-only READY plan, explicit bounded mutation approval and budget, single attempt, read-back verify and re-plan NOOP. Existing FolioRelay HOLD and other site restrictions remain unchanged.

Controller update: stage a previous+candidate immutable artifact; an **external** bounded operator updates/replaces controller and proves health; preserve independent restoration from last-known-good pinned artifact. The running catalog must never depend on its own HTTP server being healthy to perform emergency recovery.

## MVP acceptance test inventory (red-team and blue-team)

- Same app/train/version in official/Foundry/external: show all choices independently, no source overwrite or cross-provider upgrade.
- Same provider/package/version but different digest/revision: explicit immutable identity distinction or reject conflicting duplicate; never last-wins.
- Malformed/traversing manifest path, credential-bearing catalog URI, unsupported scheme, mutable source ref, untrusted template/privileged mount: block before apply.
- Catalog withdrawn/revoked/unreachable: existing install retains execution/data; new install blocked according to policy; last-known-good source/artifact identity remains inspectable.
- Native official installation: observe read-only, preserve native source/trains; do not pretend that Custom App conversion provides native upgrade equivalence.
- Human/agent/IaC simultaneous intent: one authoritative writer, plan precondition and fresh read-back; stale plan BLOCKED, not silently retried.
- Stop, start, upgrade/update, delete/reinstall, data retention, portal, auth, job failure, token replay, self-update failure, read-only boot, recovery on exact TrueNAS release.
- Generated evidence excludes secrets, private hostnames, real personal files and raw privileged Compose; negative-path tests include unauthorized operator.
- One small active target first: accepted exact-version profile required before any mutation; do not infer version support from build/render alone.

## Red-team stop conditions and residuals

P0 stop: authority collision, source identity ambiguity, unsafe materializer feature accepted silently, mutable/unpinned install artifact, controller irrecoverability, or physical write from read-only. P1 stop for public MVP claims: target-runtime mismatch, missing data-retention proof, unauthorized Web/API operation or unusable CLI/agent receipt. Native overlay parity, non-TrueNAS portability, and advanced application conversions are tracked later, not hidden MVP gates.

## Post-MVP roadmap: only promote against consumer evidence

| Horizon | Candidate feature | Promotion evidence |
| --- | --- | --- |
| R1 | Third-party catalog connectors, Git/OCI/local import, search/filter, diff and manifest localization | Two genuinely different publishers + adverse/conflict cases, bounded resource use |
| R1 | Offline catalog snapshot, source withdrawal/revocation UX and exportable install receipts | Disconnect/recovery drill from stock TrueNAS |
| R1 | Accessibility, configuration form parity, UI localization (including Thai/German), App portal polish | Human/CLI/API fixture equivalence and usability findings |
| R2 | Native-source catalog provider/injection adapter | Repeatable exact-version sync/upgrade/uninstall native oracle; reversible and no unapproved host patch |
| R2 | Explicit source-adoption/migration workflow and backup-aware cross-source transition | Independent migration + data/UID/schema rollback oracle |
| R2 | Catalog publication/update provenance: TUF/Sigstore/OCI signatures, policy profiles | Proven update-threat model and operational recovery/test fixtures; avoid trust ceremonies without a threat |
| R3 | Multi-node fleet view and delegated multi-tenant roles | Independent multi-site consumer; clear identity/auth boundaries |
| R3 | Native middleware/WebUI extension contribution upstream | Upstream-accepted hook with versioned compatibility; no fork maintenance debt |
| R3 | Other runtimes (Compose, Podman, Quadlet etc.), Helm conversion | Independent source/IR/lifecycle adapter and target-specific HIL qualification |

**No speculative dates.** Gate progression is evidence-based; a post-MVP feature must demonstrably improve a consumer workflow or prevent a measured defect.

## Session handoff and execution policy

- Read the authoritative #328 issue, its latest comments, this plan and the threat fixture/tests. Reconcile new PRs, current public/private Foundry HEAD and Agent Dispatch capacity before assigning code.
- Execute CP1 offline first. Put generic source-trust/identity contracts + tests in public Foundry; product-only Web UI and packaging in the product repository when product repo is established; private TrueNAS actuation only in Foundry private.
- Do not use local actors while exhausted; use GitHub-hosted CPU tests and disposable RDTE only when admitted. No physical mutation and no new credential request solely for planning.
- After any attempt publish exact commits, checks, receipts and next critical blocker in #328. Never claim product qualification from a documentation PR or mock.

## Executed implementation slices and upstream dependency reconciliation — 2026-10-14

1. **Federation/query/read-only contract — public Foundry PR #137:** `tools/foundry_catalog_federation.py` validates pinned provider-scoped source-tree identities, excludes duplicate keys and conflicting releases, enforces bounded offline ingestion, preserves independent publishers, and implements `list`/`show`/`resolve` as pure read-only queries. `schemas/foundry-catalog-read-api-v0.openapi.json` describes an **unimplemented HTTP adapter contract** for the exact query results. No API server exists yet; zero mutation or trust authorization can be inferred from this contract.
2. **Canonical Foundry inventory projection — public Foundry PR #138:** Real `foundry_app_inventory.validate_inventory` and `bootstrap_candidate` from *existing unpublished* PR #82 are consumed directly. Exporter selects one SHA-pinned repository and source-tree digest, preserving real repository-relative path `fixtures/foundry-rdte-probe`, without making a second inventory. Tests prove conversion from the existing real probe fixture and remain read-only.
3. **Merge/dependency order:** PR #82's `prep/foundry-born-catalog-probe-integrated-274` is **stacked on** `prep/foundry-catalog-render-install-v2-274`, while PR #126 provides an additional exact-target correction stacked on #82. PR #138 targets #82's branch. PR #137 targets main independently. Reconcile and qualify those authoritative branches; never blindly merge #82's large inherited source-library change or copy it into #137 just to make imports pass. Cross-contract integration (and three-provider real data adapters) waits for a compatible accepted merge base. This is a dependency, not permission to duplicate inventory.
4. **Current acceptance boundary:** CP1 query and Foundry inventory export primitives have focused CPU-only PR checks; still missing are an independently source-verified official catalog adapter, one pinned external-compatible adapter, combined three-source integration and product runtime. CP2's read API **schema only** exists; an authenticated running service and connection to existing planner/executor remain unimplemented.
5. **Safety/readiness:** Physical target mutation is HOLD under #291. The red-team authority #329 must independently review source URL/provider impersonation and future source fetching. A validated index remains `DISCOVERED_ONLY`; it is not catalog qualification, trust admission, ownership, or `apply` authorization.

## Continuation milestone — source-derived three-provider read path and reference HTTP seam (2026-10-14)

- **Integration public PR #139** is deliberately stacked on #138/#82, not merged into main. An official TrueNAS source adapter reuses our pinned `truenas/apps` Git SHA and existing structural source-tree validator. A registered external-compatible catalog adapter reads the archived public `codefuturist/truenas-apps` fork at an exact SHA, verifies its Git remote/revision and source tree, then produces discovery-only records. The first combined real-source CI includes official Jellyfin, third-party Jellyfin and the local Foundry probe, proving publisher identity and collision isolation with zero mutation. Source-derived success is **not** live TrueNAS native Discover, installation or upgrade evidence.
- **Reference read API public PR #140** is stacked on #139 and implements an in-process, bearer-gated, loopback-only HTTP reference adapter for the existing GET `list/show/resolve` query contract, with live HTTP method-rejection and credential-file permission tests. The reference adapter is generic public-safe functionality, **not** a packaged standalone TrueNAS application or production access-control/TLS solution. Last verified exact-head `4efc55a2d0069bd4a4a0b7fcbb4eec8c7e091825` passed five GHA workflows, including public security validation.
- Keep CP1 **offline/source-derived COMPLETE for the scoped 3-source proof**, but **live native catalog adapter and real TrueNAS runtime remain OPEN**. CP2 has read-only API functionality but not authenticated product packaging or read-only planner integration. CP3–CP6 are OPEN. The model must not treat an archived external fork as trusted/apply-qualified or infer installed-app ownership from matching names.
- The product-owned standalone application repository has not been created in this execution; the available GitHub connector does not expose repository creation. It should not be silently substituted by embedding a second controller within this public framework repo or IaC. Continue with existing shared primitives/CI/DLE until repo provisioning is available or an authorized existing product repository is selected.
- Maintain exact stacked dependency graph: #82 (canonical inventory) → #138 (projection) → #139 (source-derived integration) → #140 (reference API), with #126 exact-target correction stacked on #82; #137 independent generic federation/read API contract. Reconcile before any merge, require independent adversarial review #329 and the exact-head CI gates. Physical #291 mutation HOLD remains unchanged.
