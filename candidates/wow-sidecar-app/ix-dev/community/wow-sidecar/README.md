# WOW Sidecar TrueNAS App candidate

This source candidate packages the generic WOW Sidecar worker as a least-privilege TrueNAS App.

It consumes only the immutable public WOW image recorded in `candidate.json`. The App provides:

- fixed runtime UID/GID 10001:10001;
- a TrueNAS permissions helper scoped only to the two managed ixVolumes;
- a network-disabled, non-root create-once configuration seed helper whose container rootfs is writable only because Compose inline-content configs cannot be materialized into a read-only service;
- read-only configuration mount for the worker;
- separate writable state ixVolume;
- read-only long-running worker root filesystem and tmpfs-backed `/tmp`; the one-shot seed helper is the explicit bounded rootfs exception;
- no host paths, host networking, Docker socket, privileged mode, or GARM/root integration.

The GitHub App private key and operator-profile JSON are seed inputs. They are persisted only on first initialization; an initialized or partially initialized configuration is never silently overwritten. TrueNAS private fields reduce UI exposure but are not treated as a zero-residue secret store.

The root-required GARM capacity-two integration remains outside this App and continues through its separately governed compatibility path until a dedicated integration boundary is qualified.

The seed's inline Compose config inputs are mounted mode `0444` because Docker owns inline configs as root and the helper runs as UID 10001. Those inputs exist only inside the network-disabled one-shot seed service; the helper copies them into managed config storage and immediately constrains the persistent private key and operator profile to mode `0400`.
