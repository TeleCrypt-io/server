#!/usr/bin/env bash
set -euo pipefail

tag="${1:?release tag required}"
asset="${2:?manifest asset name required}"
manifest="${3:?manifest file required}"
repository="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

manifest_digest="sha256:$(sha256sum "$manifest" | awk '{print $1}')"
manifest_size="$(wc -c <"$manifest")"
release_json="$(mktemp)"
download_dir="$(mktemp -d)"
trap 'rm -f -- "$release_json"; rm -rf -- "$download_dir"' EXIT

gh api --hostname github.com "repos/$repository/releases/tags/$tag" >"$release_json"
if ! jq -e --arg tag "$tag" --arg asset "$asset" --arg digest "$manifest_digest" \
  --argjson size "$manifest_size" '
  .tag_name == $tag and .name == $tag and .draft == false and .prerelease == false and .immutable == true and
  (.assets | type == "array" and length == 1) and
  .assets[0].name == $asset and .assets[0].label == "" and .assets[0].state == "uploaded" and
  .assets[0].size == $size and .assets[0].digest == $digest
' "$release_json" >/dev/null; then
  echo 'published release metadata did not match the selected manifest' >&2
  cat -- "$release_json" >&2
  exit 1
fi

gh release download "$tag" --repo "$repository" --pattern "$asset" --dir "$download_dir"
cmp -- "$manifest" "$download_dir/$asset"
test "sha256:$(sha256sum "$download_dir/$asset" | awk '{print $1}')" = "$manifest_digest"
printf 'Verified immutable release %s and manifest %s\n' "$tag" "$asset"
