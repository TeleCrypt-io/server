#!/usr/bin/env bash

container_sensitive_failure_class() {
  case "${1:-}" in
    success|uid|mount-content|secrets-json|forbidden-mount|environment-leak)
      printf '%s\n' "$1"
      ;;
    *) return 1 ;;
  esac
}

container_sensitive_marker_class() {
  local output="${1:-}" candidate
  [[ -f "$output" ]] || return 1
  candidate="$(awk '
    NR == 1 && $0 ~ /^telecrypt-synapse-proof:(success|uid|mount-content|secrets-json|forbidden-mount|environment-leak)$/ {
      class = $0
      sub(/^telecrypt-synapse-proof:/, "", class)
      next
    }
    { invalid = 1 }
    END {
      if (NR == 1 && !invalid) print class
    }
  ' "$output")" || return 1
  container_sensitive_failure_class "$candidate"
}

container_sensitive_preflight_failure_class() {
  case "${1:-}" in
    image-pull|registry-auth|mount-source|entrypoint-executable|compose-secrets|compose-config|runtime-permission|file-shape|oci-runtime|daemon-resource|timeout|unknown)
      printf '%s\n' "$1"
      ;;
    *) return 1 ;;
  esac
}

container_sensitive_preflight_class() {
  local stderr_file="${1:-}" candidate
  [[ -f "$stderr_file" ]] || return 1
  candidate="$(awk '
    {
      line = tolower($0)
      if (line ~ /timed[[:space:]]+out|timeout|i\/o timeout|deadline exceeded|context deadline/) {
        print "timeout"
        exit
      }
      if (line ~ /unauthorized|authentication required|authentication failed|pull access denied|denied: requested access|requested access to the resource is denied|insufficient_scope|login required|may require.*docker login/) {
        print "registry-auth"
        exit
      }
      if (line ~ /required variable[^[:alnum:]]+.*(not set|is required|missing|empty)|variable[^[:alnum:]]+.*(not set|is required|missing|empty)|interpolation|invalid compose (file|configuration)|compose[^[:alnum:]]+(config|file)[^[:alnum:]]+.*(invalid|failed|error)|additional property.*(not allowed|is required)|refers to undefined|external[^[:alnum:]]+.*could not be found/) {
        print "compose-config"
        exit
      }
      if (line ~ /manifest unknown|no matching manifest|failed to (resolve|pull|fetch)|failed to copy|image[^[:alnum:]]+not found|repository[^[:alnum:]]+not found/) {
        print "image-pull"
        exit
      }
      if (line ~ /executable file not found|exec format error|oci runtime create failed.*exec|exec[^[:alnum:]]+.*(not found|no such file)|cannot start service.*exec/) {
        print "entrypoint-executable"
        exit
      }
      if (line ~ /invalid mount config|mounts denied|bind source path does not exist|source path[^[:alnum:]]+does not exist|mount[^[:alnum:]]+(source|no such file|does not exist)/) {
        print "mount-source"
        exit
      }
      if (line ~ /secret[^[:alnum:]]+(not found|missing|source|environment|file|mount)|failed to create secret|invalid[^[:alnum:]]+secret|secrets?[^[:alnum:]]+(required|not set)/) {
        print "compose-secrets"
        exit
      }
      if (line ~ /permission denied|operation not permitted|operation not allowed|read-only file system|access denied/) {
        print "runtime-permission"
        exit
      }
      if (line ~ /not a directory|is a directory|no such file or directory|not a file|expected (a )?(file|directory)/) {
        print "file-shape"
        exit
      }
      if (line ~ /oci runtime|runc|failed to create (a )?(shim )?task|failed to start (the )?container|failed to initialize|container process|failed to mount|mount[^[:alnum:]]+failed/) {
        print "oci-runtime"
        exit
      }
      if (line ~ /cannot connect to the docker daemon|is the docker daemon running|error during connect|connection refused|daemon[^[:alnum:]]+(unavailable|not running|error)|no space left on device|resource temporarily unavailable|too many open files|out of memory|quota exceeded|device or resource busy|failed to create[^[:alnum:]]+(container|network|shim task)|network[^[:alnum:]]+(not found|unavailable|error)/) {
        print "daemon-resource"
        exit
      }
    }
  ' "$stderr_file")" || return 1
  if [[ -n "$candidate" ]]; then
    container_sensitive_preflight_failure_class "$candidate"
  elif [[ -s "$stderr_file" ]]; then
    printf '%s\n' 'unknown'
  else
    return 1
  fi
}

