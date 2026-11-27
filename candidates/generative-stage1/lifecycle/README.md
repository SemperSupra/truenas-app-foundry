# Generative applications: container-first persistence and lifecycle gate

This is a product-specific qualification supplement to [Foundry's existing lifecycle contract](../../../docs/foundry-lifecycle.md), not a new planner, control plane, or target adapter. Runtime qualification precedes real app packaging. Existing inert iX source probes test the renderer only.

## State ownership

- Immutable runtime: source revision, OS/dependencies, frontend, tools, plugins/custom nodes and entrypoint pinned in the image or independently verified immutable artifacts. No self-update, unreviewed extension installation, or model acquisition on normal boot. Prefer a read-only root, fixed non-root identity, explicit mounts and bounded tmpfs. Any exception requires observed justification.
- User-owned durable files: projects/workflows, user preferences and settings, uploads/input, outputs, application database and necessary configuration. Give these independent storage identities, stable paths, UID/GID and documented backup/restore. They must outlive removal/recreation/reinstallation of the runtime. Do not store user files only in the container layer. Preserve even when target or package changes.
- Models: separately managed persistent immutable/digest-addressed catalog where possible; mount read-only for inference and use a separately admitted acquisition/update process. Do not duplicate weights for every runtime.
- Disposable state: temp files, regenerable caches, sessions and scratch. Do not require a previous runtime's writable layer to start. Logs/receipts use the existing approved logging/evidence path.
- Secrets: private operator binding and approved secret storage; never public fixtures, image layers, model datasets or general writable configuration.

State formats are product-specific: cross-version compatibility and cross-product portability are not implied. Export standard user-file formats where supported, and explicitly qualify app/database migrations.

## Application-specific discovery frontier

| App | First actual container evidence | Durable contract to prove | Known boundary |
| --- | --- | --- | --- |
| ComfyUI | actual CPU HTTP startup | user directory (workflows/settings/database), input, output; separate model store and disposable temp/previews | pinned source supports explicit directory flags and HTTP user settings/files; test actual writes, read-back and replacement; custom nodes are runtime code, not arbitrary user data |
| SwarmUI | actual .NET frontend installation-page boot | discover effective settings, presets, accounts/database and output/model paths; separate backend lifecycle from UI | first-run installer and backend downloads are not normal boot; actual configured state and restart/replace still unknown |
| InvokeAI | public source pinned, actual CPU build pending | discover root directory, database/model registry/config, uploads and outputs and migrations | upstream CPU build option exists; never let startup install arbitrary models |
| ACE-Step | public source pinned, actual no-model CPU startup pending | discover configuration, checkpoints, audio inputs/outputs, user settings and initialization | upstream default CUDA image and auto-init/model download are not qualified; separate acquisition/bootstrap |

Do not freeze a production mount layout based on a guessed upstream path, a placeholder image or the previous two-volume render probe.

## Lifecycle acceptance: use the existing F0-F5 planner/recipe

Each operation runs observe/discover -> plan -> apply -> verify. The generic Foundry recipe and private supported-API adapters remain the authorities. Application-specific state checks are additional evidence, not an alternative executor.

1. Observe exact source, target release/profile, runtime identity, storage identity/ownership, health, writable-path census, schema/migration version and capacity. Unknown/foreign/ambiguous states fail closed.
2. Plan exact immutable image and runtime spec, separately owned retained storage, initial seed or migration, bounded effects, rollback/restore point and verification. Reject unapproved/stale plans and destructive data operations. No-op when existing state matches.
3. Apply only admitted effects. Initialize empty stores once; never overwrite an initialized/partial store. Quiesce writers before application-consistent snapshot/backup/migration. Start on existing durable storage with a new runtime. Never implicitly delete datasets or rewrite permissions recursively.
4. Verify exact runtime/image/config/storage binding, actual application health, state through application API, preservation of files and config, no-op on replan, controlled stop/start and replacement. Test interrupted/failed initialization, restore from a snapshot/clone, rollback to compatible prior image and state, and reinstallation with retained data. If the database migrated incompatibly, restore a compatible snapshot/clone; an old image alone is not a rollback.
5. Derive real iX source from qualified container+state contract; render with the pinned iX library, test target lowering, then execute the existing F0-F5 procedure against the exact target using supported APIs. Runtime deletion must not delete durable user stores. Use separately owned TrueNAS datasets/volumes where target qualification proves persistence independent of app deletion; do not assume app-managed ixVolumes survive reinstall. Site paths, credentials and live user data stay private.

Reproducible means pin source, base image digest, dependency locks and configuration; retain build provenance, license/SBOM and artifacts. Repeatable means rerun clean-room build/boot and state checks with identical inputs. Reversible requires proven state-preserving restoration, not just a revert command. Idempotent means desired-state no-op and create-once initialization, and operation tokens/reconciliation for event-like actions as defined by the existing planner.

## First executable probe

The public ComfyUI CPU job reuses its actual built image to run
`python3 candidates/generative-stage1/lifecycle/qualify_comfyui_state.py --image foundry-comfyui-upstream-cpu:probe`.
It uses uniquely labeled synthetic Docker volumes, no runtime external networking, no models, non-root read-only runtime, application HTTP settings/user-file writes, synthetic input/output retention checks, create/read-back/NOOP/replacement and scratch-loss checks. The helper seeds ownership only on newly created empty fixture volumes. It removes only its owned synthetic volumes on teardown. This is same-image replacement evidence, not cross-version migration, ZFS snapshot/restore or native TrueNAS lifecycle qualification. An unsuccessful run stays RED. Public CI does not establish promotion authority.
