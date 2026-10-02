# Foundry product × TrueNAS target matrix

Authority: `SemperSupra/truenas-app-foundry-private#282`.

This matrix prevents platform/control evidence from being mistaken for product support.

Each Foundry product must have an explicit cell for every exact TrueNAS target in
`.foundry/truenas-target-tracks.json`. A new target intentionally breaks stale
coverage until every product is reconciled.

A cell is `PASS` only when it carries an exact runtime receipt with
`SUPPORTED`, `oracle_satisfied=true`, and a completed F0–F5 lifecycle claim.
Source/render validation, system T5, official-catalog controls, or another
product's T6 result cannot satisfy the cell.

Current product rows are deliberately OPEN unless the complete profile-driven
F0–F5 recipe has been independently proven. In particular, the existing
LiteLLM BETA.3 T6 receipt remains useful prior evidence but is not promoted into
a complete matrix PASS retroactively.

The validator also discovers `candidates/*/candidate.json`; adding a candidate
without adding a matrix row fails closed.
