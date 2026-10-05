# WOW Sidecar (Go) — parallel TrueNAS Custom App candidate

This is the parallel Go-native TrueNAS App projection for the current WOW
embodiment runtime. It does **not** replace the accepted Python-era candidate
under `candidates/wow-sidecar-app`; that package remains the rollback baseline.

## Current state

This candidate is repo-prepared only:

- public G6.11e source candidate: `cd2d073f7d4366fa4165b8875e19d286da4e8784`;
- repaired-head release mechanics are qualify-only PASS at public PR #76 head
  `2c236d83705c811099fd9d60959692e5003edaef`, run `37278888142`;
- publication/native verification/receipt were SKIPPED;
- publication receipt v2 is prepared to carry the multi-arch manifest digest,
  exact amd64/arm64 platform digests, run identity, workflow SHA, and build
  recipe/toolchain/BuildKit provenance;
- exact image publication has **not** occurred;
- the all-zero image digest is an intentional synthetic, non-deployable fixture;
- public App render qualification, private TrueNAS HIL, cutover, and rollback
  qualification remain pending.

Do not install the zero-digest candidate on a live appliance.

## Runtime contract

- fixed non-root identity `10001:10001`;
- read-only root filesystem;
- writable persistent state only at `/var/lib/wow-sidecar`;
- tmpfs at `/tmp`;
- no seed helper or shell in the Go runtime path;
- GitHub App key mounted as a private read-only config file at
  `/run/secrets/github-app.pem`;
- no raw GitHub App key in environment variables;
- durable control bound to exact repository/profile/capability/authority
  configuration;
- local rendezvous complete-or-absent, with lease range 5..3600 seconds;
- peer observation optional, polling range 5..3600 seconds;
- G6.11e peer mutation optional and disabled by default.

When G6.11e is enabled, the pairwise credential document is mounted read-only at
`/run/secrets/wow-peer-credentials.json` and the daemon receives only:

- `WOW_PEER_RENDEZVOUS_ENABLED=true`;
- `WOW_PEER_CREDENTIALS_FILE=/run/secrets/wow-peer-credentials.json`;
- `WOW_PEER_MAX_SKEW_SECONDS` in 1..600;
- `WOW_PEER_REPLAY_TTL_SECONDS` in 1..1800.

The App does not advertise `WOW_PUBLIC_ENDPOINT` by default. Publishing a
TrueNAS port is not treated as proof of authenticated peer reachability.

## Network and storage

The daemon listens internally on port 8080. The host-facing port is projected
through the supported TrueNAS port question contract; no host networking or
container-runtime socket is used.

Persistent generation/runtime state uses a TrueNAS-managed ixVolume. Host paths
are not offered by this candidate.

## Promotion boundary

Before this candidate can become HIL-eligible:

1. repaired G6.11e runtime acceptance (#96/#89) must be durable;
2. an exact multi-arch Go image must be published through the already-qualified
   repaired-head release workflow and produce receipt
   `wow-sidecar.go-publication-receipt.v2`;
3. the receipt must bind source SHA, manifest digest, exact amd64/arm64 platform
   digests, publication run identity, workflow SHA, and build recipe provenance;
4. the zero digest must be replaced by that exact accepted manifest digest;
5. the public-safe App render must pass on the exact rebound candidate;
6. only then may private/disposable TrueNAS qualification proceed.

No step here authorizes live TrueNAS mutation or state-preserving cutover.
