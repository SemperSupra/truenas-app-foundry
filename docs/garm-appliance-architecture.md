# GARM appliance for TrueNAS — public architecture

## Decision

The TrueNAS package is a **general GARM appliance running on TrueNAS**. It is not a controller restricted to TrueNAS-hosted runner backends.

Packaging GARM as a TrueNAS App must preserve stock GARM capabilities unless an exact compatibility or security reason is documented. The SemperSupra TrueNAS provider is additive.

The governing invariant is:

> Do not break a stock GARM capability merely because GARM is packaged as a TrueNAS App.

## Product boundary

```text
TrueNAS SCALE
└── GARM appliance
    ├── pinned upstream GARM controller / API / WebUI
    ├── pinned upstream external-provider bundle
    │   ├── AWS
    │   ├── Azure
    │   ├── GCP
    │   ├── OCI
    │   ├── OpenStack
    │   ├── LXD / Incus
    │   ├── Kubernetes
    │   └── other providers present in the pinned upstream distribution
    ├── additive SemperSupra provider
    │   └── garm-provider-truenas
    │       ├── Apps backend          current MVP backend
    │       ├── Containers backend    future
    │       └── VM backend            future
    └── persistent GARM/provider configuration and credential state
```

A user may therefore run the GARM controller on TrueNAS while provisioning runners:

- only on TrueNAS;
- only on a remote/cloud provider;
- across several upstream providers;
- across upstream providers and TrueNAS simultaneously.

The TrueNAS App is the controller deployment target. It does not determine the runner runtime target.

## Upstream provider preservation

Current upstream GARM documents external providers as local executables and states that its Docker image includes pre-built provider binaries under `/opt/garm/providers.d/`. GARM supports multiple configured providers, with each pool tied to one provider.

The appliance packaging contract is therefore:

1. pin an exact upstream GARM source/image/build identity;
2. inventory the upstream provider bundle at that identity;
3. preserve that bundle by default;
4. reproducibly add `/opt/garm/providers.d/garm-provider-truenas`;
5. record any upstream-provider exclusion as an explicit compatibility/security exception;
6. never substitute the TrueNAS provider for an unrelated upstream provider.

Bundling a provider does not authorize or configure it. Provider use remains opt-in.

## Provider isolation

Provider credentials and provider-specific configuration are separate concerns.

The appliance should provide persistent provider configuration storage while preserving process-level credential isolation as far as upstream GARM permits. Environment-variable passthrough must remain explicit and provider-scoped.

The presence of an upstream local provider such as LXD/Incus must **not** automatically grant the GARM App access to TrueNAS host Docker, Incus, libvirt, device, or other privileged sockets. A remote provider can remain usable without weakening the controller sandbox.

The SemperSupra TrueNAS backends use supported TrueNAS middleware APIs. They do not require direct host Docker/Incus/libvirt control.

## TrueNAS provider model

One `garm-provider-truenas` executable may be configured in GARM multiple times with backend-specific configuration files and provider names, for example:

```text
truenas-apps        -> current Apps backend
truenas-containers  -> future Containers backend
truenas-vms         -> future VM backend
```

Each provider definition may have independent pools or scale sets, limits, priorities, flavors, timeouts, and credentials while sharing common provider code.

Support for a future backend is not implied merely because the configuration model reserves a provider name for it.

## GitHub scheduling model

GARM supports two GitHub scheduling models:

- **Runner Scale Sets** — GitHub message-queue / HTTP long-poll delivery;
- **Pools** — `workflow_job` webhook-driven delivery.

For GitHub.com, Runner Scale Sets are the preferred default when the GitHub endpoint/entity supports them.

Reasons:

- no inbound workflow-job webhook is required;
- queued requests survive GARM/controller restarts better than transient webhook delivery;
- GitHub performs scale-set scheduling;
- runner-group semantics are supported directly by the scale-set model.

Pools remain a supported GARM capability. They are appropriate for Gitea, existing webhook deployments, and cases where GARM pool labels/balancing semantics are deliberately required.

The appliance must not remove the GARM webhook/pool path merely because Scale Sets are preferred.

## Repository, organization, and enterprise entities

GARM models an endpoint, credential, and entity hierarchy. Pools and Scale Sets are associated with repository, organization, or enterprise entities.

