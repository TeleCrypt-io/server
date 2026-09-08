# TeleCrypt.io server state

Public runtime configuration for the TeleCrypt Matrix service:

Current TeleCrypt project facts and decisions are maintained only in the canonical
[`llms.txt`](https://telecrypt.io/llms.txt); this README documents this repository's deployment
composition and release contract.

## Configuration and activation

1. Obtain the private deployment procedure and secret-file contract from the TeleCrypt Harness
   maintained by the operator.
2. Use the Harness guarded activator for every production validation and activation. It verifies
   the exact state release, rendered Compose and Caddy configuration, published images,
   `--no-build` activation, and the result record.
3. Do not run direct `docker compose pull`, `up`, `run`, or equivalent production activation
   commands from this public repository. The repository workflow validates public state; Harness
   performs the guarded VM preflight and owns private environment and secret handling.

`versions.env` is the canonical image coordinate manifest and must contain exactly these five keys:
`CADDY_IMAGE`, `SYNAPSE_IMAGE`, `MAS_IMAGE`, `CONTROLPLANE_IMAGE`, and `CASHIER_IMAGE`. The private
environment, derived backend and public-site hostnames, ingress binding, identity overlays, and
secret-file contract are maintained by the operator's private Harness. Harness snapshots the
private Janitor, Plan, and Cashier records and exports each service's exact environment contract
only to the guarded Compose process; Compose does not read live service `env_file` paths. The
committed `.env.example` contains TEST-NET documentation values only; replace them through the private
deployment procedure before activation.

The Matrix private inputs are `${TELECRYPT_DATA_DIR}/secrets/synapse.secrets.json`,
`${TELECRYPT_DATA_DIR}/secrets/synapse_signing.key`, and `${TELECRYPT_DATA_DIR}/secrets/mas.secrets.json`;
Harness validates their bounded contracts before passing them as file-backed Compose secrets; the
signing key is mounted as `/signing.key`. The MAS overlay contains its encryption/signing secrets,
database URI, Matrix shared secret, and two exact environment-bound clients. Synapse loads the
committed base, then the exact tracked nonsecret profile selected by `SERVER_NAME`, then its private
JSON overlay, and finally the runtime identity layer. The two profile files contain only the explicit
request-mutation limiters: production keeps Synapse's standard `rc_message` (`per_second: 0.2`,
`burst_count: 10`) and `rc_room_creation` (`per_second: 0.016`, `burst_count: 10`), while stage uses
finite `per_second: 1000` and `burst_count: 1000` values for both settings so parallel acceptance
tests do not spend their time in Synapse's production throttles. Synapse's config files are
shallow-merged by top-level key, so its private overlay owns each complete `database` and
`matrix_authentication_service` map; the committed base and profile contain no partial map that
could overwrite it.
Email and policy defaults remain in `mas.yaml`; the final runtime identity layer supplies the Janitor
admin-client ID. The committed base configs retain reviewed nonsecret loader options, while
credentials, database URIs, OAuth client secrets, and provider values remain outside this repository.

## Billing operations

The operator's private Harness owns billing-environment procedures, provider authority, private-input
handling, and billing acceptance. Current public billing facts and decisions remain in the canonical
[`llms.txt`](https://telecrypt.io/llms.txt); this repository retains only its configuration assembly
and release contract.

## Releases

This repository contains declarative state only. It publishes no packages, images, deployment
tooling, secret templates, binaries, or wheels. Each exact state Release carries one deterministic
JSON manifest binding the five selected image coordinates to their observed registry digests. Before
that manifest is published, the workflow verifies live immutable GitHub Release and annotated-tag
evidence for the public Synapse and Controlplane repositories. Every image entry in the published
manifest contains only its selected coordinate and digest; the private Harness owns deployment
operations and the secret-file contract.

A deliberately pushed, reviewed state tag receives an exact `server-state-<short-git-sha>` GitHub
Release record through a draft-first flow: the workflow verifies the complete draft metadata and
asset bytes before publishing, and resumes only an exact draft. A pre-existing published Release is
refused. It selects exact component image releases, which must already be published and verified. The
private Cashier immutable-Release check is intentionally an owner-authenticated local Harness gate
performed before Server State selection; the hosted workflow validates Cashier only from its selected
public GHCR digest and the exact OCI source, version, and revision labels. The Release's single JSON asset binds those selected tags to their observed canonical
registry digests for Harness preflight. `versions.env` is the one canonical image coordinate manifest
with exactly the five image keys used by Compose (`CADDY_IMAGE`, `SYNAPSE_IMAGE`, `MAS_IMAGE`,
`CONTROLPLANE_IMAGE`, and `CASHIER_IMAGE`); the workflow
rejects any Compose image tag, first-party image label, default command, entrypoint, user, route, or
public-origin contract that differs from the selected release contract. The state release is an
identity for one configuration commit, not a package version. Controlplane and Cashier images
advertise config contract `1`, and trusted exact state-tag runs of the public workflow
authenticate to GHCR to verify both first-party images as well as the public images; main and
pull-request runs receive the exact local contract checks without registry credentials. Do not change
`versions.env` or `compose.yml` independently; update their exact coordinates and contracts together
in one reviewed exact state change.

## Security and licence

Do not commit `.env`, populated secret templates, signing keys, or deployment inventory. Report
security issues according to [SECURITY.md](./SECURITY.md).

Licensed under [BUSL-1.1](./LICENSE); converts to Apache-2.0 on 2030-07-20.
