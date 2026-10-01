# Foundry inventory-to-artifact binding

This slice connects the Git-backed Foundry app inventory to the existing
identity-bound TrueNAS deployment-artifact primitive.

Inputs:

- exact inventory app id + version;
- exact registered TrueNAS target version;
- normalized Compose IR;
- bootstrap source-tree identity already recorded in the inventory.

Output:

- `truenas-foundry-deployment-artifact/v1`;
- a sanitized inventory-materialization receipt.

Artifact provenance binds:

- inventory entry SHA-256;
- source repository/ref/path;
- source-tree SHA-256;
- catalog train;
- native catalog-validator state;
- exact target version/profile;
- target apply-qualification state.

Materialization is allowed while catalog validation is still PENDING because
pre-catalog RDTE is a Foundry requirement. That state is retained in provenance
and must not be mistaken for catalog readiness.

The artifact does not authorize mutation. The existing observe/plan/apply gates
still decide whether a target may be changed.
