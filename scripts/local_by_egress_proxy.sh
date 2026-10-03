#!/usr/bin/env bash
# Локальный BY egress для ice ingest с ноутбука в РБ (VPN выключен).
# Railway BY_EGRESS_PROXY_URL не трогаем — прокси только на 127.0.0.1.
#
#   bash scripts/local_by_egress_proxy.sh setup   # один раз: .local/* + строка в .env
#   bash scripts/local_by_egress_proxy.sh start   # держать открытым в отдельном терминале
#   bash scripts/local_by_egress_proxy.sh check   # ipinfo + junost через прокси
#   bash scripts/local_by_egress_proxy.sh ingest  # Railway: DATABASE_URL=<public postgres> ingest
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
LOCAL_DIR="$ROOT/.local"
CONF="$LOCAL_DIR/tinyproxy-by.conf"
CREDS="$LOCAL_DIR/by-egress-proxy.env"
PORT="${BY_EGRESS_LOCAL_PORT:-8888}"
USER_NAME="${BY_EGRESS_LOCAL_USER:-byegress}"

die() {
  echo "local_by_egress_proxy: $*" >&2
  exit 1
}

tinyproxy_bin() {
  if command -v tinyproxy >/dev/null 2>&1; then
    command -v tinyproxy
    return
  fi
  if [[ -x /opt/homebrew/bin/tinyproxy ]]; then
    echo /opt/homebrew/bin/tinyproxy
    return
  fi
  die "tinyproxy not found — run: brew install tinyproxy"
}

load_creds() {
  [[ -f "$CREDS" ]] || die "run: bash scripts/local_by_egress_proxy.sh setup"
  # shellcheck disable=SC1090
  source "$CREDS"
  [[ -n "${BY_EGRESS_LOCAL_PASSWORD:-}" ]] || die "missing BY_EGRESS_LOCAL_PASSWORD in $CREDS"
}

proxy_url() {
  load_creds
  echo "http://${USER_NAME}:${BY_EGRESS_LOCAL_PASSWORD}@127.0.0.1:${PORT}"
}

write_env_var() {
  local url="$1"
  local line="BY_EGRESS_PROXY_URL=${url}"
  if [[ ! -f "$ENV_FILE" ]]; then
    printf '%s\n' "$line" >>"$ENV_FILE"
    return
  fi
  if grep -q '^BY_EGRESS_PROXY_URL=' "$ENV_FILE"; then
    if [[ "$(uname)" == Darwin ]]; then
      sed -i '' "s|^BY_EGRESS_PROXY_URL=.*|${line}|" "$ENV_FILE"
    else
      sed -i "s|^BY_EGRESS_PROXY_URL=.*|${line}|" "$ENV_FILE"
    fi
  else
    printf '\n%s\n' "$line" >>"$ENV_FILE"
  fi
}

cmd_setup() {
  mkdir -p "$LOCAL_DIR"
  if [[ ! -f "$CREDS" ]]; then
    BY_EGRESS_LOCAL_PASSWORD="$(openssl rand -hex 12)"
    cat >"$CREDS" <<EOF
# gitignored — не коммитить
BY_EGRESS_LOCAL_PASSWORD=${BY_EGRESS_LOCAL_PASSWORD}
EOF
    chmod 600 "$CREDS"
  fi
  load_creds
  cat >"$CONF" <<EOF
Port ${PORT}
Listen 127.0.0.1
Allow 127.0.0.1
BasicAuth ${USER_NAME} ${BY_EGRESS_LOCAL_PASSWORD}
MaxClients 10
Timeout 600
EOF
  write_env_var "$(proxy_url)"
  echo "Wrote $CONF and BY_EGRESS_PROXY_URL in $ENV_FILE"
  echo "Next: terminal 1 → bash scripts/local_by_egress_proxy.sh start"
  echo "      terminal 2 → bash scripts/local_by_egress_proxy.sh check"
}

cmd_start() {
  [[ -f "$CONF" ]] || die "run setup first"
  echo "tinyproxy on 127.0.0.1:${PORT} (Ctrl-C to stop)"
  exec "$(tinyproxy_bin)" -d -c "$CONF"
}

cmd_check() {
  local url
  url="$(proxy_url)"
  echo "=== direct (VPN должен быть выключен) ==="
  curl -s --max-time 12 https://ipinfo.io/json || true
  echo ""
  echo "=== via local proxy ==="
  curl -s --max-time 12 --proxy "$url" https://ipinfo.io/json || die "proxy unreachable — is 'start' running?"
  echo ""
  echo "=== junost / ledlife via proxy ==="
  curl -sI --max-time 15 --proxy "$url" https://junost.by/ | head -1
  curl -sI --max-time 15 --proxy "$url" https://ledlife.by/ | head -1
}

cmd_ingest() {
  url="$(proxy_url)"
  if ! curl -s --max-time 5 --proxy "$url" https://ipinfo.io/country >/dev/null 2>&1; then
    die "local proxy not responding — run 'start' in another terminal"
  fi
  cd "$ROOT"
  PY="$ROOT/.venv/bin/python"
  if [[ ! -x "$PY" ]]; then
    PY=python3
  fi
  PYTHONPATH=. "$PY" scripts/run_ice_ingest_once.py --i-know-this-is-prod
}

usage() {
  sed -n '3,8p' "$0" | sed 's/^# //'
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    setup) cmd_setup ;;
    start) cmd_start ;;
    check) cmd_check ;;
    ingest) cmd_ingest ;;
    *) usage; exit 1 ;;
  esac
}

main "${1:-}"
