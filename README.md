# TeleCrypt.io server state

Public runtime configuration for the TeleCrypt Matrix service:

Current TeleCrypt project facts and decisions are maintained only in the canonical
[`llms.txt`](https://telecrypt-io.github.io/llms-authority/llms.txt); this README documents this
repository's deployment model and release contract.

## Configuration and activation

The private Harness owns release verification, deployment procedure and acceptance. This
repository supplies the public application state, systemd units and masterless Salt states.
Each host keeps its own Salt pillar, runtime values and secrets; none of those values belong in
this repository.

`versions.env` is the only image coordinate source and contains exactly five keys: `CADDY_IMAGE`,
`SYNAPSE_IMAGE`, `MAS_IMAGE`, `CONTROLPLANE_IMAGE`, and `CASHIER_IMAGE`. The Quadlet declarations in
`systemd/quadlet/` consume those values. `systemd/telecrypt-pod.service` creates the shared rootless
Podman pod with pasta and the configured ingress binding; `systemd/telecrypt.target` groups the
long-running services. Janitor has a separate one-shot service and timer. The Harness controls timer
activation for each environment.

Private environment, identity, and secret files are supplied outside this repository. The tracked
Synapse and MAS base and profile files contain nonsecret configuration; the host-local Salt pillar
supplies its environment values and renders the deployment environment and runtime identity files.
Secret contents remain in the existing host-local files. No operator `.env` file, populated pillar or
alternate image list is checked in.

All services share one rootless Podman pod network namespace and communicate over loopback. The MAS
admin listener is pod-local, has no host-published port, and is not routed by Caddy; MAS continues to
authorize admin API requests. Salt owns the Janitor timer definition and its enabled, active state;
the timer invokes only the tracked oneshot service and is observed through the ordinary Stage
acceptance schedule.

## Host configuration with masterless Salt

The `salt/` tree is applied locally on an Ubuntu host with `salt-call --local`. It manages the
runtime packages, rootless Podman prerequisites, operator directories, nonsecret runtime identity
files, secret-file metadata, the SSH daemon drop-in, stable systemd/Quadlet links and Janitor
scheduling. It does not manage networking, SSH keys, sudo rules, persistent data or secret contents.

Install the pinned Salt LTS version recorded in [`salt/version`](salt/version), then copy
[`salt/pillar/top.sls`](salt/pillar/top.sls) and
[`salt/pillar/telecrypt.sls.example`](salt/pillar/telecrypt.sls.example) to a private
`/etc/telecrypt/pillar` directory. Rename the example to `telecrypt.sls` and replace every host
value. Keep that directory mode `0700` and its files mode `0600`; do not commit it.

Apply host setup before deployment:

```sh
sudo salt-call --local --retcode-passthrough \
  --file-root="$RELEASE_DIR" --pillar-root=/etc/telecrypt/pillar \
  state.apply salt.host
```

After the released `deploy` helper activates the selected Server State release, apply service
activation and Janitor scheduling:

```sh
sudo salt-call --local --retcode-passthrough \
  --file-root="$RELEASE_DIR" --pillar-root=/etc/telecrypt/pillar \
  state.apply salt.services
```

`deploy` selects versions, pulls their prebuilt images, switches `telecrypt-current`, reloads the
user manager and restarts the application target. Salt owns the link topology and Janitor timer;
the two operations are serialized by the operator. Masterless mode requires no Salt master or
running minion daemon. Salt's local execution and file/pillar-root options are documented in the
[Salt CLI reference](https://docs.saltproject.io/en/latest/ref/cli/salt-call.html).

## Billing operations

The operator's private Harness owns billing-environment procedures, provider authority, private-input
handling, and billing acceptance. Current public billing facts and decisions remain in the canonical
[`llms.txt`](https://telecrypt-io.github.io/llms-authority/llms.txt); this repository retains only its
configuration assembly and release contract.

## Releases

The repository publishes no packages, images, deployment tools, binaries, or populated secret
templates. The validation workflow checks that every exact image in `versions.env` is available,
parses the Quadlet units using Podman's 4.9.3 user generator, and renders the Salt states with
synthetic host values. The image release validator also checks the selected image metadata and
provenance before writing the release manifest.

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
