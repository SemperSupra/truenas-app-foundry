# Synthetic Takeout — public Foundry source-only candidate

Authority: SemperSupra/truenas-app-foundry-private#327, Agent Dispatch private #642, public synthetic source #426.

**PREPARED/HOLD**. Uses pinned official truenas/apps 25.04.2.6 source renderer and library 2.3.4. Fixture image is deliberately **UNPUBLISHED** and not in a registry; this candidate cannot install an app. It has no Google account access, signed URL, cookies, or private backup code.

The one-shot source has rootless UID:GID 10001:10001, read-only root, no ingress/listening ports, bounded resources, one synthetic archive dataset and separate temporary state dataset. Two `ix_volume` declarations are strictly **disposable source-render fixtures**; they do NOT establish the real user's archival ZFS dataset retention behavior. Before T6 admission qualify actual host-managed retention and cleanup separately, using a least-authority site-local adapter and full data/ownership evidence. No per-product lifecycle executor.

Source render, normalized Compose, OCI publication, independent process exit witness, actual disposable TrueNAS host/mount cleanup, or physical apply are NOT claimed from this candidate. Foundry lifecycle PR #136→#143 remains observation-only and unaccepted without the native terminal witness. Real export retrieval/auth remains separate, private and out of public GHA.
