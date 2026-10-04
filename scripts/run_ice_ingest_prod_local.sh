#!/usr/bin/env bash
# Prod ops from a laptop: Railway api-server env + Postgres PUBLIC URL.
#
# ``railway run -s api-server`` alone sets DATABASE_URL to *.railway.internal,
# which does not resolve off Railway's network (gaierror). Postgres service exposes
# DATABASE_PUBLIC_URL (*.proxy.rlwy.net).
#
# Usage (from repo root, Railway CLI linked to production):
#   bash scripts/run_ice_ingest_prod_local.sh
#   bash scripts/run_ice_ingest_prod_local.sh scripts/seed_ice_parser_jobs.py --apply --i-know-this-is-prod
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

POSTGRES_SERVICE="${RAILWAY_POSTGRES_SERVICE:-Postgres-W--1}"
API_SERVICE="${RAILWAY_API_SERVICE:-api-server}"

PUB="$(railway run -s "$POSTGRES_SERVICE" -- printenv DATABASE_PUBLIC_URL)"
if [[ -z "$PUB" ]]; then
  echo "DATABASE_PUBLIC_URL is empty on service $POSTGRES_SERVICE." >&2
  echo "Railway → Postgres → Connect → Public network, or set RAILWAY_POSTGRES_SERVICE." >&2
  exit 1
fi
case "$PUB" in
  postgresql://*) DB_URL="postgresql+asyncpg://${PUB#postgresql://}" ;;
  postgresql+asyncpg://*) DB_URL="$PUB" ;;
  *)
    echo "Unexpected DATABASE_PUBLIC_URL scheme." >&2
    exit 1
    ;;
esac

echo "Using public Postgres host (from $POSTGRES_SERVICE) + env from $API_SERVICE …" >&2

if [[ $# -eq 0 ]]; then
  set -- scripts/run_ice_ingest_once.py --i-know-this-is-prod
fi

exec railway run -s "$API_SERVICE" -- env DATABASE_URL="$DB_URL" PYTHONPATH=. "$PY" "$@"
