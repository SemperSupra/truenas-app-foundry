# Foundry app inventory and bootstrap

The Foundry app inventory is the durable, Git-backed address book for app source
identities that can enter the TrueNAS materialization pipeline before official
catalog publication.

It is intentionally **not** a replacement catalog service or a second mutable
database. The source of truth is `.foundry/app-inventory.json`.

## Read-only inventory contract

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

## Bootstrap/admission proposal

A new pre-catalog app enters through a non-authoritative proposal step:

```text
python3 tools/foundry_app_inventory.py \
  bootstrap \
  --spec bootstrap.json \
  --source-root /path/to/materialized/app/source \
  --proposal-out proposed-inventory.json \
  --receipt-out bootstrap-receipt.json
```

The bootstrap specification is:

```json
{
  "schema": "truenas-foundry-app-bootstrap/v1",
  "entry": {
    "id": "example",
    "version": "1.0.0",
    "source": {
      "kind": "foundry-repository",
      "repository": "https://github.com/example/example.git",
      "ref": "<exact ref>",
      "path": "truenas"
    },
    "catalog_train": "community",
    "target_versions": ["25.10.7", "26.0.0-BETA.3"],
    "catalog_export": {"status": "not-assessed"}
  }
}
```

The caller is responsible for materializing the exact repository/ref/path into
`--source-root`. Bootstrap deliberately does not perform credentialed source
fetches.

Bootstrap requires the same source shape documented by the TrueNAS Apps
contribution workflow:

- `README.md`;
- `app.yaml`;
- `ix_values.yaml`;
- `questions.yaml`;
- `templates/docker-compose.yaml`;
- at least one `templates/test_values/*.yaml`.

It also requires top-level `app.yaml` `name`, `version`, and `train` to
match the proposed inventory identity, rejects symlinks, requires every target
to be an already registered exact TrueNAS version, and records a deterministic
source-tree SHA-256.

The result is **READY_FOR_GIT_REVIEW**, not catalog-ready. The tool writes a
proposed inventory file and leaves the canonical inventory untouched. Admission
occurs through ordinary Git review/merge so there is no hidden mutable source
of truth.

## TrueNAS-native validation boundary

Structural bootstrap is only the first source gate. It does **not** replace the
official TrueNAS catalog validators.

The upstream TrueNAS Apps repository currently validates development catalog
source with `apps_dev_charts_validate validate --path ...`, and its app test
suite renders/installs each test-values fixture through the repository's
`.github/scripts/ci.py` path. Foundry catalog-readiness must eventually run
the pinned equivalents of those two oracles against the exact candidate source.

Until those oracles pass, inventory source metadata records:

```text
structural_preflight = PASS
official_validator = PENDING
catalog_ready = false
```

This prevents successful Custom App runtime RDTE from being confused with
catalog-source correctness.

## Entry shape and evidence

Each app/version records:

- stable Foundry app id;
- exact app/source version;
- source kind, repository, ref and path;
- intended catalog train as metadata;
- exact target versions admitted for the candidate;
- deterministic source-tree identity after bootstrap;
- source-contract status;
- catalog-export assessment state.

The inventory does not duplicate target runtime receipts. Target qualification
is joined from the exact-version target registry so the inventory does not
become a second mutable truth.

## Next earned slices

1. pin and execute the TrueNAS-native dev-catalog validator/render-install
   oracles for a bootstrap candidate;
2. bind an admitted inventory identity to the existing normalized materializer
   and identity-bound deployment artifact;
3. add Foundry lifecycle operations only behind accepted
   observe -> plan -> apply -> verify contracts;
4. add catalog-ready export validation without automatic publication.

Private design/acceptance authority:
`SemperSupra/truenas-app-foundry-private#274`.
