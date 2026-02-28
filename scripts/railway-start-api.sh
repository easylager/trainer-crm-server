#!/usr/bin/env sh
set -e
alembic upgrade head
exec uvicorn src.api.app:app --host 0.0.0.0 --port "${PORT:-8000}"
