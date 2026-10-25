# LiteLLM gateway-minimal: Score fit-gap

Authority: Foundry #262.

## Decision

Use the current Score workload specification (`score.dev/v1b1`) as the portable workload vocabulary for the MVP. Do not create a SemperSupra workload schema.

Score directly covers the MVP's container image, command/args, variables, files/volumes, CPU/memory, health probes, service ports, and abstract resources.

The gaps are deliberately kept outside the workload contract:

| Concern | Score fit | MVP treatment |
|---|---|---|
| OCI image + command/args | Direct | Score |
| Service port | Direct | Score |
| CPU/memory limits | Direct | Score |
| Liveness/readiness | Direct | Score |
| Config volume | Direct | Score resource + volume |
| Provider secret reference | Resource is representable; secret strength is not standardized | Score resource + target capability policy |
| Minimum secret tier | Not represented | lifecycle/target policy (S1+) |
| Catalog metadata/questions | Target-specific | TrueNAS adapter |
| Upgrade/rollback | Out of workload scope | lifecycle contract |
| Image signature/provenance | Out of workload scope | appliance qualification |
| Real TrueNAS compatibility | Out of workload scope | Agent Dispatch target receipt |

Score explicitly leaves secure handling of sensitive resource outputs to each implementation. For this MVP, a target is unsupported if it cannot project the `provider-secrets` resource at secret tier S1 or stronger.

## Resource conventions used by this workload

These are implementation-local resource classes, not additions to the Score schema:

- `volume/config-directory`: directory containing `proxy_server_config.yaml`.
- `secret/env-files`: directory containing one file per environment variable; filenames are the environment variable names.

The SemperSupra appliance converts the latter into process environment variables immediately before exec. Secret values are never part of the Score file.

## Kill rule

If future portable semantics cannot be expressed without target-specific fields in the Score workload, record the concrete gap before adding any extension. Do not turn Score metadata into a hidden general-purpose deployment language.
