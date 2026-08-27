# TrueNAS App Foundry

Public execution, packaging, materialization, compatibility, and trust plane for TrueNAS App source applications and candidates.

This repository is intentionally observable. It contains generic public-safe tooling for source rendering and validation, normalized deployment IR generation, known-good materialization controls, public provenance/trust evidence, and qualification of exact public source revisions on GitHub-hosted runners.

It is **not** the development authority for applications and it is not the private promotion authority. Product implementation remains in product repositories; private qualification/promotion authority is `SemperSupra/truenas-app-foundry-private`.

Canonical terminology lives in `docs/terminology.md`. Runtime-target status and possible future target-lowering backends live in `docs/runtime-targets.md`.

## Materialization model

Use **materialization** as the umbrella process. When precision matters, distinguish these stages:

```text
TrueNAS App Store-compatible source application
        |
        | source rendering
        v
normalized deployment IR
(currently normalized Compose JSON)
        |
        | target lowering
        v
target-specific deployment artifact
        |
        | runtime realization
        v
runtime target / target profile
        |
        | execute + observe
        v
qualification evidence
```

A **materialization control** is a known-good source application used to test source rendering/materializer behavior. It is not a runtime target.

## Initial RDTE/MVP

The first consumer is the GARM + TrueNAS runner stack:

- independently qualify exact `SemperSupra/garm` candidate SHAs on standard GitHub-hosted Ubuntu runners rather than upstream's custom runner labels;
- build/test `SemperSupra/garm-provider-truenas` using public-safe mocked TrueNAS API tests;
- source-render and validate prospective TrueNAS App packages with official iX-compatible tooling;
- maintain exact compatibility evidence for the relevant public TrueNAS source surfaces;
- retain only public-safe mechanics and evidence here;
- never receive credentials capable of reading private repositories or reaching a private TrueNAS host.

Public GitHub-hosted execution is the default for this repository.

## TrueNAS source-rendering control gate

`.foundry/truenas-apps-upstream.json` pins one exact public `truenas/apps` revision and its iX library identity. `tools/validate_truenas_materialization.py` checks out that exact revision, source-renders known-good catalog controls through upstream `ci.py`, normalizes the generated Compose with Docker Compose, and verifies stable structural/security properties.

The initial **materialization controls** deliberately exercise different source shapes:

- `community/forgejo-runner` proves a runner-like source application with helper services, persistent data, healthcheck, and its intentional upstream Docker-socket mount;
- `community/ntfy` proves conventional storage, permission-helper, healthcheck, and published-port rendering without a Docker socket.

The GitHub-hosted workflow `.github/workflows/validate-truenas-materialization.yml` records a sanitized fingerprint of the normalized controls together with the exact upstream source/library identity.

A PASS establishes only that the pinned public TrueNAS Apps source materializer reproduced the expected known-good control envelopes in public CI. It does **not** establish private promotion approval, provider correctness/security, target lowering, runtime realization, or live compatibility with a private TrueNAS host. Those remain separate qualification and HIL gates.

## Runtime targets

The active MVP runtime target is **TrueNAS SCALE Apps**. Docker Compose is already used as the practical normalized IR and for focused smoke evidence, but general Docker Compose runtime qualification is still future work.

Possible future runtime targets, tracked without support claims, include Podman Compose, Podman Quadlet/systemd, Kubernetes, k3s, Nomad, and selected nerdctl/containerd profiles. See `docs/runtime-targets.md` and issues #5/#6.

## Upstream TrueNAS compatibility

Foundry should ground native compatibility in the public upstream implementation rather than maintain a private reinterpretation of “TrueNAS-compatible”:

- `truenas/apps` anchors source application/catalog schemas, iX library/templates, known-good controls, and rendering behavior;
- `truenas/middleware` anchors the native Apps CRUD/custom-App/Compose/ix-volume/lifecycle implementation used for runtime realization.

Future compatibility profiles should bind exact source identities and release-specific middleware commits to target-profile evidence. This capability is tracked in issue #5 and does not replace HIL evidence from the actual target host.
