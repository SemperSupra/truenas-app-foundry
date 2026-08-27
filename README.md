# TrueNAS App Foundry

Public execution, packaging, materialization, and trust plane for TrueNAS App candidates.

This repository is intentionally observable. It contains generic public-safe tooling for rendering and validating TrueNAS App candidates, comparing against known-good controls, producing public provenance/trust evidence, and qualifying exact public source revisions on GitHub-hosted runners.

It is **not** the development authority for applications and it is not the private promotion authority. Product implementation remains in product repositories; private qualification/promotion authority is `SemperSupra/truenas-app-foundry-private`.

## Initial RDTE/MVP

The first consumer is the GARM + TrueNAS runner stack:

- independently qualify exact `SemperSupra/garm` candidate SHAs on standard GitHub-hosted Ubuntu runners rather than upstream's custom runner labels;
- build/test `SemperSupra/garm-provider-truenas` using public-safe mocked TrueNAS API tests;
- render and validate prospective TrueNAS App packages with official iX-compatible tooling;
- retain only public-safe mechanics and evidence here;
- never receive credentials capable of reading private repositories or reaching a private TrueNAS host.

Public GitHub-hosted execution is the default for this repository.

## TrueNAS materialization control gate

`.foundry/truenas-apps-upstream.json` pins one exact public `truenas/apps` revision and its iX library identity. `tools/validate_truenas_materialization.py` checks out that exact revision, renders known-good catalog controls through upstream `ci.py`, normalizes the generated Compose with Docker Compose, and verifies stable structural/security properties.

The initial controls deliberately exercise different materialization shapes:

- `community/forgejo-runner` proves a runner-like App with helper services, persistent data, healthcheck, and its intentional upstream Docker-socket mount;
- `community/ntfy` proves conventional storage, permission-helper, healthcheck, and published-port materialization without a Docker socket.

The GitHub-hosted workflow `.github/workflows/validate-truenas-materialization.yml` records a sanitized fingerprint of the normalized controls together with the exact upstream source/library identity.

A PASS establishes only that the pinned public TrueNAS Apps materializer reproduced the expected known-good control envelopes in public CI. It does **not** establish private promotion approval, provider correctness/security, or live compatibility with a private TrueNAS host. Those remain separate private qualification and HIL gates.
