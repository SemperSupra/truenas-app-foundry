# ShelfMark Book2EPUB — Foundry candidate (source only)

Product authority: ShelfMark-Bindery/pipeline#50 and draft PR #51.
Private intake: SemperSupra/truenas-app-foundry-private#325.
Parent generic Foundry lifecycle: #274 and #290.

This directory is a pre-catalog source candidate. The image reference is
deliberately unpublished; **do not deploy** or claim source/runtime qualification.

Stages and gates:
- Product Source: exact PR #51 candidate SHA 104f292122e0a446a8946e23c98697f70cf8f9e6.
- Source rendering: exact truenas/apps commit and ix lib v2.3.4; NOT RUN.
- Container image build and digest publication: NOT RUN.
- Normalized Compose/IR + immutable deployment artifact: NOT RUN.
- Disposable exact 25.04.2.6 Foundry F0-F5: NOT RUN.
- Functional browser+PDF/EPUB H0-H5 and visual illustration placement: NOT RUN.
- Physical TrueNAS APPLY: HOLD.

No app-specific lifecycle scripts, custom Apply YAML, Docker socket, or
unauthenticated public ingress. Source/render/pass cannot imply GPU, image,
app runtime or private promotion qualification.

Red team should examine untrusted PDFs, model downloads, persistence,
container resource limits, web request behavior, port binding (host_ips [] is
NOT proven LAN-only), EPUBCheck, and dropped illustration faults.
