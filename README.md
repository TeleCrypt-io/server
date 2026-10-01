# TeleCrypt.io server configuration

This repository is the immutable source for a TeleCrypt VM release. It contains the Caddy,
Matrix, systemd/Quadlet and Salt files needed to prepare a host and run one exact image manifest.
Credentials and populated environment files stay outside Git in Harness's private secret files.

## Salt deployment

Harness runs Salt SSH with a private roster and verified SSH host keys. Its file root points
at one extracted, published `server-state-*` release, and its Pillar contains the target profile,
release tag and private runtime values. The VM needs SSH, Python 3 and the operator's sudo
access; neither a Salt master daemon nor a minion daemon is required.

Activate a verified release from Harness:

```sh
salt-ssh --config-dir=/home/ubuntu/harness.git/servers_salt_configs stage state.apply salt.host
salt-ssh --config-dir=/home/ubuntu/harness.git/servers_salt_configs stage state.apply salt.deploy
salt-ssh --config-dir=/home/ubuntu/harness.git/servers_salt_configs stage state.apply salt.services
```

The `salt.deploy` state reads `server-state-images.json` from the selected file root,
pulls each image by its recorded digest, switches `/home/ubuntu/salt_config/current`, and applies
the runtime inputs and service definitions. It reloads the user's systemd manager so generated
Quadlet units reflect the deployed files, then restarts only services whose effective inputs
changed; pod-level changes recreate the shared pod. Repeating it with the same release does not
restart unchanged services.
`salt.services` keeps the boot target and Janitor timer enabled.

Before the first activation, extract the exact server release into Harness's private
`releases/<tag>` directory and place its matching release asset beside it as
`server-state-images.json`; then update `releases/current` to that directory. Do not point the
file root at a mutable checkout or a branch.

Provision new VMs with the owner's SSH public key, Python 3 and sudo access, verify their SSH
host keys, and add their private roster entries on Harness. Salt does not replace
`authorized_keys`. Applying `salt.host` through Salt SSH disables an existing Salt minion and
removes its obsolete TeleCrypt configuration.

Store each target's exact secret files under
`~/salt_secrets/hosts/<roster-id>/secrets/`, with `~/salt_secrets` as a private Salt file root.
The runtime states select `salt://hosts/<roster-id>/secrets/<name>` using the target's Salt ID.
Salt SSH packages those referenced files and `salt.deploy` copies their original bytes to
`/home/ubuntu/salt_config/secrets/` with the required private modes. Secrets are not templated
or embedded in Pillar. Cashier's
existing private configuration remains in `cashier.secrets.env`. Three separate files carry the
Cashier service credentials: `cashier-plan-token.env` contains only `CASHIER_PLAN_TOKEN`,
`cashier-synapse-token.env` only `CASHIER_SYNAPSE_TOKEN`, and `cashier-janitor-token.env` only
`CASHIER_JANITOR_TOKEN`. Generate each environment's three independent 32-byte random values
with `openssl rand -hex 32`, and store them as 64 lowercase hexadecimal characters. Keep Stage
and Production credentials independent. The source files under Harness's private tree remain
mode `0640` for Salt's reader group; Salt writes target copies as mode `0600` inside the mode
`0700` secrets directory. Cashier reads all three; Plan, Synapse, and Janitor each read only
their matching file. Do not provide these token files to Caddy, Registration, MAS, or LiveKit JWT.
These files are required private inputs for each target and must remain outside this repository.

`dodo-webhook.env` contains only `DODO_WEBHOOK_PATH`; Caddy reads it as a systemd environment file
and passes only that variable into its container. `cashier-dodo-webhook-secret.env` contains only
`DODO_WEBHOOK_SECRET` and is mounted into Cashier alone. Move the existing webhook secret value
from `cashier.secrets.env` into that Cashier-only file when updating each target's private inputs.
Keep `dodo-webhook.env` path-only and keep one authoritative copy of the secret. The Dodo
read-only API key belongs only in Janitor's private environment.

## TLS ingress

HAProxy passes TCP through to the VM's private port 8443 and supplies the original client
address using PROXY protocol. Caddy terminates TLS inside the shared pasta pod, and routes
requests directly to the application loopback listeners. Set `server.ingress_bind_address`
to the VM's private address and `server.ingress_proxy_cidr` to the actual HAProxy peer's CIDR.
Caddy requires PROXY protocol from that peer; port 8080 is no longer published.

Caddy renews certificates with the TLS-ALPN challenge through public port 443. HTTP/3 and
HTTP redirects are disabled because the external ingress forwards only TLS over TCP.
Certificate and ACME data persist at `/home/ubuntu/salt_config/runtime/tls-ingress/data`;
keep this directory across releases. Salt retires the former standalone TLS ingress container
before the shared pod binds port 8443, retaining its existing certificates.

## Manual release

Run releases from an operator checkout on Harness. GitHub Actions does not assemble releases.
Install the release tools once: Podman 4.9.3 (matching Stage), Salt at `salt/version`,
`skopeo`, `gh`, `jq`, OpenSSL, and Python 3. Authenticate `gh` for this repository and
`skopeo login ghcr.io` when private image access requires it; keep credentials outside Git.

Run `./scripts/check.sh` to validate Caddy and systemd/Quadlet, render the Salt states with
an isolated example Pillar, and execute activation receipt transition tests. This reuses the
local Caddy image and installed tools; it does not install packages or alter Harness's
configuration. These checks supplement the required real Stage end-to-end acceptance.

Select exact published Synapse, Controlplane and Cashier image tags. To check the selection
and resolve all six image digests without publishing:

```sh
./scripts/release.sh --check 1.159-tc34 0.5.54 0.4.39
```

After committing and pushing the source, publish that same selection from a clean checkout:

```sh
./scripts/release.sh 1.159-tc34 0.5.54 0.4.39
```

The command repeats the checks, resolves canonical registry digests, and creates an annotated
`server-state-<commit>-<UTC YYYYMMDDhhmmss>` tag and its matching immutable
`<tag>-images.json` release asset. It downloads the asset again and compares its contents.
Existing release tags/assets are never overwritten. If publication is interrupted, inspect
the reported GitHub tag/release before retrying. The command does not deploy; use the Harness
runbook to activate and verify Stage. Production remains frozen until the owner's instruction.

See [`LICENSE`](./LICENSE) for licensing.
