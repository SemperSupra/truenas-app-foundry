# Public upstream qualification lane

The source manifest binds four **public release tags to exact commits**. The matrix independently fetches each public release tag and verifies its dereferenced commit. This is source identity, not a license approval or build claim.

The ComfyUI job builds the **actual public upstream source** in a disposable CPU container, with CPU PyTorch wheels, no models, no third-party custom nodes, and no external network at runtime. It checks the real `/system_stats` endpoint and CPU device type. Source revision, local OCI image ID and resolved pip versions are recorded in logs. This is exploratory RDT&E: the base image and transitive Python dependencies are not fully digest/lock pinned, and no image is published. ComfyUI's upstream GPLv3 source remains available at its pinned commit; any subsequent distribution needs corresponding-source and license review.

SwarmUI, InvokeAI, and ACE-Step have **source identity probes only** in this increment. Their real-image/CPU boot, native iX catalog source rendering, target lowering, GPU/inference, and production compatibility remain separate gates. No private input, credential, site binding or model data is needed. The probe container is not the deployable Stage 1 Compose proposal and does not establish its rootless storage/runtime compatibility.
