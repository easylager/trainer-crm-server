#!/usr/bin/env bash
# Summarize a pg_dump custom-format archive: full vs data-only, TOC size.
set -euo pipefail

if [[ $# -lt 1 ]] || [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  echo "Usage: $0 <file.dump>" >&2
  exit 1
fi

DUMP="$1"
if [[ ! -f "$DUMP" ]]; then
  echo "File not found: $DUMP" >&2
  exit 1
fi

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "pg_restore not found (install PostgreSQL client tools)." >&2
  exit 1
fi

echo "=== $DUMP ==="
pg_restore -l "$DUMP" 2>/dev/null | head -20

# "TABLE public" must not match "TABLE DATA public"
TABLE_SCHEMA=$(pg_restore -l "$DUMP" 2>/dev/null | grep ' TABLE public ' | grep -cv 'TABLE DATA' || true)
TABLE_DATA=$(pg_restore -l "$DUMP" 2>/dev/null | grep -c ' TABLE DATA public ' || true)

echo ""
echo "--- Summary ---"
echo "Lines matching TABLE (schema, not DATA): $TABLE_SCHEMA"
echo "Lines matching TABLE DATA:               $TABLE_DATA"

if [[ "$TABLE_DATA" -gt 0 ]] && [[ "$TABLE_SCHEMA" -eq 0 ]]; then
  echo "Verdict: DATA-ONLY dump — apply schema first (alembic upgrade head), then pg_restore --data-only."
elif [[ "$TABLE_SCHEMA" -gt 0 ]]; then
  echo "Verdict: includes TABLE definitions — full (or schema+data) dump; restore to empty DB or use --clean with care."
else
  echo "Verdict: could not classify (unexpected TOC)."
fi
