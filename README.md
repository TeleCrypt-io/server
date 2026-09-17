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
pulls each image by its recorded digest, switches `/home/ubuntu/salt_config/current`, and starts
the tracked `telecrypt.target`. Repeating it with the same release is a no-op. `salt.services`
keeps the boot target and Janitor timer enabled.

Before the first activation, extract the exact server release into the master's private
`releases/<tag>` directory and place its matching release asset beside it as
`server-state-images.json`; then update `releases/current` to that directory. Do not point the
master at a mutable checkout or a branch.

The new VM bootstrap command is generated from the master's actual address and public-key
fingerprint after the master is installed. It installs the pinned Salt minion, configures the
master address and fingerprint, and starts the minion. The VM image is expected to contain the
owner's recovery SSH key; Salt does not replace `authorized_keys`.

See [`LICENSE`](./LICENSE) for licensing.
