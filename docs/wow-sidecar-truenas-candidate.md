# WOW Sidecar TrueNAS candidate — source-qualified frontier

Private Foundry tracker retained outside the public projection.

This candidate is intentionally **not yet an App package**. It freezes the source/build facts that Foundry may consume and makes later HIL eligibility mechanically fail closed.

Current accepted source evidence:

- published WOW source authority: `SemperSupra/wow-sidecar@8c2949691265027acd039fec674787da05c4fd99`;
- exact public qualification head: `246a7f635c70cf93803b1932ef4129040f6ff458`;
- compatibility run: `36381580065` — PASS, 116 tests;
- container build run: `36381580056` — PASS;
- exact base image: `python@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f`;
- qualification-only local image ID: `sha256:b39c8a2a8437d1584d5d0e808a55a38c787ef2b7b28bd4367e543fb06b6c8bee`.

The qualified head and published merge have the identical complete Git tree `5d43ddcfb8d36748448d8c3bebef0c4abfd12f0f`. This supersedes the earlier five-file equivalence proof and includes the host-control/MCP role-boundary correction discovered before HIL.

## Next gates

1. publish an immutable candidate image to `ghcr.io/sempersupra/wow-sidecar@sha256:...` under WOW release authority;
2. construct/render the TrueNAS Custom App using that exact digest;
3. public-safe render/catalog validation;
4. private TrueNAS HIL with synthetic/non-consequential authority;
5. state-preserving migration/cutover and rollback qualification.

The root-required GARM capacity-two integration is **not** part of the default least-privilege WOW App. It remains a separately qualified Foundry/GARM integration and must not broaden the App privilege envelope.

Until gates 1 and 2 pass, `hil_eligible=false` is mandatory. No live appliance mutation is authorized by this candidate.
