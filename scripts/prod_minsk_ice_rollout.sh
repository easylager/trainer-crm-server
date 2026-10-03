#!/usr/bin/env bash
# One-shot prod: arena repairs → seed jobs → BY-egress ingest (ledlife + junost) + ABWS refresh.
#
# Prerequisites:
#   export DATABASE_URL='<Railway DATABASE_PUBLIC_URL or proxy URL>'  # NOT localhost
#   Terminal 1: bash scripts/local_by_egress_proxy.sh start
#   VPN off (BY IP for ledlife/junost)
#
# Usage:
#   bash scripts/prod_minsk_ice_rollout.sh
#   bash scripts/prod_minsk_ice_rollout.sh --skip-ingest   # DB-only (repairs + seed)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

SKIP_INGEST=false
for arg in "$@"; do
  case "$arg" in
    --skip-ingest) SKIP_INGEST=true ;;
    -h|--help)
      sed -n '3,12p' "$0" | sed 's/^# //'
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 1 ;;
  esac
done

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "Set DATABASE_URL to Railway Postgres (public URL from dashboard → Postgres → Connect)." >&2
  exit 1
fi
case "$DATABASE_URL" in
  *localhost*|*127.0.0.1*) echo "DATABASE_URL is local; use Railway public URL for prod rollout." >&2; exit 1 ;;
esac

ACK=(--i-know-this-is-prod)

echo "=== 1/4 repair ledlife arena row (Minsk / minsk-ledlife) ==="
PYTHONPATH=. "$PY" scripts/repair_minsk_ledlife_arena_row.py --apply "${ACK[@]}"

echo "=== 2/4 move hockey MK (service/55) to arena 115 ==="
PYTHONPATH=. "$PY" scripts/repair_minskarena_hockey_mk_target.py --apply "${ACK[@]}"

echo "=== 3/4 seed ice_parser_jobs (main arena / hockey / ledlife / junost) ==="
PYTHONPATH=. "$PY" scripts/seed_ice_parser_jobs.py --apply "${ACK[@]}"

if [[ "$SKIP_INGEST" == true ]]; then
  echo "skipped ingest (--skip-ingest). Run: bash scripts/local_by_egress_proxy.sh ingest"
  exit 0
fi

echo "=== 4/4 ice ingest (BY proxy + all MK including ABWS) ==="
bash scripts/local_by_egress_proxy.sh ingest

echo "Done. Verify:"
echo "  curl -s 'https://api-server-production-dcd9.up.railway.app/api/public/arenas/minsk-ledlife/sessions' | jq '.sessions[0].price_adult_minor'"
echo "  curl -s 'https://api-server-production-dcd9.up.railway.app/api/public/ice/arenas?city_id=2' | jq '.items[] | select(.id==4 or .id==115)'"
