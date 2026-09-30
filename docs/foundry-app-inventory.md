# Foundry app inventory

The Foundry app inventory is the durable, Git-backed address book for app source
identities that can enter the TrueNAS materialization pipeline before official
catalog publication.

It is intentionally **not** a replacement catalog service or a second mutable
database. The source of truth is `.foundry/app-inventory.json`.

## First-slice contract

The initial read-only CLI is:

```text
python3 tools/foundry_app_inventory.py validate
python3 tools/foundry_app_inventory.py list
python3 tools/foundry_app_inventory.py show --app APP --version VERSION
python3 tools/foundry_app_inventory.py resolve --app APP --version VERSION --target-version TRUENAS_VERSION
```

All identity selection is exact. There is no implicit `latest`.

`resolve` joins the app source identity to the existing exact-version TrueNAS
target registry. It does not authorize mutation. The returned
`mutation_eligible` value is inherited from the target registry and remains
false until the exact target is apply-qualified under the Foundry acceptance
process.

## Entry shape

Each app/version records:

- stable Foundry app id;
- exact app/source version;
- source kind, repository, ref and path;
- intended catalog train as metadata;
- exact target versions admitted for the candidate, when constrained;
- catalog-export assessment state.

The inventory deliberately does not duplicate runtime receipts. Qualification
state is joined from the target/evidence surfaces so the inventory does not
become a second mutable truth.

## Next earned slices

Once this read-only contract is accepted:

1. add a bounded bootstrap/seed operation that validates a candidate before
   writing an inventory entry;
2. bind inventory resolution to the existing materializer and identity-bound
   deployment artifact;
3. add Foundry lifecycle operations only behind accepted observe/plan/apply/
   verify contracts;
4. add catalog-ready export validation without automatic publication.

Private design/acceptance authority: `SemperSupra/truenas-app-foundry-private#274`.
