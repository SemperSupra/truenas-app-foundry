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


## External products

Products whose implementation lives outside the Foundry repository are still explicit
matrix members. They are listed in `required_external_product_ids`, which makes omission
fail closed without pretending they are Foundry candidates.

The current external rows include LiteLLM and FolioRelay. FolioRelay is bound to
`SemperSupra/truenas-app-foundry-private#273` and public product authority
`SemperSupra/folio-relay#29`. Its current BETA.3 reps are retained only as causal
failure evidence; all FolioRelay exact-target cells remain OPEN until a complete
receipt earns PASS.
