#!/usr/bin/env bash
# Repair an existing crm-dev tmux session: API, tunnel URL, crashed bot windows.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SESSION="${TMUX_SESSION:-crm-dev}"
ENV_FILE="$ROOT/.env"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"
WINDOWS=(tunnel api bot-client bot-trainer bot-admin notify)

log() { printf '[repair] %s\n' "$1"; }

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  log "no tmux session '$SESSION' — nothing to repair"
  exit 0
fi

# Stray processes from manual runs (outside tmux) steal :8000 and stale bot tokens.
lsof -ti :8000 | xargs kill -9 2>/dev/null || true
pkill -f "uvicorn src.api.app:app" 2>/dev/null || true
pkill -f "ssh.*nokey@localhost.run" 2>/dev/null || true
sleep 1

wait_local_api() {
  for _ in $(seq 1 45); do
    if curl -sf -m 2 http://127.0.0.1:8000/webapp/catalog >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

pane_dead() {
  local w=$1
  tmux capture-pane -t "${SESSION}:${w}" -p 2>/dev/null | tail -8 | grep -qE "Pane is dead|Process exited|exited with"
}

respawn_window() {
  local w=$1
  log "respawn window: ${w}"
  tmux respawn-window -k -t "${SESSION}:${w}" 2>/dev/null || true
}

if ! wait_local_api; then
  log "local API not responding — clearing :8000 and respawning api"
  lsof -ti :8000 | xargs kill -9 2>/dev/null || true
  pkill -f "uvicorn src.api.app:app" 2>/dev/null || true
  sleep 1
  respawn_window api
  wait_local_api || log "WARNING: API still down after respawn"
fi

BASE="$("$PY" "$ROOT/scripts/dev_tunnel_util.py" read-env-url "$ENV_FILE" 2>/dev/null || true)"
if [[ -z "$BASE" ]] || ! "$PY" "$ROOT/scripts/dev_tunnel_util.py" health "$BASE" >/dev/null 2>&1; then
  log "tunnel URL missing or unhealthy (${BASE:-none}) — restarting tunnel"
  bash "$ROOT/scripts/dev_stop_tunnel.sh" >/dev/null 2>&1 || true
  respawn_window tunnel
  for _ in $(seq 1 60); do
    BASE="$("$PY" "$ROOT/scripts/dev_tunnel_util.py" read-env-url "$ENV_FILE" 2>/dev/null || true)"
    if [[ -n "$BASE" ]] && "$PY" "$ROOT/scripts/dev_tunnel_util.py" health "$BASE" >/dev/null 2>&1; then
      log "tunnel healthy: $BASE"
      for w in api bot-client bot-trainer bot-admin notify; do
        respawn_window "$w"
      done
      break
    fi
    sleep 2
  done
  if [[ -z "$BASE" ]] || ! "$PY" "$ROOT/scripts/dev_tunnel_util.py" health "$BASE" >/dev/null 2>&1; then
    log "WARNING: tunnel still unhealthy — check tmux window 'tunnel'"
  fi
else
  log "tunnel OK: $BASE"
fi

for w in "${WINDOWS[@]}"; do
  if pane_dead "$w"; then
    respawn_window "$w"
  fi
done

log "syncing Telegram menu buttons to current tunnel URL..."
sleep 4
if (cd "$ROOT" && PYTHONPATH="$ROOT" "$PY" "$ROOT/scripts/dev_sync_bot_menus.py"); then
  log "bot menus synced"
else
  log "WARNING: bot menu sync failed — run: PYTHONPATH=. $PY scripts/dev_sync_bot_menus.py"
fi

log "repair finished"
