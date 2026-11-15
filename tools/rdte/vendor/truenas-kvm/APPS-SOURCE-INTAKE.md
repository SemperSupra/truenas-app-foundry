# Stage T4–T5 native TrueNAS Apps client intake (source-only)

This branch is a distinct, low-cost public-source qualification batch independent of the T3 heavyweight guest. Three adapters copied verbatim from the public Agent Dispatch experiment source at commit 8744304c3c0a332460b1c5db97a2fb1e9562b222; exact Git blob IDs are in test_foundry_native_truenas_apps_source.py.

Original platform flow: T3 two-disk ZFS mirror, T4 exact digest-pinned public nginx custom App create/read-back, T5 native stop/start, update/read-back, redeploy and delete/absence. Stage T4–T5 will be admitted for real guest execution ONLY after the independently verified Foundry T3 native receipt. Source-only CI here must not be mistaken for native TrueNAS Apps proof, and neither constitutes a Foundry Agent Dispatch F0–F5 product pass.

No private assets, image credentials, live host changes, new control plane or Agent Dispatch runtime. Public GHA is the sole free source-test executor.