container_sensitive_proof_class() {
  local status="${1:-}" output="${2:-}" stderr_file="${3:-}" marker preflight_class
  [[ "$status" =~ ^[0-9]+$ ]] || {
    printf '%s\n' 'command-failure'
    return 0
  }
  marker="$(container_sensitive_marker_class "$output" || true)"
  if (( status != 0 )); then
    case "$marker" in
      uid|mount-content|secrets-json|forbidden-mount|environment-leak)
        container_sensitive_failure_class "$marker"
        ;;
      success)
        if [[ -s "$stderr_file" ]]; then
          printf '%s\n' 'stderr-diagnostics'
        else
          printf '%s\n' 'command-failure'
        fi
        ;;
      '')
        if [[ -s "$output" ]]; then
          printf '%s\n' 'output-contract'
        else
          preflight_class="$(container_sensitive_preflight_class "$stderr_file" || true)"
          if [[ -n "$preflight_class" ]]; then
            printf '%s\n' "$preflight_class"
          else
            printf '%s\n' 'command-failure'
          fi
        fi
        ;;
      *) printf '%s\n' 'output-contract' ;;
    esac
  elif [[ "$marker" == success ]]; then
    printf '%s\n' 'success'
  else
    printf '%s\n' 'output-contract'
  fi
}

container_remove_stderr() {
  local stderr_file="$1" command_status="$2"
  if rm -f -- "$stderr_file"; then
    return 0
  fi
  printf 'container stderr cleanup failed (command status %s)\n' "$command_status" >&2
  return 1
}

container_redact_diagnostics() {
  local diagnostic_file="$1"
  sed -E \
    -e "s#(https?://)[^/@[:space:]]+@#\\1[redacted]@#g" \
    -e "s#(^|[^[:alnum:]_])(([[:alnum:]_.-]*(secret|token|password|private([_-]?key)?|credential|customer|email)[[:alnum:]_.-]*)[[:space:]]*\"?[[:space:]]*[:=][[:space:]]*)(\"[^\"]*\"|'[^']*'|[^[:space:],}]+)#\\1\\2[redacted]#Ig" \
    -e "s#((Authorization|Proxy-Authorization|Cookie):[[:space:]]+)[^,[:cntrl:]]+#\\1[redacted]#Ig" \
    -e "s#(^|[^[:alnum:]_])((secret([[:space:]]+key)?|token|password|private([[:space:]]+key)?|credential|customer|email)[[:space:]]+)(\"[^\"]*\"|'[^']*'|[^[:space:],}]+)#\\1\\2[redacted]#Ig" \
    -e "s#[[:alnum:]_.%+-]+@[[:alnum:].-]+#[redacted]#g" \
    -e "s#@[[:alnum:]_.=-]+:[[:alnum:].-]+#[redacted]#g" \
    -e "s#([A-Za-z0-9._-]*fixture[A-Za-z0-9._-]*)#[redacted]#Ig" \
    "$diagnostic_file"
}

container_replay_sensitive() {
  local output="$1" stderr_file="$2" status=0
  if ! container_redact_diagnostics "$output" >&2; then
    status=1
  fi
  if ! container_redact_diagnostics "$stderr_file" >&2; then
    status=1
  fi
  return "$status"
}

container_emit_sensitive_stderr() {
  local stderr_file="$1"
  if [[ -s "$stderr_file" ]]; then
    container_redact_diagnostics "$stderr_file" >&2
  fi
}

container_active_pid=""
container_active_output=""
container_active_stderr=""
container_active_sensitive=false

