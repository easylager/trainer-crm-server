#!/usr/bin/env bash
# Источники, которым нужен белорусский IP (СДЮШОР, Горки, Бобруйск, Солигорск, Конькобежный стадион): прогон с ноутбука в Беларуси. VPN выключен, Railway CLI залогинен.
#
#   bash scripts/by_ingest.sh dry                  # проверка: открыть сайты и разобрать расписание, БЕЗ записи
#   bash scripts/by_ingest.sh run                  # прод: то же, но слоты записываются в базу
#   bash scripts/by_ingest.sh run --only gorki_lds_v1 bobruisk_arena_v1   # только эти источники
#   bash scripts/by_ingest.sh list                 # какие источники входят и какие задания есть в проде
#
# Запускать можно из любой папки и любой ветки, где лежит этот файл: привязка Railway-проекта не нужна.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${RAILWAY_PROJECT_ID:-3f69c07d-25ee-412b-8bb1-bf68c61884f5}"
ENVIRONMENT="${RAILWAY_ENVIRONMENT_NAME:-production}"
POSTGRES_SERVICE="${RAILWAY_POSTGRES_SERVICE:-Postgres-W--1}"
API_SERVICE="${RAILWAY_API_SERVICE:-api-server}"

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

mode="${1:-}"
[[ -n "$mode" ]] || { usage; exit 1; }
shift || true

case "$mode" in
  dry)  flags=(--dry-run) ;;
  run)  flags=() ;;
  list) flags=(--list) ;;
  *)    usage; exit 1 ;;
esac

# Python: .venv этого репозитория, иначе .venv основной папки, иначе системный.
PY=""
for candidate in "$ROOT/.venv/bin/python" "$ROOT/../trainer-crm-server/.venv/bin/python"; do
  if [[ -x "$candidate" ]]; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || PY="python3"

command -v railway >/dev/null || { echo "Нет Railway CLI (brew install railway; railway login)." >&2; exit 1; }

PUB="$(railway run -p "$PROJECT" -e "$ENVIRONMENT" -s "$POSTGRES_SERVICE" -- printenv DATABASE_PUBLIC_URL 2>/dev/null | tail -n1)"
if [[ -z "$PUB" ]]; then
  echo "Не получил DATABASE_PUBLIC_URL у сервиса $POSTGRES_SERVICE. Проверьте: railway login." >&2
  exit 1
fi
case "$PUB" in
  postgresql://*) DB_URL="postgresql+asyncpg://${PUB#postgresql://}" ;;
  postgresql+asyncpg://*) DB_URL="$PUB" ;;
  *) echo "Неожиданный формат DATABASE_PUBLIC_URL." >&2; exit 1 ;;
esac

exec railway run -p "$PROJECT" -e "$ENVIRONMENT" -s "$API_SERVICE" -- \
  env DATABASE_URL="$DB_URL" PYTHONPATH="$ROOT" \
  "$PY" "$ROOT/scripts/ingest_by_local.py" ${flags[@]+"${flags[@]}"} --i-know-this-is-prod "$@"
