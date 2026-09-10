#!/usr/bin/env sh
set -e
# Console-script `alembic` does not put the repo root on sys.path; migrations
# that import `src.*` then fail with ModuleNotFoundError and never reach uvicorn.
# Resolve root from this script and use `python -m alembic` (same as CI).
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${PYTHONPATH:-$ROOT}"
cd "$ROOT"
python -m alembic upgrade head
exec uvicorn src.api.app:app --host 0.0.0.0 --port "${PORT:-8000}"
