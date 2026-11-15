# Source-verbatim, immutably pinned disposable TrueNAS installer harness

This source was copied as public text, with per-file Git blob verification, from the already-qualified SemperSupra/agent-dispatch branch experiment/gha-kvm-system-rdte at commit 8744304c3c0a332460b1c5db97a2fb1e9562b222. Provenance is held in SOURCE-PROVENANCE.json. This **does not use Agent Dispatch as an executor**: it is just vendored public QEMU/TrueNAS test code, run by independent Foundry GitHub Actions.

The initially admitted Foundry workflow runs exactly rung T2 on TrueNAS 25.04.2.6: verify vendor ISO+SHA sidecar, boot the real installer, authenticated read-only installer RPC, install onto disposable disk, reboot installed TrueNAS and verify middleware. It inherits bounded cleanup from the proven source; the Foundry workflow independently requires SUPPORTED, full T2 positive oracles and absent disposable state.

Other rungs (including T3 pool/T4 Apps/T5 lifecycle/T6 Foundry) are present in the source but **not admitted by this workflow**. They require the corresponding exact source dependencies and their own test/authority gates; do not use this vendored directory as a general arbitrary host mutation launcher. The source registry authority_issue fields are historical lineage only; Foundry private #353 is the current authoritative test workset.

No private code, credential, live TrueNAS/OCI host, GHCR publication, external scheduler, local Agent Dispatch or WOW Sidecar dependency. D2 full F0-F5 is not complete on a T2 pass.
