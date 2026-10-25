# SemperSupra LiteLLM appliance v0

Thin derivative of the signed upstream LiteLLM v1.103.0 image.

Pinned upstream evidence:

- tag: `v1.103.0`
- tag commit: `c991f4b01f5799eb0b0cab0fb63988e15c3a8a9d`
- OCI digest: `sha256:bd089afdcd35b894b14a93f9743cdc8b591f82da1a38dd43a010a7b0c9de5fd7`
- upstream cosign key commit: `0112e53046018d726492c814b3644b7d376029d0`
- public GHA verification run: `SemperSupra/agent-dispatch/actions/runs/36496814619`

The only runtime behavior added by the appliance is protected file-to-environment projection from `/run/secrets/semper-env`, followed by exec of upstream `/app/docker/prod_entrypoint.sh`.

The image does not contain provider credentials, account-management logic, routing policy, or a replacement LiteLLM control plane.
