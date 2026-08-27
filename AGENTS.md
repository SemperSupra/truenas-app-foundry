# Agent Instructions

This repository is the public execution/packaging/materialization plane for the TrueNAS App Foundry. It is not an application development authority and it is not the private promotion authority.

Canonical vocabulary is defined in `docs/terminology.md`. Use it consistently: source rendering, normalized deployment IR, target lowering, deployment artifact, runtime realization, runtime target, target profile, qualification, and materialization control. Use `materialization` only as the umbrella term when the finer stage distinction is not material.

Rules:

- Keep all work public-safe. Never request or add credentials that can read private repositories or reach a private TrueNAS host.
- GitHub-hosted runners are the default execution environment. Do not target private/self-hosted runner labels from this repository.
- Generic public execution mechanics, source materializers, normalized IR tooling, target-lowering adapters, compatibility checks, and public-safe qualification evidence may be hand-authored and reviewed here.
- Product source defects belong in the product's development authority, not in this Foundry.
- Private evaluator logic, adversarial corpora, failure taxonomies, promotion thresholds, and private environment evidence belong in `SemperSupra/truenas-app-foundry-private`.
- Bind qualification to exact public repository revisions. Avoid mutable source identities in release-critical evidence.
- For native TrueNAS compatibility, prefer exact `truenas/apps` and release-specific `truenas/middleware` identities over floating upstream branches when practical.
- Pin third-party Actions by full commit SHA.
- Treat successful source rendering or target lowering as evidence about those stages, not runtime qualification.
- Treat successful public CI as evidence, not private promotion approval.
- A future runtime target must not be described as supported until an explicit target adapter and target-profile qualification exist.
- Preserve reproducible, repeatable, reversible where practical, and idempotent/convergent behavior.
