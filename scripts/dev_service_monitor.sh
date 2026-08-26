#!/usr/bin/env bash
# Service health monitor for dev tmux session.
# Monitors all services and auto-respawns them on crash.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${TMUX_SESSION:-crm-dev}"
MONITOR_INTERVAL=5

log() { printf '[monitor] %s\n' "$1"; }
check_window_alive() {
  tmux list-windows -t "$SESSION" 2>/dev/null | grep -q "^$1:" && \
  ! tmux capture-pane -t "$SESSION:$1" -p | grep -q "^.*exited.*$"
}

SERVICES=(tunnel api bot-client bot-trainer bot-admin notify)

# Wait for initial session setup
sleep 2

while true; do
  for svc in "${SERVICES[@]}"; do
    if ! tmux list-windows -t "$SESSION" 2>/dev/null | grep -q "^$svc:"; then
      log "WARNING: window '$svc' does not exist"
      continue
    fi

    # Check if pane is in error/dead state
    status="$(tmux capture-pane -t "$SESSION:$svc" -p | tail -5)"

    # If window shows "Pane is dead", respawn it
    if echo "$status" | grep -qE "Pane is dead|Process exited"; then
      log "RESTART: $svc (crashed)"
      tmux respawn-window -k -t "$SESSION:$svc" 2>/dev/null || true
      sleep 2
    fi
  done

  sleep "$MONITOR_INTERVAL"
done
