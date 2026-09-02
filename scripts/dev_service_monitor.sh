#!/usr/bin/env bash
# Service health monitor for dev tmux session.
# Monitors all services, tunnel HTTPS URL, and auto-respawns on crash.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${TMUX_SESSION:-crm-dev}"
MONITOR_INTERVAL=5
ENV_FILE="$ROOT/.env"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

log() { printf '[monitor] %s\n' "$1"; }

SERVICES=(tunnel api bot-client bot-trainer bot-admin notify)

sleep 2

while true; do
  for svc in "${SERVICES[@]}"; do
    if ! tmux list-windows -t "$SESSION" 2>/dev/null | grep -q "^${svc}:"; then
      log "WARNING: window '$svc' does not exist"
      continue
    fi

    status="$(tmux capture-pane -t "$SESSION:${svc}" -p | tail -5)"

    if echo "$status" | grep -qE "Pane is dead|Process exited"; then
      log "RESTART: $svc (crashed)"
      tmux respawn-window -k -t "$SESSION:${svc}" 2>/dev/null || true
      sleep 2
    fi
  done

  BASE="$("$PY" "$ROOT/scripts/dev_tunnel_util.py" read-env-url "$ENV_FILE" 2>/dev/null || true)"
  if [[ -n "$BASE" ]] && ! "$PY" "$ROOT/scripts/dev_tunnel_util.py" health "$BASE" >/dev/null 2>&1; then
    log "RESTART: tunnel (public URL unhealthy: $BASE)"
    bash "$ROOT/scripts/dev_stop_tunnel.sh" >/dev/null 2>&1 || true
    tmux respawn-window -k -t "$SESSION:tunnel" 2>/dev/null || true
    sleep 5
  fi

  sleep "$MONITOR_INTERVAL"
done
