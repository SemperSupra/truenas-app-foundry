# Drasl for TrueNAS

This source candidate packages upstream Drasl as a native TrueNAS SCALE App source application.

The candidate deliberately keeps the application boundary small:

- the exact upstream Drasl release image is used without rebuilding it;
- Drasl runs as UID/GID 568 after a real-container qualification rep;
- /var/lib/drasl is the only persistent volume and contains the database, generated signing key, skins, capes, and migration backups;
- /etc/drasl/config.toml is rendered from TrueNAS App values as a read-only Compose config;
- password registration is invite-gated by default;
- no host paths, privileged mode, container-runtime socket, or external database are required.

Drasl itself listens on plain HTTP inside the App. For access beyond a controlled RDT&E network, place it behind an HTTPS reverse proxy and set Domain and BaseURL to the externally visible names.

The exact upstream OCI image is minimal and does not provide a qualified in-container HTTP probe utility. The source therefore disables the Compose healthcheck rather than adding a production sidecar solely for probing. Foundry qualification starts the real image and probes the HTTP endpoint externally.

Public Foundry qualification proves source rendering, normalized Compose invariants, exact-image startup, non-root operation, and restart persistence of the generated Drasl signing key. It does not claim live TrueNAS installation, site networking/TLS, upgrade/rollback behavior, or promotion. Those are private HIL gates.
