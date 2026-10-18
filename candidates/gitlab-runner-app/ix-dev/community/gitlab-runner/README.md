# GitLab Runner for TrueNAS — Foundry source seed

This is an **unregistered and disarmed native TrueNAS Apps source candidate**, not a production GitLab runner or a qualified TrueNAS Fleeting deployment.

It follows the upstream TrueNAS source layout (`app.yaml`, `questions.yaml`, `ix_values.yaml`, `templates/docker-compose.yaml`). Foundry owns source rendering, normalized Compose IR, immutable deployment artifacts, version/ownership-bound observe → plan → apply → verify, upgrade/rollback and full lifecycle evidence. Installation through Foundry remains an explicitly identified **native Custom App**, not an official-catalog install.

The candidate starts with an immutable-image-shaped stock GitLab Runner manager and a create-if-absent persistent `config.toml` seed. It provisions **no runner, token, project, virtual machine, TrueNAS API authority, Docker socket or host mount**. The pinned GitLab Runner **19.5.0** image has been independently pulled as linux/amd64 and both offline `--version` and `fleeting --help` passed in public GHA (run 39136278207). Source rendering passed in Foundry public CI. Full manager service/persistence and disposable TrueNAS lifecycle are **not** qualified; the current source seed remains not deployable.

Future opt-in Fleeting/Taskscaler integration requires a separately qualified `fleeting-plugin-truenas` Go plugin. GitLab owns job/capacity scheduling; Fleeting owns instance requests; a provider-neutral, API-only TrueNAS runtime adapter owns bounded worker realization, positive-ownership reconciliation and verified cleanup. Apps first; Containers and VMs remain independently gated. Persistent manager app lifecycle remains with Foundry, **not** with the job scheduler.

## Constraints and next gates

- The committed catalog form does **not** collect or store GitLab runner registration tokens or TrueNAS credentials.
- No workers can execute jobs before a deliberately configured and qualified registration/runner profile.
- The default capacity is one and cannot be widened through this question schema.
- No unvalidated direct Docker, Incus/libvirt, or host-level API access.
- `tools/validate_gitlab_runner_catalog_seed.py` validates a bounded **source-shape** contract only; it does not claim successful upstream rendering, OCI pull, runtime health, HIL, CI execution, or official catalog acceptance.
- Before enabling anything: build/pin integrated runner+Fleeting OCI image, validate exact GitLab SDK plugin contract, source-render against the pinned TrueNAS Apps/iX library, qualify manager seed/permissions/lifecycle through Foundry, then run a separately authorized capacity-one GitLab job and zero-residue oracle.

Upstream [TrueNAS catalog inclusion policy](https://github.com/truenas/apps/blob/master/CONTRIBUTIONS.md#apps-catalog-inclusion-policy) excludes host-management API use. **TrueNAS official source format and actual upstream catalog acceptance are distinct.** The latter is not a blocker to Foundry-managed lifecycle qualification; do not claim approval or bypass the policy.

Authority: [Foundry private #331](https://github.com/SemperSupra/truenas-app-foundry-private/issues/331).
