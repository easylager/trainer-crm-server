#!/usr/bin/env bash
# Stop dev tunnels (cloudflared quick tunnel + localhost.run SSH).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/.cursor-dev-cloudflared.pid"

if [[ -f "$PID_FILE" ]]; then
  PID="$(tr -d '[:space:]' <"$PID_FILE" || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    echo "[dev-stop-tunnel] stopping cloudflared pid ${PID}"
    kill "${PID}" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

pkill -f "cloudflared tunnel --url http://127.0.0.1:8000" 2>/dev/null || true
pkill -f "ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ExitOnForwardFailure=yes -R 80:127.0.0.1:8000 nokey@localhost.run" 2>/dev/null || true
pkill -f "ssh.*nokey@localhost.run" 2>/dev/null || true

echo "[dev-stop-tunnel] done"
