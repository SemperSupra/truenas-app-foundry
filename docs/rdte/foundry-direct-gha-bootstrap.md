# Foundry bootstrap RDTE without Agent Dispatch

Authority: [private Foundry #353](https://github.com/SemperSupra/truenas-app-foundry-private/issues/353), Foundry #274/#290 and private Agent Dispatch #748. This *execution* does not call or run Agent Dispatch, use its API or repository workflow, use a sidecar, or require the deployed TrueNAS control or OCI worker.

## Execution contract

- **Observe:** A direct, PR-triggered public GitHub Actions job on `SemperSupra/truenas-app-foundry` performs one read-only Linux KVM ABI ioctl and bounded memory/CPU/disk capability preflight. It does not create a guest.
- **Package:** Another independent public runner compiles the existing intentionally harmless standalone Go control/worker fixture, runs its unit tests, builds a local scratch Docker image, exports a Docker archive and publishes *only* a 7-day GitHub Actions artifact and SHA256 manifest (not GHCR).
- **Verify:** Check actual run/job logs, head source SHA, artifact ID/bytes when available, container image identity, and evidence JSON. The public synthetic archive proves neither the private product image nor a native TrueNAS guest.
- **Bootstrap:** When the preflight is accepted, a separate narrowly scoped Foundry-owned workflow can use the same direct public GHA runner to fetch a fixed TrueNAS ISO, prove exact image checksum, boot a disposable guest, load this harmless image archive, interact with native middleware and Apps, exercise F0-F5 and teardown. Do **not** claim that future stage is implemented or accepted by this workflow.

## Why it is not a circular dependency

Only GitHub and Foundry source are required to test and reconstitute the Foundry-managed application deployment. Agent Dispatch and WOW Sidecar may later consume the certified workflow, but cannot be required for executing or observing its initial acceptance. No job registration database, callback transport, dispatcher, cross-venue credentials, or persistent agent service is introduced.

**Safety:** no production host, SSH, secrets or private code in public GHA; zero private hosted runner minutes; no QEMU guest yet; no live migration or release. If KVM ABI/CPU/memory/free-disk gate is blocked, retain receipt and do not substitute an unsupported emulator or claim a guest pass. The proof threshold for D2 remains real native TrueNAS Apps F0-F5 and zero residue. Physical private-image HIL and state-preserving cutover remain D3.
