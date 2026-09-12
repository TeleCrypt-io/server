#!/usr/bin/env bash
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${METADATA_DIR:?METADATA_DIR is required}"

MAX_RELEASE_ASSET_BYTES=1048576
captured_stderr_files=()

# shellcheck disable=SC1091
source .github/scripts/release-helpers.sh

capture_api() {
  local replay_output=true
  if [[ "${1:-}" == --binary-output ]]; then
    replay_output=false
    shift
  fi
  local output="$1" phase="$2" repository="$3" tag="$4" status=0
  shift 4
  local stderr="$output.stderr"
  captured_stderr_files+=("$stderr")
  if [[ "$replay_output" == true ]]; then
    if capture_command "$output" "$stderr" 60 gh api "$@"; then
      return 0
    else
      status="$?"
    fi
  else
    if capture_command --binary-output "$output" "$stderr" 60 gh api "$@"; then
      return 0
    else
      status="$?"
    fi
  fi
  echo "GitHub API request failed (phase=$phase repository=$repository tag=$tag; status $status)" >&2
  return "$status"
}

validate_api_json() {
  local output="$1" phase="$2" repository="$3" tag="$4" status
  shift 4
  if jq -e "$@" "$output" >/dev/null; then
    return 0
  else
    status="$?"
  fi
  echo "GitHub API response failed semantic validation (phase=$phase repository=$repository tag=$tag)" >&2
  replay_capture "$output" "$output.stderr" ||
    echo "GitHub API response diagnostics could not be replayed (phase=$phase repository=$repository tag=$tag)" >&2
  return "$status"
}

extract_api_json() {
  local variable="$1" output="$2" phase="$3" repository="$4" tag="$5" value status
  shift 5
  if value="$(jq -er "$@" "$output")"; then
    printf -v "$variable" '%s' "$value"
    return 0
  else
    status="$?"
  fi
  echo "GitHub API response failed semantic extraction (phase=$phase repository=$repository tag=$tag)" >&2
  replay_capture "$output" "$output.stderr" ||
    echo "GitHub API response diagnostics could not be replayed (phase=$phase repository=$repository tag=$tag)" >&2
  return "$status"
}

# shellcheck disable=SC1091
source versions.env
mkdir -p "$METADATA_DIR"
cleanup_captured_stderr() {
  local status=$? cleanup_status=0 stderr_file
  trap - EXIT
  for stderr_file in "${captured_stderr_files[@]}"; do
    if ! rm -f -- "$stderr_file"; then
      cleanup_status=1
      echo "GitHub API stderr cleanup failed: $stderr_file" >&2
    fi
  done
  if [[ "$status" -eq 0 && "$cleanup_status" -ne 0 ]]; then
    status=1
  fi
  exit "$status"
}
trap cleanup_captured_stderr EXIT

fetch_release_asset() {
  local key="$1" image="$2" repository="$3" asset_name="$4"
  local tag="${image##*:}"
  local release_path="$METADATA_DIR/$key.release.json"
  local asset_path="$METADATA_DIR/$key.release.asset"
  local tag_ref_path="$METADATA_DIR/$key.annotated-tag-ref.json"
  local annotated_tag_path="$METADATA_DIR/$key.annotated-tag.json"
  local api_root="https://api.github.com/repos/$repository"
  local annotated_tag_sha
  capture_api "$tag_ref_path" tag-ref "$repository" "$tag" \
    --hostname github.com \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2026-03-10' \
    "repos/$repository/git/ref/tags/$tag"
  extract_api_json annotated_tag_sha "$tag_ref_path" tag-ref "$repository" "$tag" \
    --arg ref "refs/tags/$tag" --arg url "$api_root/git/refs/tags/$tag" \
    '. | select(type == "object" and .ref == $ref and .url == $url) |
     .object | select(type == "object" and .type == "tag" and
       (.sha | type == "string" and test("^[0-9a-f]{40}$"))) | .sha'
  capture_api "$annotated_tag_path" annotated-tag "$repository" "$tag" \
    --hostname github.com \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2026-03-10' \
    "repos/$repository/git/tags/$annotated_tag_sha"
  validate_api_json "$annotated_tag_path" annotated-tag "$repository" "$tag" \
    --arg tag "$tag" --arg sha "$annotated_tag_sha" --arg commit_url "$api_root/git/commits/" \
    --arg object_url "$api_root/git/tags/$annotated_tag_sha" \
    '. | select(type == "object" and .sha == $sha and .tag == $tag and .url == $object_url) |
     .object as $target | $target | select(type == "object" and .type == "commit" and
       (.sha | type == "string" and test("^[0-9a-f]{40}$")) and
       ($target.url | type == "string" and . == ($commit_url + $target.sha)))'
  capture_api "$release_path" release "$repository" "$tag" \
    --hostname github.com \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2026-03-10' \
    "repos/$repository/releases/tags/$tag"
  local asset_id
  extract_api_json asset_id "$release_path" release "$repository" "$tag" \
    --arg asset "$asset_name" '.assets | map(select(.name == $asset)) |
    if length == 1 then .[0].id else error end |
    select(type == "number" and . == floor and . > 0)'
  capture_api --binary-output "$asset_path" asset "$repository" "$tag" \
    --hostname github.com \
    --header 'Accept: application/octet-stream' \
    --header 'X-GitHub-Api-Version: 2026-03-10' \
    "repos/$repository/releases/assets/$asset_id"
  if [[ ! -s "$asset_path" ]]; then
    echo "GitHub release asset was empty (repository=$repository tag=$tag asset=$asset_name)" >&2
    replay_capture "$release_path" "$release_path.stderr" ||
      echo "GitHub release response diagnostics could not be replayed (repository=$repository tag=$tag)" >&2
    return 1
  fi
  if [[ "$(wc -c < "$asset_path")" -gt "$MAX_RELEASE_ASSET_BYTES" ]]; then
    echo "GitHub release asset exceeded the supported size (repository=$repository tag=$tag asset=$asset_name)" >&2
    replay_capture "$release_path" "$release_path.stderr" ||
      echo "GitHub release response diagnostics could not be replayed (repository=$repository tag=$tag)" >&2
    return 1
  fi
  local expected_asset_size
  extract_api_json expected_asset_size "$release_path" release "$repository" "$tag" \
    --arg asset "$asset_name" '.assets | map(select(.name == $asset)) |
    if length == 1 then .[0].size else error end |
    select(type == "number" and . == floor and . > 0)'
  if [[ "$(wc -c < "$asset_path")" -ne "$expected_asset_size" ]]; then
    echo "GitHub release asset size mismatch (repository=$repository tag=$tag asset=$asset_name)" >&2
    replay_capture "$release_path" "$release_path.stderr" ||
      echo "GitHub release response diagnostics could not be replayed (repository=$repository tag=$tag)" >&2
    return 1
  fi
}

fetch_release_asset SYNAPSE_IMAGE "$SYNAPSE_IMAGE" TeleCrypt-io/telecrypt-synapse \
  "telecrypt-synapse-${SYNAPSE_IMAGE##*:}.digest.json"
fetch_release_asset CONTROLPLANE_IMAGE "$CONTROLPLANE_IMAGE" TeleCrypt-io/controlplane \
  "controlplane-${CONTROLPLANE_IMAGE##*:}.digest.json"
