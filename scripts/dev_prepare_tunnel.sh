#!/usr/bin/env bash
# Start cloudflared quick tunnel in background, wait for *.trycloudflare.com URL, patch .env (API_BASE_URL + WEBAPP_BASE_URL).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/.cursor-dev-cloudflared.pid"
LOG_FILE="${TMPDIR:-/tmp}/trainer-crm-cloudflared.log"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install: brew install cloudflare/cloudflare/cloudflared" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(tr -d '[:space:]' <"$PID_FILE" || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
    echo "Stopping previous cloudflared (pid ${OLD_PID})"
    kill "${OLD_PID}" 2>/dev/null || true
    sleep 1
  fi
fi

: >"$LOG_FILE"
echo "cloudflared log: $LOG_FILE"

# Force HTTP/2: QUIC (UDP/7844) often fails on local Wi-Fi/VPN and leaves a
# trycloudflare URL that returns Cloudflare 530 while localhost:8000 is fine.
# cloudflared 2026.x reads TUNNEL_TRANSPORT_PROTOCOL (not --protocol).
nohup env TUNNEL_TRANSPORT_PROTOCOL=http2 cloudflared tunnel --url http://127.0.0.1:8000 >>"$LOG_FILE" 2>&1 &
CF_PID=$!
disown "$CF_PID" 2>/dev/null || true
echo "$CF_PID" >"$PID_FILE"
echo "cloudflared pid ${CF_PID} (saved to .cursor-dev-cloudflared.pid)"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "No .env at $ROOT/.env — create it from .env.example first." >&2
  exit 1
fi

BASE_URL="$(python3 "$ROOT/scripts/wait_trycloudflare_and_patch_env.py" "$LOG_FILE" "$ROOT/.env")"
echo "Patched .env: API_BASE_URL and WEBAPP_BASE_URL → ${BASE_URL}"
echo "Cloudflare tunnel keeps running in background. Start/restart API and bots so they reload Settings."
