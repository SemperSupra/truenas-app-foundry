# TrueNAS catalog materialization parity

## Decision

The Foundry will treat a TrueNAS App Store-compatible source application as the desired-state source and reproduce the native TrueNAS catalog materialization contract far enough to realize the same workload through the supported Custom App API.

The objective is **runtime/materialization parity**, not falsifying TrueNAS internal metadata. A Foundry-managed deployment remains a TrueNAS Custom App, but its source rendering, required platform normalization, target lowering, runtime realization, and read-back verification are bound to an exact compatibility profile.

GARM is the first demanding fixture. Certificates are the first missing platform-normalization feature because the GARM runner path requires normally trusted HTTPS.

## Source-derived 25.04.2.6 pipeline

Native catalog creation in `truenas/middleware` performs the following stages before Docker Compose is started:

1. resolve catalog App/version details and normalized question context;
2. validate effective values and conditional/default schema behavior;
3. normalize TrueNAS-specific `$ref` features;
4. perform normalization actions such as ixVolume dataset creation and ACL application;
5. inject reserved values including `ix_certificates`, `ix_certificate_authorities`, `ix_volumes`, and `ix_context`;
6. run the pinned `truenas/apps` renderer/iX library;
7. persist App config/metadata and derive portals/notes;
8. execute the rendered Compose through the Apps lifecycle.

The raw Custom App path skips stages 1-6 and persists the supplied Compose directly. Therefore the Foundry must reproduce the required pre-render semantics before submitting a Custom App and must explicitly account for lifecycle semantics that are not representable in Compose.

## Architecture

```text
source application + explicit/effective values
                 |
                 v
       compatibility-profile gate
                 |
                 v
       platform value resolution
  (API-derived cert/volume/etc. inputs)
                 |
                 v
   TrueNAS-equivalent normalized values
                 |
                 v
 exact pinned truenas/apps renderer/library
                 |
                 v
        normalized Compose IR
                 |
                 v
       TrueNAS Custom App API
                 |
                 v
          runtime realization
                 |
                 v
     read-back + semantic comparison
                 |
       +---------+---------+
       |                   |
      NO-OP             RECONCILE
```

The public Foundry owns generic, public-safe normalization logic, compatibility profiles, source rendering, semantic comparison, and qualification fixtures. The private Foundry adapter is responsible for contacting a real appliance, resolving site-sensitive values, executing authorized side effects, and retaining sensitive evidence locally.

## MVP parity contract

The MVP supports only features required to unblock GARM and must fail closed on an active unsupported feature.

| Feature | MVP behavior | Parity class |
| --- | --- | --- |
| Certificate reference | Resolve selected certificate through TrueNAS API, inject into `ix_certificates`, include public certificate fingerprint in dependency identity | pre-render resolution + lifecycle shim |
| ixVolume | Resolve host path, emit an ownership-gated ensure-dataset action, inject `ix_volumes` | pre-render action |
| ACL | No action when absent/disabled; active ACL requests remain fail-closed until separately qualified | conditional/deferred |
| Node bind IP | Empty selection is supported for the GARM MVP; active choices require validation parity before support is claimed | conditional/deferred |
| Certificate authority | fail closed | deferred |
| GPU configuration | fail closed | deferred |
| Renderer/library features expressible in Compose | use exact pinned upstream renderer/library | render-equivalent |

Unknown active `$ref` features are errors. Silent degradation is prohibited.

## Certificate parity

Native middleware resolves `definitions/certificate` with `certificate.get_instance()` and stores the complete object in `ix_certificates`. Catalog templates then consume the certificate and private key and materialize them as Compose configs/files.

Foundry reproduces that pre-render shape. Certificate/private-key material is allowed only in local normalized values and the final local deployment artifact. Sanitized plans and Git evidence contain only non-secret identity information such as certificate ID and a SHA-256 of the public certificate.

A Custom App does not retain the native catalog certificate attachment relationship used by TrueNAS to trigger automatic redeploy after renewal. The MVP therefore includes the public certificate fingerprint in the materialization dependency identity. A renewed certificate changes desired state and causes deterministic rematerialization/redeploy. This gives behavioral lifecycle parity without pretending the Custom App has native catalog metadata.

## Desired-state and read-back model

Foundry remains the desired-state authority. TrueNAS read-back is verification, not a source from which intent is guessed.

A materialization identity should bind at least:

- source application/version/revision;
- exact `truenas/apps` revision and iX library identity;
- exact `truenas/middleware` compatibility profile;
- effective non-secret inputs;
- external dependency identities/fingerprints;
- normalized Compose fingerprint;
- target/app ownership identity.

Apply must be convergent:

- desired equals observed: no mutation;
- owned drift: reconcile;
- foreign/unowned state: refuse mutation;
- rollback: materialize the previous owned desired state.

## Differential qualification

Native catalog installation is the reference implementation. Native Apps preserve their installed source/version tree, effective `user_config.yaml`, rendered templates, metadata, and observable runtime workload. Representative fixtures can therefore be installed natively, read back, removed, materialized through Foundry, and compared across the same surfaces.

MVP fixtures should cover mechanisms rather than a large catalog corpus:

1. simple service/port/resources;
2. ixVolume/storage;
3. certificate-to-config HTTPS;
4. multi-service/dependency behavior where useful.

Source inspection establishes the intended contract; HIL differential evidence establishes runtime parity.

## Explicit non-goals for MVP

The MVP does not implement a replacement TrueNAS control plane, a resident reconciliation daemon, a Terraform state authority, arbitrary native-App import, every catalog `$ref`, GPU parity, catalog upgrade/migration semantics, manipulation of private ix-apps metadata, or fleet-wide continuous reconciliation.

Those capabilities are added only when a real consumer justifies them and after the corresponding upstream semantics can be pinned and qualified.

## Upgrade path

When a source App later becomes an official native catalog App, Foundry-specific lifecycle shims can be retired in favor of the native catalog lifecycle. Until then, runtime/materialization parity is acceptable even where TrueNAS internally records the workload as a Custom App.
