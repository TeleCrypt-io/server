# TeleCrypt application host

This Salt source owns Cashier, Plan, Registration, and Janitor on one rootless Podman pod. PostgreSQL remains external. Matrix and LiveKit run on separate hosts.

The shared state top selects this role with `deployment.role: apps`. It includes the shared OS state, `apps.svc`, and the shared private ingress state. The shared file and Pillar roots provide the Salt user-service module, `salt-operator`, `salt-user-manager`, platform package versions, and HAProxy resources. `pillar/apps.sls` owns only the Cashier and Controlplane image selections; runtime package versions come from the shared Pillar.

The private target Pillar supplies `site.server_name`, `site.billing_environment`, `deployment.environment`, `deployment.role`, `network.private_address`, `network.matrix_address`, `network.ssh_port`, `endpoints.mas_admin_url`, `endpoints.mas_internal_url`, `endpoints.synapse_admin_url`, and `ingress.dodo_webhook_path`. Its top selects shared runtime/app settings and host settings, then includes the invocation's generated `deployment` Pillar containing only the source commit. Extend the Matrix repository’s private example tree with `examples/pillar/hosts/apps/settings.sls`
and merge the `apps` entry from this repository’s example `top.sls` into the existing private top.
The shared `shared/stage.sls` owns site identity and the payment-webhook path once for both roles. Keep credentials in the per-host input files below; do not merge them into one environment file.

The image pins in `pillar/apps.sls` identify the currently released app baseline. Replace them with the new cross-host release images before applying the fresh-host app highstate.

Salt reads these files from `hosts/<target>/secrets/`:

- `cashier.secrets.env`
- `cashier-plan-token.env`
- `cashier-synapse-token.env`
- `cashier-janitor-token.env`
- `cashier-dodo-webhook-secret.env`
- `plan.secrets.env`
- `janitor.secrets.env`

Cashier, Plan, and Registration bind inside the `apps` pod. The pod publishes ports 9009, 9011, and 9012 only on host loopback for HAProxy. Cashier, Plan, Registration, and the one-shot Janitor service are native Quadlet resources (`apps-pod`, `cashier`, `plan`, `registration`, and `janitor`). A daily systemd timer targets `janitor.service`. Applying Salt starts the timer after Cashier and Plan; it does not start the Janitor service.

All three app-to-Matrix service URLs use the Matrix private HAProxy listener on port 8080. Compile the app states through the combined Harness Salt roots with `salt-call --local state.show_sls apps.svc`. Render checks do not replace Stage workflow acceptance.

See `LICENSE` for licensing.
