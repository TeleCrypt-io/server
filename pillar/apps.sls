# These existing released image pins must be replaced with the new cross-host release images
# before the fresh-host app highstate is applied. Platform package versions are owned by
# matrix-salt/pillar/runtime.sls.
versions:
  images:
    cashier: ghcr.io/telecrypt-io/telecrypt-cashier:0.4.39
    controlplane: ghcr.io/telecrypt-io/controlplane:0.5.54
