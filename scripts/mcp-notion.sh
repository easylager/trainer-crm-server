#!/usr/bin/env bash
# Loads NOTION_TOKEN from repo .env — Cursor MCP does not source .env for ${env:NOTION_TOKEN}.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TOKEN="$(python3 "${ROOT}/scripts/extract_env_kv.py" NOTION_TOKEN)"
export NOTION_TOKEN="${TOKEN}"
if [[ -z "${NOTION_TOKEN}" ]]; then
  echo "mcp-notion: set NOTION_TOKEN in ${ROOT}/.env (Notion → My integrations → Internal Integration Secret)" >&2
  exit 1
fi
export npm_config_loglevel="${npm_config_loglevel:-silent}"
export npm_config_update_notifier="${npm_config_update_notifier:-false}"
exec npx -y @notionhq/notion-mcp-server
