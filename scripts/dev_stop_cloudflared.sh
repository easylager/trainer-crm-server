#!/usr/bin/env bash
# Stop cloudflared started by dev_prepare_tunnel.sh (pid file in repo root).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/.cursor-dev-cloudflared.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "No $PID_FILE — nothing to stop."
  exit 0
fi
PID="$(tr -d '[:space:]' <"$PID_FILE" || true)"
if [[ -z "$PID" ]]; then
  rm -f "$PID_FILE"
  exit 0
fi
if kill -0 "$PID" 2>/dev/null; then
  echo "Stopping cloudflared pid $PID"
  kill "$PID" 2>/dev/null || true
else
  echo "Process $PID not running"
fi
rm -f "$PID_FILE"
