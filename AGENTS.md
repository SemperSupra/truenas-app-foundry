# Agent Instructions

This repository is the public execution/packaging plane for the TrueNAS App Foundry. It is not an application development authority and it is not the private promotion authority.

Rules:

- Keep all work public-safe. Never request or add credentials that can read private repositories or reach a private TrueNAS host.
- GitHub-hosted runners are the default execution environment. Do not target private/self-hosted runner labels from this repository.
- Generic public execution mechanics may be hand-authored and reviewed here.
- Product source defects belong in the product's development authority, not in this Foundry.
- Private evaluator logic, adversarial corpora, failure taxonomies, promotion thresholds, and private environment evidence belong in `SemperSupra/truenas-app-foundry-private`.
- Bind qualification to exact public repository revisions. Avoid mutable source identities in release-critical evidence.
- Pin third-party Actions by full commit SHA.
- Treat successful public CI as evidence, not private promotion approval.
- Preserve reproducible, repeatable, reversible where practical, and idempotent/convergent behavior.
