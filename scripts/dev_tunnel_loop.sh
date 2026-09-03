#!/usr/bin/env bash
# Self-healing dev tunnel for ./dev-start tmux session.
# Tries cloudflared quick tunnel first; falls back to localhost.run (SSH) when CF is blocked.
# Re-patches .env on URL change and respawns API/bots (Settings is lru_cache per process).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="$ROOT/.env"
SESSION="${TMUX_SESSION:-crm-dev}"
CF_LOG="${TMPDIR:-/tmp}/trainer-crm-cloudflared.log"
LR_LOG="${TMPDIR:-/tmp}/trainer-crm-localhostrun.log"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"
DEPENDENTS=(api bot-client bot-trainer bot-admin notify)

TUNNEL_PID=""
TUNNEL_URL=""
TUNNEL_PROVIDER=""

log() { printf '[tunnel] %s\n' "$1"; }

stop_all_tunnels() {
  bash "$ROOT/scripts/dev_stop_tunnel.sh" >/dev/null 2>&1 || true
  TUNNEL_PID=""
}

cleanup() {
  echo
  log "stopping..."
  stop_all_tunnels
  exit 0
}
trap cleanup INT TERM

restart_dependents() {
  [[ -n "${TMUX:-}" ]] || return 0
  for w in "${DEPENDENTS[@]}"; do
    tmux respawn-window -k -t "${SESSION}:${w}" 2>/dev/null && log "respawned ${w}"
  done
  sleep 4
  (cd "$ROOT" && PYTHONPATH="$ROOT" "$PY" "$ROOT/scripts/dev_sync_bot_menus.py" 2>/dev/null) \
    && log "Telegram menu buttons synced" \
    || log "menu sync skipped (bots still starting)"
}

wait_local_api() {
  for _ in $(seq 1 60); do
    if curl -sf -m 2 http://127.0.0.1:8000/webapp/catalog >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  log "WARNING: local API not up on :8000 (tunnel health may fail until api window starts)"
  return 1
}

wait_tunnel_health() {
  local url=$1
  for _ in $(seq 1 40); do
    if "$PY" "$ROOT/scripts/dev_tunnel_util.py" health "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

try_cloudflare() {
  command -v cloudflared >/dev/null 2>&1 || return 1
  : >"$CF_LOG"
  log "trying cloudflared (trycloudflare.com)..."
  env TUNNEL_TRANSPORT_PROTOCOL=http2 cloudflared tunnel --url http://127.0.0.1:8000 2>&1 | tee -a "$CF_LOG" &
  TUNNEL_PID=$!
  local url
  url="$("$PY" "$ROOT/scripts/dev_tunnel_util.py" wait-cloudflare "$CF_LOG" "$ENV_FILE" --timeout 45 2>/dev/null || true)"
  if [[ -z "$url" ]]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    TUNNEL_PID=""
    return 1
  fi
  TUNNEL_URL="$url"
  TUNNEL_PROVIDER="cloudflare"
  return 0
}

try_localhostrun() {
  command -v ssh >/dev/null 2>&1 || return 1
  : >"$LR_LOG"
  log "trying localhost.run (SSH)..."
  ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ExitOnForwardFailure=yes \
    -R 80:127.0.0.1:8000 nokey@localhost.run 2>&1 | tee -a "$LR_LOG" &
  TUNNEL_PID=$!
  local url
  url="$("$PY" "$ROOT/scripts/dev_tunnel_util.py" wait-localhostrun "$LR_LOG" "$ENV_FILE" --timeout 45 2>/dev/null || true)"
  if [[ -z "$url" ]]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    TUNNEL_PID=""
    return 1
  fi
  TUNNEL_URL="$url"
  TUNNEL_PROVIDER="localhostrun"
  return 0
}

bring_tunnel_up() {
  stop_all_tunnels
  wait_local_api || true

  if try_cloudflare && wait_tunnel_health "$TUNNEL_URL"; then
    log "live (${TUNNEL_PROVIDER}): ${TUNNEL_URL}"
    restart_dependents
    return 0
  fi
  stop_all_tunnels

  if try_localhostrun && wait_tunnel_health "$TUNNEL_URL"; then
    log "live (${TUNNEL_PROVIDER}): ${TUNNEL_URL}"
    restart_dependents
    return 0
  fi
  stop_all_tunnels
  TUNNEL_URL=""
  return 1
}

monitor_tunnel() {
  while kill -0 "$TUNNEL_PID" 2>/dev/null; do
    if ! "$PY" "$ROOT/scripts/dev_tunnel_util.py" health "$TUNNEL_URL" >/dev/null 2>&1; then
      log "public URL unhealthy — restarting tunnel"
      return 1
    fi
    sleep 15
  done
  log "${TUNNEL_PROVIDER:-tunnel} process exited"
  return 1
}

while true; do
  if bring_tunnel_up; then
    monitor_tunnel || true
  else
    log "all providers failed — retry in 10s (check network/VPN; cloudflared optional)"
    sleep 10
  fi
  stop_all_tunnels
  sleep 3
done
