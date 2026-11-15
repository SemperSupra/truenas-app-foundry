# Native Apps T4–T5: source-staged, not yet dispatched

Foundry #353 is authority. This workflow is deliberately **not** triggered by normal source-file or workflow edits. It runs only on a new one-off, exact-version request document under `tools/rdte/requests/native-t5`, which must be created in a distinct PR after T3's terminal guest receipt is read and accepted.

Preflight verifies request schema/limited scope and queries the GitHub REST run record directly for the exact successful T3 run and SHA. It then executes the vendored, source-hash-verified public TrueNAS installer T5 rung (T0–T5 in one disposable KVM guest), independently rejects an exit-0 classified RED, demands native app lifecycle and absent experimental guest state, and archives a classified receipt.

The platform target is one digest-pinned **public nginx** Custom App for substrate T4/T5 only. This is **not** the private or public-synthetic Agent Dispatch two-service Foundry App F0–F5, nor production host qualification. Do not create an arbitrary source PR as a T5 dispatch, repeat a request ID, widen supported target versions or initiate a physical migration. No Agent Dispatch service, scheduler or private GHA execution.
