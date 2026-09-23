# TeleCrypt.io server configuration

This repository is the immutable source for a TeleCrypt VM release. It contains the Caddy,
Matrix, systemd/Quadlet and Salt files needed to prepare a host and run one exact image manifest.
Credentials and populated environment files stay outside Git in the Salt master's private Pillar.

## Salt deployment

The Salt master runs on the private Harness host. Its file root points at one extracted, published
`server-state-*` release, and its Pillar contains the target profile, release tag and private
runtime values. The VM runs a Salt minion and initiates the connection to the master; no SSH is
needed for normal deployment or diagnostics. Direct SSH remains an owner recovery path.

The operator activates a verified release with the following two commands from Harness:

```sh
sudo salt-key -a stage
sudo salt stage state.apply salt.host
sudo salt stage state.apply salt.deploy
sudo salt stage state.apply salt.services
```

The `salt.deploy` state reads `server-state-images.json` from the selected master file root,
pulls each image by its recorded digest, switches `/home/ubuntu/salt_config/current`, and applies
the runtime inputs and service definitions. It restarts only services whose effective inputs
changed; pod-level changes recreate the shared pod. Repeating it with the same release is a no-op.
`salt.services` keeps the boot target and Janitor timer enabled.

Before the first activation, extract the exact server release into the master's private
`releases/<tag>` directory and place its matching release asset beside it as
`server-state-images.json`; then update `releases/current` to that directory. Do not point the
master at a mutable checkout or a branch.

The new VM bootstrap command is generated from the master's actual address and public-key
fingerprint after the master is installed. It installs the pinned Salt minion, configures the
master address and fingerprint, and starts the minion. The VM image is expected to contain the
owner's recovery SSH key; Salt does not replace `authorized_keys`.

Store each target's exact secret files under
`~/salt_secrets/hosts/<minion-id>/secrets/`. The master's built-in
`file_tree` Pillar exposes only the matching target's files as Pillar values, and `salt.deploy`
writes them to `/home/ubuntu/salt_config/secrets/` with their required private modes. Cashier's
existing private configuration remains in `cashier.secrets.env`. Three separate files carry the
Cashier service credentials: `cashier-plan-token.env` contains only `CASHIER_PLAN_TOKEN`,
`cashier-synapse-token.env` only `CASHIER_SYNAPSE_TOKEN`, and `cashier-janitor-token.env` only
`CASHIER_JANITOR_TOKEN`. Generate each environment's three independent 32-byte random values
with `openssl rand -hex 32`, and store them as 64 lowercase hexadecimal characters. Keep Stage
and Production credentials independent. The source files under the master's private tree remain
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

See [`LICENSE`](./LICENSE) for licensing.
