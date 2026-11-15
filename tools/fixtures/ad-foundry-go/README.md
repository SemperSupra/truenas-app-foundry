# Independent public Go runtime smoke for Foundry

This standalone, stdlib-only Go control/worker fixture is *not* Agent Dispatch
source and intentionally performs no remote dispatch or production side effects.
CI builds a scratch image locally without publishing to GHCR. The two services
run nonroot, no-new-privileges, read-only root; control binds to host loopback,
worker has no ingress, custody is mounted ro and ledger rw.

One disposable Docker Compose lifecycle verifies:
- control readiness stays negative until synthetic custody and worker ledger exist;
- worker writes a durable synthetic count;
- app container teardown and recreation preserve external state (count 1 -> 2);
- no Docker socket, external credentials, private source or physical NAS access;
- cleanup removes experiment-owned containers and temp paths.

This proves a **public Docker runtime surrogate** only. It does not prove the
private Go image, catalog render, TrueNAS native Apps F0-F5, host-storage
permissions, cross-venue fencing or live deployment. Governing private DLE:
Foundry #353 / #274 and Agent Dispatch #748 / native lab #396.
