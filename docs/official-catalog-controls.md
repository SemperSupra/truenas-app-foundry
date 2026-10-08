# Official-catalog control discovery

Authority: `SemperSupra/truenas-app-foundry-private#281`.

This surface selects and source-binds official TrueNAS catalog applications that may
serve as **native-catalog** controls for the cross-version Foundry lifecycle matrix.

It is intentionally upstream of runtime qualification. Passing this source gate does
not mean an application works on any TrueNAS target.

## Exact catalog source

The manifest pins one immutable `truenas/apps` commit and the Git blob identity of
each selected app's `app.yaml`. CI re-fetches that exact catalog commit and verifies
the blobs before accepting the source contract.

The target envelope comes from `.foundry/truenas-target-tracks.json`; it is not copied
from train names. When a new exact target is admitted, every universal candidate becomes
invalid until its declared matrix is extended.

## Control roles

- **ntfy** — primary universal candidate. Current catalog metadata uses app library
  2.3.4 and declares no host mounts. It is the first runtime candidate because it keeps
  the lifecycle oracle low-coupling.
- **element-web** — secondary universal candidate/discriminator. It also uses library
  2.3.4 and declares no host mounts.
- **forgejo-runner** — specialized runner control, not the generic lifecycle oracle.
  Its current catalog metadata uses a newer library and mounts
  `/var/run/docker.sock`. That coupling is useful for runner-specific qualification
  but should not be required to prove generic catalog lifecycle behavior.

These are role selections, not compatibility verdicts. In particular, ntfy and
element-web remain only **candidates** until native catalog install/lifecycle receipts
exist for every exact target.

## Fail-closed invariants

For a universal candidate:

1. declared target coverage must exactly equal the target registry;
2. native catalog semantics are mandatory;
3. Custom App substitution is prohibited;
4. runtime-qualified targets must be a subset of declared targets;
5. `universal_qualified=true` is legal only when every exact target is runtime
   qualified.

This prevents a green source check, a single successful target, or a Custom App
fallback from being mistaken for universal official-catalog support.

## Next runtime step

After system T0-T5 is accepted for an exact target, the disposable TrueNAS consumer
must exercise the selected app through native catalog semantics:

`absent -> install -> verify -> stop/start -> config update/read-back -> applicable native upgrade -> redeploy -> NOOP -> retain-data delete -> absence -> reinstall -> verify -> NOOP`

The existing public profile/lifecycle planner supplies target/profile identity and
postcondition semantics. The runtime consumer must preserve the exact catalog commit,
app identity/version, profile fingerprint, and classified receipts for each matrix row.
