#!/usr/bin/env bash
# Resolve published images and publish an annotated Server State release.
set -euo pipefail
cd "$(dirname "$0")/.."
check_only=false
if [[ ${1:-} == --check ]]; then
  check_only=true
  shift
fi
reuse_tag=''
if [[ $# == 2 && $1 == --reuse-images ]]; then
  reuse_tag=$2
  [[ $reuse_tag =~ ^server-state-[0-9a-f]{7,10}-[1-9][0-9]*$ ]]
  # This mode takes every image from the verified manifest below.
  source scripts/images.sh 0.0-tc0 0.0.0 0.0.0
elif [[ $# == 3 ]]; then
  [[ $1 =~ ^[0-9]+\.[0-9]+-tc[0-9]+$ ]]
  [[ $2 =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
  [[ $3 =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
  source scripts/images.sh "$@"
else
  echo 'Usage: scripts/release.sh [--check] SYNAPSE_TAG CONTROLPLANE_TAG CASHIER_TAG' >&2
  echo '   or: scripts/release.sh [--check] --reuse-images SERVER_STATE_TAG' >&2
  exit 2
fi
./scripts/check.sh >&2
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
images='{}'
if [[ -n $reuse_tag ]]; then
  asset_name="${reuse_tag}-images.json"
  gh api "repos/$repo/releases/tags/$reuse_tag" | jq -e \
    --arg tag "$reuse_tag" --arg asset "$asset_name" \
    '.tag_name == $tag and .immutable == true and .draft == false
     and any(.assets[]; .name == $asset)' >/dev/null
  tag_ref=$(gh api "repos/$repo/git/ref/tags/$reuse_tag")
  jq -e '.object.type == "tag"' <<< "$tag_ref" >/dev/null
  tag_sha=$(jq -r .object.sha <<< "$tag_ref")
  source_commit=$(gh api "repos/$repo/git/tags/$tag_sha" \
    --jq 'select(.object.type == "commit") | .object.sha')
  manifest=$(gh release download "$reuse_tag" --repo "$repo" --pattern "$asset_name" --output -)
  expected_keys=$(printf '%s\n' "${IMAGE_KEYS[@]}" | jq -R . | jq -s sort)
  jq -e --arg tag "$reuse_tag" --arg annotated "$tag_sha" \
    --arg commit "$source_commit" --argjson keys "$expected_keys" \
    '.schema_version == 1 and .server_state_tag == $tag
     and .annotated_tag_sha == $annotated and .source_commit == $commit
     and (.images | keys) == $keys
     and all(.images[]; (.image | type == "string")
       and (.digest | test("^sha256:[0-9a-f]{64}$")))' <<< "$manifest" >/dev/null || {
      echo "Invalid source manifest or tag identity: $reuse_tag" >&2
      exit 1
    }
  images=$(jq .images <<< "$manifest")
  printf 'Reusing exact image manifest from %s\n' "$reuse_tag" >&2
fi
for key in "${IMAGE_KEYS[@]}"; do
  if [[ -n $reuse_tag ]]; then
    image=$(jq -r --arg key "$key" '.[$key].image' <<< "$images")
    digest=$(jq -r --arg key "$key" '.[$key].digest' <<< "$images")
  else
    image=${!key}
    digest=$(skopeo inspect --no-tags --format '{{.Digest}}' "docker://$image")
    [[ $digest =~ ^sha256:[0-9a-f]{64}$ ]]
  fi
  # First-party images must match the exact immutable published product release.
  product_repo=''
  case "$key" in
    SYNAPSE_IMAGE) product_repo=TeleCrypt-io/synapse-server ;;
    CONTROLPLANE_IMAGE) product_repo=TeleCrypt-io/control-plane ;;
    CASHIER_IMAGE) product_repo=TeleCrypt-io/cashier ;;
  esac
  if [[ -n $product_repo ]]; then
    tag=${image##*:}
    image_name=${image%:*}
    asset_name="${image_name##*/}-${tag}.digest.json"
    printf 'Checking immutable %s release %s against selected digest\n' "$product_repo" "$tag" >&2
    gh api "repos/$product_repo/releases/tags/$tag" | jq -e \
      --arg tag "$tag" --arg asset "$asset_name" \
      '.tag_name == $tag and .immutable == true and .draft == false
       and any(.assets[]; .name == $asset)' >/dev/null || {
        echo "Missing immutable published release or digest asset: $product_repo $tag" >&2
        exit 1
      }
    tag_ref=$(gh api "repos/$product_repo/git/ref/tags/$tag")
    jq -e '.object.type == "tag"' <<< "$tag_ref" >/dev/null
    tag_sha=$(jq -r .object.sha <<< "$tag_ref")
    source_commit=$(gh api "repos/$product_repo/git/tags/$tag_sha" \
      --jq 'select(.object.type == "commit") | .object.sha')
    gh release download "$tag" --repo "$product_repo" --pattern "$asset_name" --output - \
      | jq -e --arg image "$image_name" --arg tag "$tag" --arg digest "$digest" \
        --arg annotated "$tag_sha" --arg commit "$source_commit" \
        '.schema_version == 1 and .image == $image and .tag == $tag
         and .digest == $digest and .annotated_tag_sha == $annotated
         and .source_commit == $commit' >/dev/null || {
        echo "Release digest asset does not match selected image and source tag: $product_repo $tag" >&2
        exit 1
      }
    printf 'Verified %s release %s and image digest\n' "$product_repo" "$tag" >&2
  fi
  images=$(jq --arg key "$key" --arg image "$image" --arg digest "$digest" \
    '. + {($key): {image: $image, digest: $digest}}' <<< "$images")
done
if "$check_only"; then
  jq . <<< "$images"
  exit 0
fi
# The tag and checks must describe exactly the committed source being published.
test -z "$(git status --porcelain)"
commit=$(git rev-parse HEAD)
release_tag="server-state-${commit:0:8}-$(date -u +%Y%m%d%H%M%S)"
# Creating a new annotated tag/ref fails if the immutable name already exists.
annotated_tag_sha=$(gh api --method POST "repos/$repo/git/tags" \
  -f tag="$release_tag" -f message="Server State $release_tag" \
  -f object="$commit" -f type=commit --jq .sha)
gh api --method POST "repos/$repo/git/refs" \
  -f ref="refs/tags/$release_tag" -f sha="$annotated_tag_sha" >/dev/null
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
manifest_name="${release_tag}-images.json"
jq -n --arg tag "$release_tag" --arg commit "$commit" \
  --arg annotated "$annotated_tag_sha" --argjson images "$images" \
  '{schema_version: 1, server_state_tag: $tag, source_commit: $commit,
    annotated_tag_sha: $annotated, images: $images}' > "$work_dir/$manifest_name"
gh release create "$release_tag" "$work_dir/$manifest_name" --repo "$repo" \
  --title "$release_tag" --notes "Server State image digest manifest for commit $commit." \
  --target "$commit" --verify-tag
mkdir "$work_dir/readback"
gh release download "$release_tag" --repo "$repo" --pattern "$manifest_name" \
  --dir "$work_dir/readback"
cmp "$work_dir/$manifest_name" "$work_dir/readback/$manifest_name"
test "$(gh api "repos/$repo/git/ref/tags/$release_tag" --jq .object.type)" = tag
printf 'Published %s\n' "$release_tag"
