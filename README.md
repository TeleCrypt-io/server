# TeleCrypt.io server state

Public runtime configuration for the TeleCrypt Matrix service:

Current TeleCrypt project facts and decisions are maintained only in the canonical
[`llms.txt`](https://telecrypt-io.github.io/llms-authority/llms.txt); this README documents this
repository's deployment model and release contract.

## Configuration and activation

The private Harness owns host setup, private runtime values, deployment, service activation, and
acceptance. This repository supplies the public state files and systemd units; use the Harness
release procedure to install and activate them.

`versions.env` is the only image coordinate source and contains exactly five keys: `CADDY_IMAGE`,
`SYNAPSE_IMAGE`, `MAS_IMAGE`, `CONTROLPLANE_IMAGE`, and `CASHIER_IMAGE`. The Quadlet declarations in
`systemd/quadlet/` consume those values. `systemd/telecrypt-pod.service` creates the shared rootless
Podman pod with pasta and the configured ingress binding; `systemd/telecrypt.target` groups the
long-running services. Janitor has a separate one-shot service and timer. The Harness controls timer
activation for each environment.

Private environment, identity, and secret files are supplied outside this repository. The tracked
Synapse and MAS base and profile files contain nonsecret configuration; the Harness supplies their
private overlays and runtime identity files. No operator `.env` file or alternate image list is
checked in.

All services share one rootless Podman pod network namespace and communicate over loopback. The MAS
admin listener is pod-local, has no host-published port, and is not routed by Caddy; MAS continues to
authorize admin API requests. Keep the Stage Janitor timer disabled until controlled Stage account
tests verify locking, paid-account exclusion, existing-session access loss, and manual recovery through
Plan controls.

## Billing operations

The operator's private Harness owns billing-environment procedures, provider authority, private-input
handling, and billing acceptance. Current public billing facts and decisions remain in the canonical
[`llms.txt`](https://telecrypt-io.github.io/llms-authority/llms.txt); this repository retains only its
configuration assembly and release contract.

## Releases

The repository publishes no packages, images, deployment tools, binaries, or secret templates. The
validation workflow checks that every exact image in `versions.env` is available and parses the
Quadlet units using Podman's 4.9.3 user generator, matching Stage. The image release validator also
checks the selected image metadata and provenance before writing the release manifest.

A reviewed `server-state-<short-git-sha>` annotated tag identifies one configuration commit. The
validation job requires the tag suffix and push event to match its target, then checks that commit is
an ancestor of the fetched `main` branch. It passes the commit and annotated tag-object identity to the
release job, which verifies the same checkout before publication; `main` may advance while the
workflow runs.

The immutable Server State GitHub Release carries one deterministic JSON asset binding the five
selected image coordinates to their observed registry digests. Before publishing it, the workflow
verifies immutable GitHub Release and annotated-tag evidence for Synapse and Controlplane, along with
the required OCI provenance. The release job reads back the published release and verifies the asset's
exact bytes. Existing same-tag releases are left unchanged. If publication leaves a partial draft, the
owner inspects and removes it before retrying; the workflow does not attempt recovery. The private
Harness owns deployment and acceptance.

## Security and licence

Do not commit `.env`, populated secret templates, signing keys, or deployment inventory. Report
security issues according to [SECURITY.md](./SECURITY.md).

Licensed under [BUSL-1.1](./LICENSE); converts to Apache-2.0 on 2030-07-20.
