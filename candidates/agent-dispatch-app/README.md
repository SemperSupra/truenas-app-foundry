# Agent Dispatch Foundry synthetic source contract (qualification-only)

Authority: private Foundry #353, #274, #290; Agent Dispatch private #748; disposable TrueNAS #396.

This fixture covers the public-safe *shape* of the planned control/worker App:
same image identity, no root or privileged mode, no host/container socket, control
loopback ingress only, custody read-only, effect ledger read-write and data retained
across App removal. The image host `registry.invalid` is intentionally non-pullable.
No private source/image digest, token, ZFS path or physical App state is contained here.

**Gates not passed:** TrueNAS official iX source render; immutable *runnable*
public Go image; Foundry F0-F5 native app lifecycle; actual private Go image
qualification; host custody/rollback migration. Do not deploy this fixture.

Next: adapt source into official-shaped pre-catalog TrueNAS `ix-dev` package,
pin upstream iX materializer and its OCI images, then use one disposable native
TrueNAS KVM system via Agent Dispatch #396. Keep public test data synthetic.
