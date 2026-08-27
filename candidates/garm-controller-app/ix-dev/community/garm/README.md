# GARM for TrueNAS

This source candidate packages the SemperSupra-qualified GARM appliance as a persistent TrueNAS SCALE App.

The controller image is pinned by digest. `/etc/garm` is a TrueNAS-managed ixVolume. A network-disabled helper using the same pinned image seeds `config.toml` only when it is absent; an existing non-empty config is preserved and an existing empty config is treated as an error.

The two bootstrap secrets are TrueNAS `private` questions because GARM requires them before first startup. `private` masks values in the UI; it is not a zero-residue secret-storage claim. After first boot, add GitHub credentials and external-provider configuration through GARM rather than duplicating them in App values.

The pinned runtime currently defaults to root inside the container. This candidate makes that explicit while relying on the TrueNAS 2.3.4 library defaults of `cap_drop: ALL` and `no-new-privileges=true`, with no host-path mounts, privileged mode, or container-runtime socket. Non-root operation is a separate qualification task.

After the App reaches a healthy state, initialize the controller/admin identity with the upstream `garm-cli init` workflow. Real TrueNAS lifecycle, persistence, provider connectivity, and runner creation remain HIL claims and require separately authorized site evidence.
