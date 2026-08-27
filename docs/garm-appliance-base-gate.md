# Pinned GARM appliance-base provider-bundle gate

## Purpose

Before the TrueNAS controller App is built, the Foundry records the exact upstream GARM controller image that serves as the packaging baseline and inventories the provider executables actually shipped inside that image.

This gate enforces one product invariant from `docs/garm-appliance-architecture.md`:

> Packaging GARM on TrueNAS must not silently remove or replace stock GARM capabilities.

The gate is public-safe and uses only GitHub-hosted infrastructure. It does not access a NAS, private repository, GitHub organization credential, provider credential, or runner registration secret.

## Why inspect the image instead of relying on documentation

The upstream source and documentation do not form a single interchangeable provider-bundle authority.

For the initial `cloudbase/garm` v0.2.1 candidate:

- annotated tag object: `859585744a82a760af10d35b2f37b1d0a22d7948`;
- release commit: `154638445c3949c1958b01812f69d9a1e4d82684`;
- image tag: `ghcr.io/cloudbase/garm:v0.2.1`;
- controller target platform: `linux/amd64`.

At that exact source commit, the Dockerfile build loop includes `garm-provider-linode`, but the final image stage does not copy it into `/opt/garm/providers.d`. The same Dockerfile does not include `garm-provider-oci`, although newer/current GARM provider documentation lists OCI as a supported provider.

The Foundry therefore preserves **the actual provider bytes in the exact pinned image**. It does not silently synthesize a bundle from a newer documentation table or from intermediate build-stage intent.

A later appliance decision may deliberately add or remove a provider for a documented compatibility/security reason, but that is a separate reviewed change rather than an accidental side effect of packaging.

## Gate mechanics

`.foundry/garm-appliance/upstream-v0.2.1.json` records:

- exact release/source identity;
- image reference and target platform;
- immutable image digest once discovered;
- exact provider filenames;
- exact SHA-256 for every shipped provider executable;
- known upstream source/image/documentation seams;
- the qualification claim boundary.

`.github/workflows/validate-garm-appliance-base.yml`:

1. runs only on GitHub-hosted `ubuntu-24.04`;
2. pulls the candidate `linux/amd64` image;
3. resolves its immutable registry digest;
4. creates but does not start a container;
5. copies `/opt/garm/providers.d` to the hosted runner;
6. hashes every provider executable;
7. validates the result with `tools/validate_garm_appliance_base.py`;
8. records sanitized JSON evidence and uploads it as a short-retention artifact.

The first discovery run intentionally fails the final gate because the profile contains no immutable image/provider hashes yet. That run is used only to capture public evidence. The observed digest and hashes are then reviewed, pinned into the profile, and the same workflow must PASS on a second run before merge.

## What PASS means

A PASS establishes that the exact configured image digest for the configured platform reproduces the exact recorded `/opt/garm/providers.d` filename set and provider executable hashes.

This is **packaging-baseline evidence only**.

It does not establish that:

- every bundled upstream provider can authenticate or create a runner;
- any bundled provider is suitable for a particular GitHub account or organization;
- GARM Runner Scale Sets or webhook Pools work from the future TrueNAS App;
- the future TrueNAS controller App starts, persists, upgrades, or passes HIL;
- `garm-provider-truenas` has been added to the controller image;
- the TrueNAS Apps, Containers, or VM runner backends are all qualified.

Those remain independent gates.

## Next packaging step

After this baseline is pinned and privately re-intaken, the next bounded controller-image increment is to derive an appliance image from the selected GARM base while **additively** inserting an exact qualified `garm-provider-truenas` executable. Its CI must prove that all pinned upstream provider bytes remain unchanged and that the new TrueNAS provider appears only as an additional entry.
