#!/usr/bin/env bash
# Reads only TELEGRAM_BOT_TOKEN_TRAINER via Python — never source .env (stray lines can break bash).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TOKEN="$(python3 "${ROOT}/scripts/extract_env_kv.py" TELEGRAM_BOT_TOKEN_TRAINER)"
export TELEGRAM_BOT_TOKEN="${TOKEN}"
export SAMPLING_ENABLED="false"
if [[ -z "${TELEGRAM_BOT_TOKEN}" ]]; then
  echo "mcp-telegram-trainer: set TELEGRAM_BOT_TOKEN_TRAINER in ${ROOT}/.env" >&2
  exit 1
fi
export CI="${CI:-true}"
export npm_config_loglevel="${npm_config_loglevel:-silent}"
export npm_config_update_notifier="${npm_config_update_notifier:-false}"
exec npx -y @iqai/mcp-telegram