container_command_signal() {
  local signal_name="$1" status=143 kill_status wait_status replay_status=0
  case "$signal_name" in
    HUP) status=129 ;;
    INT) status=130 ;;
    TERM) status=143 ;;
    *) status=143 ;;
  esac
  set +e
  if [[ -n "$container_active_pid" ]]; then
    kill -0 "$container_active_pid"
    kill_status=$?
    if [[ "$kill_status" -eq 0 ]]; then
      kill -TERM "$container_active_pid"
      kill_status=$?
      if [[ "$kill_status" -ne 0 ]]; then
        printf 'container command child termination failed during %s (status %s)\n' "$signal_name" "$kill_status" >&2
      fi
    elif [[ "$kill_status" -ne 1 ]]; then
      printf 'container command child liveness check failed during %s (status %s)\n' "$signal_name" "$kill_status" >&2
    fi
    wait "$container_active_pid"
    wait_status=$?
    container_active_pid=""
    if [[ "$wait_status" -eq 127 ]]; then
      printf 'container command child wait failed during %s\n' "$signal_name" >&2
    fi
    if [[ "$wait_status" -eq 0 ]]; then
      printf 'container command child exited successfully while handling %s\n' "$signal_name" >&2
    fi
  fi
  if [[ "$container_active_sensitive" == true ]]; then
    if ! container_replay_sensitive "$container_active_output" "$container_active_stderr"; then
      replay_status=1
    fi
  else
    if ! cat -- "$container_active_output"; then replay_status=1; fi
    if ! cat -- "$container_active_stderr" >&2; then replay_status=1; fi
  fi
  if (( replay_status != 0 )); then
    printf 'container command diagnostics could not be replayed after %s\n' "$signal_name" >&2
  fi
  exit "$status"
}

container_command() {
  local inherit_stdin=false
  local sensitive=false
  while [[ "${1:-}" == --* ]]; do
    case "$1" in
      --inherit-stdin) inherit_stdin=true ;;
      --sensitive) sensitive=true ;;
      *) return 2 ;;
    esac
    shift
  done
  local output="$1" timeout_seconds="$2" stderr_file status replay_status=0 cleanup_status=0
  shift 2
  [[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || return 2
  [[ $# -gt 0 ]] || return 2
  stderr_file="${output}.stderr"
  local previous_hup previous_int previous_term
  previous_hup="$(trap -p HUP || true)"
  previous_int="$(trap -p INT || true)"
  previous_term="$(trap -p TERM || true)"
  container_active_output="$output"
  container_active_stderr="$stderr_file"
  container_active_sensitive="$sensitive"
  trap 'container_command_signal HUP' HUP
  trap 'container_command_signal INT' INT
  trap 'container_command_signal TERM' TERM
  set +e
  if [[ "$inherit_stdin" == true ]]; then
    timeout --signal=TERM --kill-after=5s "${timeout_seconds}s" "$@" >"$output" 2>"$stderr_file" &
  else
    timeout --signal=TERM --kill-after=5s "${timeout_seconds}s" "$@" </dev/null >"$output" 2>"$stderr_file" &
  fi
  container_active_pid="$!"
  wait "$container_active_pid"
  status="$?"
  set -e
  container_active_pid=""
  container_active_output=""
  container_active_stderr=""
  container_active_sensitive=false
  if [[ -n "$previous_hup" ]]; then eval "$previous_hup"; else trap - HUP; fi
  if [[ -n "$previous_int" ]]; then eval "$previous_int"; else trap - INT; fi
  if [[ -n "$previous_term" ]]; then eval "$previous_term"; else trap - TERM; fi
  if (( status == 0 )); then
    :
  else
    if [[ "$sensitive" == true ]]; then
      if ! container_replay_sensitive "$output" "$stderr_file"; then
        replay_status=1
      fi
    else
      if ! cat -- "$output"; then replay_status=1; fi
      if ! cat -- "$stderr_file" >&2; then replay_status=1; fi
    fi
    if (( replay_status != 0 )); then
      printf 'container command diagnostics could not be replayed (command status %s)\n' "$status" >&2
    fi
  fi
  if (( status != 0 )); then
    if [[ "$sensitive" == false ]]; then
      if ! container_remove_stderr "$stderr_file" "$status"; then
        cleanup_status=1
      fi
    fi
    return "$status"
  fi
  if [[ "$sensitive" == false ]]; then
    if ! cat -- "$output"; then replay_status=1; fi
    if [[ -s "$stderr_file" ]] && ! cat -- "$stderr_file" >&2; then replay_status=1; fi
  fi
  if [[ "$sensitive" == false ]]; then
    if ! container_remove_stderr "$stderr_file" "$status"; then
      cleanup_status=1
    fi
  else
    if ! container_emit_sensitive_stderr "$stderr_file"; then
      replay_status=1
    fi
  fi
  if (( replay_status != 0 )); then
    printf 'container command diagnostics could not be replayed\n' >&2
  fi
  if (( cleanup_status != 0 )); then
    printf 'container command diagnostics cleanup failed\n' >&2
  fi
  if (( replay_status != 0 || cleanup_status != 0 )); then
    return 1
  fi
  return 0
}
