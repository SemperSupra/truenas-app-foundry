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
