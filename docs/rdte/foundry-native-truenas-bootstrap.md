# Direct native TrueNAS RDTE: source reuse without runtime coupling

Authority: Foundry-private issue #353, Foundry #274/#290, and Agent Dispatch private #748. Historic native KVM issue agent-dispatch-private#396 is source evidence only, not an execution control plane.

Proven existing public source: SemperSupra/agent-dispatch branch experiment/gha-kvm-system-rdte; scripts/gha_kvm_truenas_rdte.sh (Git blob aee419c4a97829da4d2d7e833aa070d943b2f66e). It specifies exact SHA256-verified vendor media, serial-observable GRUB, native KVM guest, installer RPC, installed middleware, pools and Apps lifecycle. The new Foundry native direct workflow adapts the T0 subset into a standalone script. No GitHub Agent Dispatch checkout or service/API/workflow invocation occurs at runtime.

Exact target: TrueNAS SCALE 25.04.2.6 with vendor ISO SHA sidecar, QEMU/KVM 2 vCPU, 8192 MiB RAM, sparse 24 GiB boot disk, BIOS/virtio and bounded serial vendor-marker observation. TrueNAS app compatibility substrate qualified by Foundry does not imply the Agent Dispatch app is F0-F5 qualified.

A Foundry public PR triggers GitHub-hosted standard free Actions. One heavyweight Foundry concurrency group, resource checks, bounded guest execution, and mandatory cleanup ensure no unmanaged guest is retained. Receipt distinguishes vendor digest, native installer serial marker, live QEMU observation, zero residue, and negative classifications. T0 does NOT install TrueNAS or test native Apps; the job must not claim T2/T3/F0-F5.

Next after T0 acceptance: port exact installer RPC discovery/install, installed middleware and ZFS oracles from the prior successful public source. Once these are verified, native Apps F0-F5 can exercise the harmless synthetic Foundry Go image archive before private product HIL and safeguarded site migration.

No external scheduler, no Agent Dispatch runtime dependency, no production TrueNAS/OCI, no credentials, private code, paid runner, GHCR publication, or actual product deployment. Only a clean public Foundry checkout is required.
