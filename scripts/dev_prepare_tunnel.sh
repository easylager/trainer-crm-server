#!/usr/bin/env bash
# Start dev HTTPS tunnel, patch .env. Cloudflared first; localhost.run fallback.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
CF_LOG="${TMPDIR:-/tmp}/trainer-crm-cloudflared.log"
LR_LOG="${TMPDIR:-/tmp}/trainer-crm-localhostrun.log"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

[[ -f "$ENV_FILE" ]] || { echo "No .env at $ENV_FILE" >&2; exit 1; }

bash "$ROOT/scripts/dev_stop_tunnel.sh"

wait_local_api() {
  for _ in $(seq 1 30); do
    curl -sf -m 2 http://127.0.0.1:8000/webapp/catalog >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "WARNING: API not on :8000 yet — start uvicorn first for tunnel health check" >&2
}

wait_local_api || true

URL=""
if command -v cloudflared >/dev/null 2>&1; then
  : >"$CF_LOG"
  echo "Starting cloudflared..."
  nohup env TUNNEL_TRANSPORT_PROTOCOL=http2 cloudflared tunnel --url http://127.0.0.1:8000 >>"$CF_LOG" 2>&1 &
  disown $! 2>/dev/null || true
  URL="$("$PY" "$ROOT/scripts/dev_tunnel_util.py" wait-cloudflare "$CF_LOG" "$ENV_FILE" --timeout 60 2>/dev/null || true)"
fi

if [[ -z "$URL" ]]; then
  bash "$ROOT/scripts/dev_stop_tunnel.sh" >/dev/null 2>&1 || true
  : >"$LR_LOG"
  echo "Cloudflared unavailable — starting localhost.run..."
  nohup ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ExitOnForwardFailure=yes \
    -R 80:127.0.0.1:8000 nokey@localhost.run >>"$LR_LOG" 2>&1 &
  disown $! 2>/dev/null || true
  URL="$("$PY" "$ROOT/scripts/dev_tunnel_util.py" wait-localhostrun "$LR_LOG" "$ENV_FILE" --timeout 60 2>/dev/null || true)"
fi

if [[ -z "$URL" ]]; then
  echo "Failed to obtain HTTPS tunnel URL." >&2
  exit 1
fi

if ! "$PY" "$ROOT/scripts/dev_tunnel_util.py" health "$URL" >/dev/null 2>&1; then
  echo "Tunnel URL not healthy yet: $URL (is API running on :8000?)" >&2
  exit 1
fi

echo "Patched .env: API_BASE_URL and WEBAPP_BASE_URL → ${URL}"
echo "Restart API and bots so they reload Settings."
