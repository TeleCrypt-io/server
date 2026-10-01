#!/usr/bin/env bash
# Run release checks locally, without changing the host Salt configuration.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/images.sh 0.0-tc0 0.0.0 0.0.0
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
podman run --rm \
  -e SERVER_NAME=stage.example.invalid \
  -e INGRESS_PROXY_CIDR=192.0.2.1/32 \
  -e DODO_WEBHOOK_PATH="/payment_webhook_$(openssl rand -hex 32)" \
  -v "$PWD:/work:ro" \
  "$CADDY_IMAGE" caddy validate --config /work/Caddyfile --adapter caddyfile

test "$(podman --version)" = 'podman version 4.9.3'
QUADLET_UNIT_DIRS="$PWD/systemd/quadlet" \
  /usr/lib/systemd/user-generators/podman-user-generator --dryrun --no-kmsg-log \
  > "$work_dir/generated-units"
test -s "$work_dir/generated-units"
systemd-analyze verify systemd/telecrypt-pod.service systemd/telecrypt.target

test "$(salt-call --version | awk '{print $2}')" = "$(<salt/version)"
mkdir -p "$work_dir/root" "$work_dir/pillar" "$work_dir/config"
# Salt renders the working files, including uncommitted edits, in an isolated file root.
cp -a salt systemd "$work_dir/root/"
cp salt/pillar/top.sls "$work_dir/pillar/top.sls"
cp salt/pillar/telecrypt.sls.example "$work_dir/pillar/telecrypt.sls"
cat > "$work_dir/config/minion" <<CONFIG
id: local
file_client: local
cachedir: $work_dir/cache
pki_dir: $work_dir/pki
log_file: $work_dir/salt.log
CONFIG
images='{}'
for key in "${IMAGE_KEYS[@]}"; do
  images=$(jq --arg key "$key" --arg image "${!key}" \
    '. + {($key): {image: $image, digest: ("sha256:" + ("0" * 64))}}' <<< "$images")
done
jq -n --argjson images "$images" '{schema_version: 1,
  server_state_tag: "server-state-REPLACE_WITH_RELEASE_TAG",
  source_commit: ("0" * 40), annotated_tag_sha: ("0" * 40), images: $images}' \
  > "$work_dir/root/server-state-images.json"
for state in salt.host salt.services salt.release salt.deploy; do
  salt-call --config-dir="$work_dir/config" --local --retcode-passthrough --out=json \
    --file-root="$work_dir/root" --pillar-root="$work_dir/pillar" \
    state.show_sls "$state" > "$work_dir/${state//./-}-render"
done
./tests/test_activation_receipt.py "$work_dir/salt-deploy-render"
