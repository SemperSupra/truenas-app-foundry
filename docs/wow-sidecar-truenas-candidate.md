# WOW Sidecar TrueNAS candidate — source-qualified frontier

Private Foundry tracker retained outside the public projection.

This candidate is intentionally **not yet an App package**. It freezes the source/build facts that Foundry may consume and makes later HIL eligibility mechanically fail closed.

Current accepted source evidence:

- published WOW source authority: `SemperSupra/wow-sidecar@c68f4250db460d485eb133b763003d3762f7617e`;
- exact public qualification head: `569142103e8e822a00178104b257e27b6e334638`;
- compatibility run: `36366148367`;
- container build run: `36366148387`;
- exact base image: `python@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f`;
- qualification-only local image ID: `sha256:360bd3cdf3dd8e0d0fa68297407d77e461479241bd21c16f51e3027c618badab`.

The five container-candidate files were independently verified byte-identical between the qualified head and the published squash-merge revision.

## Next gates

1. publish an immutable candidate image to `ghcr.io/sempersupra/wow-sidecar@sha256:...` under WOW release authority;
2. construct/render the TrueNAS Custom App using that exact digest;
3. public-safe render/catalog validation;
4. private TrueNAS HIL with synthetic/non-consequential authority;
5. state-preserving migration/cutover and rollback qualification.

Until gates 1 and 2 pass, `hil_eligible=false` is mandatory. No live appliance mutation is authorized by this candidate.
