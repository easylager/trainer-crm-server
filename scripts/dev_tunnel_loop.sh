#!/usr/bin/env bash
# Self-healing cloudflared quick tunnel for the tmux dev session started by
# ./dev-start. Free quick tunnels drop from time to time; this loop restarts
# cloudflared, re-patches .env with the fresh *.trycloudflare.com URL, and
# respawns the API/bot windows so they pick up the new Settings (Settings is
# lru_cache'd per-process, so a stale URL survives until the process restarts).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_FILE="${TMPDIR:-/tmp}/trainer-crm-cloudflared.log"
ENV_FILE="$ROOT/.env"
SESSION="${TMUX_SESSION:-crm-dev}"
DEPENDENTS=(api bot-client bot-trainer bot-admin notify)

cleanup() {
  echo
  echo "[tunnel] stopping cloudflared..."
  pkill -f "cloudflared tunnel --url http://127.0.0.1:8000" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

restart_dependents() {
  [[ -n "${TMUX:-}" ]] || return 0
  for w in "${DEPENDENTS[@]}"; do
    tmux respawn-window -k -t "${SESSION}:${w}" 2>/dev/null && echo "[tunnel] respawned ${w}"
  done
}

while true; do
  : >"$LOG_FILE"
  echo "[tunnel] starting cloudflared..."
  env TUNNEL_TRANSPORT_PROTOCOL=http2 cloudflared tunnel --url http://127.0.0.1:8000 2>&1 | tee -a "$LOG_FILE" &
  PIPE_PID=$!

  URL="$(python3 "$ROOT/scripts/wait_trycloudflare_and_patch_env.py" "$LOG_FILE" "$ENV_FILE" --timeout 60 2>/dev/null || true)"
  if [[ -n "$URL" ]]; then
    echo "[tunnel] live at: $URL"
    echo "[tunnel] patched .env -- restarting API/bots so they reload it..."
    restart_dependents
  else
    echo "[tunnel] no *.trycloudflare.com URL seen within 60s -- check cloudflared output above."
  fi

  wait "$PIPE_PID"
  echo "[tunnel] cloudflared exited -- restarting in 3s (Ctrl-C to stop)..."
  sleep 3
done