One GARM appliance may therefore hold multiple authorized credentials/entities, including credentials for multiple independent GitHub organizations.

The security boundary is explicit:

```text
credential / installation A -> organization A -> its pools / scale sets
credential / installation B -> organization B -> its pools / scale sets
```

Independent organizations are not implicitly trusted or merged. Cross-organization runner sharing is only an enterprise-level capability when an actual GitHub enterprise boundary supplies it.

The preferred authentication model for organization/repository use is a GitHub App where practical, while preserving other credential modes that upstream GARM supports.

## GitHub Free baseline

The appliance must have a useful baseline on GitHub Free without depending on paid GitHub-hosted compute.

Current GitHub billing documentation states that GitHub Actions execution on self-hosted runners is free; users pay for the infrastructure they operate. GARM-provisioned runners are self-hosted runners from GitHub's perspective.

Runner-group documentation has had plan-surface differences across GitHub documentation views. Therefore the product contract does **not** require custom runner-group creation as an installation prerequisite.

Required baseline:

- self-hosted GARM runner operation;
- repository or organization entity as authorized by the account;
- Default runner group where custom groups are unavailable or unverified;
- one scale set per independently authorized GitHub entity where Scale Sets are used.

Optional capability after detection/qualification:

- additional/custom runner groups;
- selected-repository/workflow policies;
- enterprise-level runner-group sharing;
- other plan-specific controls.

Plan-dependent controls must fail closed or degrade to the documented baseline. They must not silently block installation.

## Persistent and ephemeral state

The controller appliance is persistent. Runner instances are disposable.

Persistent controller state includes, as required by pinned GARM:

- controller configuration;
- GARM database/state;
- provider definitions and provider configuration;
- GitHub endpoint/entity/credential configuration;
- provider secrets that GARM itself requires durably and protects appropriately.

Ephemeral runner state belongs to the selected runner provider/runtime and must not be retained by the controller merely for convenience.

The TrueNAS Apps runner backend continues to treat the JIT runner workload as a one-job disposable Custom App.

## Qualification dimensions

The appliance and provider backends are qualified independently.

Controller-appliance qualification should prove at least:

1. pinned GARM starts and persists controller state on TrueNAS;
2. the upstream provider bundle is present at the recorded identity;
3. adding the TrueNAS provider does not shadow or remove upstream providers;
4. GARM can operate with no TrueNAS provider enabled;
5. at least one stock upstream provider can be configured from the packaged controller without controller-image modification;
6. Runner Scale Set mode functions without an inbound webhook;
7. Pool/webhook mode remains compatible;
8. multiple credentials/entities do not cross-contaminate configuration or secrets;
9. the GitHub Free + Default runner-group baseline works without paid-only assumptions.

Runner-backend qualification is separate:

- TrueNAS Apps — current Stage 5 HIL path;
- TrueNAS Containers — future release-specific backend/profile;
- TrueNAS VMs — future release-specific backend/profile;
- upstream providers — their own provider/runtime qualification; packaging tests only prove the appliance preserved access to them.

A controller packaging PASS is not a PASS for every bundled provider.

## Non-goals

The MVP does not:

- fork GARM core merely to add TrueNAS support;
- rewrite upstream external providers;
- require all bundled providers to be configured;
- grant local host sockets to upstream providers automatically;
- create a synthetic enterprise boundary across unrelated organizations;
- require custom runner groups on GitHub Free;
- claim the future TrueNAS Containers or VM backend is implemented;
- replace provider-specific or TrueNAS HIL qualification.

## Upstream references

Architecture should be revalidated against the exact pinned release during candidate qualification. Current design references:

- GARM providers: https://github.com/cloudbase/garm/blob/main/doc/providers.md
- GARM resource hierarchy: https://github.com/cloudbase/garm/blob/main/doc/first-steps.md
- GARM Scale Sets: https://github.com/cloudbase/garm/blob/main/doc/scale-sets.md
- GitHub Actions billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
- GitHub Runner Scale Sets: https://docs.github.com/en/actions/concepts/runners/runner-scale-sets
- GitHub self-hosted runner groups: https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access

These references describe upstream behavior; the exact appliance candidate still requires pinned-source checks and qualification evidence.
