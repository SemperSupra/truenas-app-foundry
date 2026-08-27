# Upstream TrueNAS compatibility profiles

This document records the intended compatibility-profile model for native TrueNAS materialization. The capability is planned work tracked in #5; it is not required to complete the current capacity-one GARM HIL.

## Why profiles are needed

A TrueNAS App source application and a TrueNAS SCALE runtime are governed by more than one version surface. A robust native qualification claim should bind the source-rendering implementation and the runtime-realization implementation separately.

## Public upstream anchors

### `truenas/apps`

Use exact public source identities for:

- App metadata and catalog layout;
- `questions.yaml`/schema behavior;
- shared iX library templates/helpers;
- known-good catalog controls;
- upstream render/CI mechanics.

The current public materialization-control gate already pins an exact `truenas/apps` commit and iX library identity in `.foundry/truenas-apps-upstream.json`.

### `truenas/middleware`

Use exact release-specific source identities for native runtime semantics, including:

- Apps CRUD operations;
- custom-App operations;
- Compose handling/progress;
- ix-volume/storage behavior;
- lifecycle/state handling;
- native runtime realization behavior exposed through middleware APIs.

Prefer release branches/commits over floating `master` for a qualification profile. During the August 2026 terminology review, public branch `release/25.04.1` resolved to `74ab5a2d373be4097dece257d00e1086376333ba`.

That upstream commit is a compatibility anchor, not a substitute for target-host evidence. A deployed host can differ because of patch level/build/release details; HIL must record the actual system version and reconcile it deliberately.

## Proposed profile shape

```yaml
schema_version: 1
source:
  format: truenas-app
  apps_repository: https://github.com/truenas/apps.git
  apps_commit: <sha>
  ix_library_version: <version>
  ix_library_hash: <hash>

ir:
  format: normalized-compose-json
  version: <foundry-version>

runtime_target:
  family: truenas-scale-apps
  version: <reported-version>
  platform: linux-amd64
  middleware_repository: https://github.com/truenas/middleware.git
  middleware_ref: <release-ref>
  middleware_commit: <sha>

lowering:
  adapter: native-truenas
  version: <adapter-version>

qualification:
  evidence_ids: []
  semantic_gaps: []
```

## Compatibility workflow, future

A future public-safe workflow can periodically:

1. resolve/pin candidate `truenas/apps` and release-specific `truenas/middleware` identities;
2. source-render known-good controls;
3. inspect or exercise public middleware/App contracts without private NAS credentials;
4. compare expected source/runtime semantics against the current Foundry IR/adapter contract;
5. emit drift evidence;
6. leave live realization claims to private HIL on the actual target profile.

This creates an early-warning compatibility signal without confusing source compatibility with target-host qualification.

## Licensing boundary

The relevant upstream repositories are public and carry LGPL-3.0 licensing at repository level. Any reuse must still honor file-level notices and separately licensed portions. Foundry should prefer pinning/executing/comparing upstream behavior over copying large implementation bodies.
