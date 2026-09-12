#!/usr/bin/env bash

# Shared capture helpers for release API commands. Output stays in files for
# later parsing; failures replay text diagnostics and binary responses stay out
# of the runner log.

release_capture_active_pid=""
release_capture_active_output=""
release_capture_active_stderr=""
release_capture_active_replay_output=true

release_capture_signal() {
  local signal_name="$1" status=143 kill_status wait_status replay_status=0
  case "$signal_name" in
    HUP) status=129 ;;
    INT) status=130 ;;
    TERM) status=143 ;;
    *) status=143 ;;
  esac
  set +e
  if [[ -n "$release_capture_active_pid" ]]; then
    kill -0 "$release_capture_active_pid"
    kill_status=$?
    if [[ "$kill_status" -eq 0 ]]; then
      kill -TERM "$release_capture_active_pid"
      kill_status=$?
      if [[ "$kill_status" -ne 0 ]]; then
        printf 'release capture child termination failed during %s (status %s)\n' "$signal_name" "$kill_status" >&2
      fi
    elif [[ "$kill_status" -ne 1 ]]; then
      printf 'release capture child liveness check failed during %s (status %s)\n' "$signal_name" "$kill_status" >&2
    fi
    wait "$release_capture_active_pid"
    wait_status=$?
    release_capture_active_pid=""
    if [[ "$wait_status" -eq 127 ]]; then
      printf 'release capture child wait failed during %s\n' "$signal_name" >&2
    fi
  fi
  if [[ -n "$release_capture_active_output" && "$release_capture_active_replay_output" == true ]] && ! cat -- "$release_capture_active_output" >&2; then replay_status=1; fi
  if [[ -n "$release_capture_active_stderr" ]] && ! cat -- "$release_capture_active_stderr" >&2; then replay_status=1; fi
  if [[ "$replay_status" -ne 0 ]]; then
    printf 'release capture diagnostics could not be replayed after %s\n' "$signal_name" >&2
  fi
  exit "$status"
}

capture_command() {
  local replay_output=true
  if [[ "${1:-}" == --binary-output ]]; then
    replay_output=false
    shift
  fi
  local output="$1" stderr="$2" timeout_seconds="$3" status replay_status=0
  shift 3
  local previous_hup previous_int previous_term
  previous_hup="$(trap -p HUP || true)"
  previous_int="$(trap -p INT || true)"
  previous_term="$(trap -p TERM || true)"
  release_capture_active_output="$output"
  release_capture_active_stderr="$stderr"
  release_capture_active_replay_output="$replay_output"
  trap 'release_capture_signal HUP' HUP
  trap 'release_capture_signal INT' INT
  trap 'release_capture_signal TERM' TERM
  timeout --signal=TERM --kill-after=5s "${timeout_seconds}s" "$@" >"$output" 2>"$stderr" &
  release_capture_active_pid="$!"
  if wait "$release_capture_active_pid"; then
    status=0
  else
    status=$?
  fi
  release_capture_active_pid=""
  release_capture_active_output=""
  release_capture_active_stderr=""
  release_capture_active_replay_output=true
  if [[ -n "$previous_hup" ]]; then eval "$previous_hup"; else trap - HUP; fi
  if [[ -n "$previous_int" ]]; then eval "$previous_int"; else trap - INT; fi
  if [[ -n "$previous_term" ]]; then eval "$previous_term"; else trap - TERM; fi
  if [[ "$status" -ne 0 ]]; then
    if [[ "$replay_output" == true ]] && ! cat -- "$output" >&2; then replay_status=1; fi
    if ! cat -- "$stderr" >&2; then replay_status=1; fi
    if [[ "$replay_status" -ne 0 ]]; then
      echo 'captured command diagnostics could not be replayed' >&2
    fi
    return "$status"
  fi
  if ! cat -- "$stderr" >&2; then
    echo 'captured command stderr could not be emitted' >&2
    return 1
  fi
  return 0
}

replay_capture() {
  local output="$1" stderr="$2" status=0
  if ! cat -- "$output" >&2; then status=1; fi
  if ! cat -- "$stderr" >&2; then status=1; fi
  return "$status"
}
