# shellcheck shell=bash
# Values are consumed by sourcing scripts, including indirect expansion.
# shellcheck disable=SC2034
# Image tags selected for a Server State release. Application tags are operator inputs.
CADDY_IMAGE=docker.io/caddy:2.11.4-alpine
SYNAPSE_IMAGE=ghcr.io/telecrypt-io/telecrypt-synapse:${1:?Synapse tag required}
MAS_IMAGE=ghcr.io/element-hq/matrix-authentication-service:1.24.0
CONTROLPLANE_IMAGE=ghcr.io/telecrypt-io/controlplane:${2:?Controlplane tag required}
CASHIER_IMAGE=ghcr.io/telecrypt-io/telecrypt-cashier:${3:?Cashier tag required}
LK_JWT_IMAGE=ghcr.io/element-hq/lk-jwt-service:0.7.0
IMAGE_KEYS=(CADDY_IMAGE SYNAPSE_IMAGE MAS_IMAGE CONTROLPLANE_IMAGE CASHIER_IMAGE LK_JWT_IMAGE)
