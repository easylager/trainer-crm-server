#!/usr/bin/env bash
# То же, что scripts/by_ingest.sh, но слоты пишутся в ЛОКАЛЬНУЮ базу (из .env, обычно localhost:5432/trainer_crm)
# кодом из текущей ветки — проверить на живых сайтах, что всё разбирается и раскладывается по видам.
#
#   bash scripts/by_ingest_local.sh run            # alembic upgrade head + прогон + сводка (спросит подтверждение)
#   bash scripts/by_ingest_local.sh run -y         # без вопроса
#   bash scripts/by_ingest_local.sh dry            # открыть сайты и разобрать, БЕЗ записи (миграции не нужны)
#   bash scripts/by_ingest_local.sh summary        # только сводка по тому, что уже лежит в базе
#   bash scripts/by_ingest_local.sh run --only ledlife_origin_html_v1   # только эти источники
#   bash scripts/by_ingest_local.sh run --proxy    # через BY_EGRESS_PROXY_URL из .env (если IP не белорусский)
#
# Сайтам нужен белорусский IP (VPN выключен) или BY-прокси (--proxy: BY_EGRESS_PROXY_URL из .env, проверка IP пропускается). Railway и прод не трогаются:
# хост базы, отличный от localhost/127.x, — отказ. Файл окружения: $ENV_FILE, иначе ./.env, иначе ../trainer-crm-server/.env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

mode="${1:-}"; [[ -n "$mode" ]] || { usage; exit 1; }; shift || true
yes=0; rest=()
for a in "$@"; do
  case "$a" in -y|--yes) yes=1 ;; --proxy) rest+=(--proxy --skip-ip-check) ;; *) rest+=("$a") ;; esac
done
case "$mode" in
  run) flags=() ;; dry) flags=(--dry-run) ;; summary) flags=() ;; *) usage; exit 1 ;;
esac

PY=""
for c in "$ROOT/.venv/bin/python" "$ROOT/../trainer-crm-server/.venv/bin/python"; do
  [[ -x "$c" ]] && { PY="$c"; break; }
done
[[ -n "$PY" ]] || PY="python3"

ENV_FILE="${ENV_FILE:-}"
if [[ -z "$ENV_FILE" ]]; then
  for c in "$ROOT/.env" "$ROOT/../trainer-crm-server/.env"; do [[ -f "$c" ]] && { ENV_FILE="$c"; break; }; done
fi
[[ -n "$ENV_FILE" && -f "$ENV_FILE" ]] || { echo "Не нашёл .env (задайте ENV_FILE=...)." >&2; exit 1; }

# Переменные из .env (уже заданные в окружении не перетираются, кроме ссылок на базу — они только из .env,
# чтобы случайный DATABASE_URL прода в shell не попал сюда).
eval "$("$PY" - "$ENV_FILE" <<'PYEOF'
import os, shlex, sys
from dotenv import dotenv_values
for k, v in dotenv_values(sys.argv[1]).items():
    if v is None:
        continue
    if k in ("DATABASE_URL", "DATABASE_URL_SYNC") or k not in os.environ:
        print(f"export {k}={shlex.quote(v)}")
PYEOF
)"
[[ -n "${DATABASE_URL:-}" ]] || { echo "В $ENV_FILE нет DATABASE_URL." >&2; exit 1; }
export DATABASE_URL_SYNC="${DATABASE_URL_SYNC:-$DATABASE_URL}"
unset DATABASE_PUBLIC_URL RAILWAY_ENVIRONMENT RAILWAY_PROJECT_ID 2>/dev/null || true

# Жёсткая защита: только локальный хост, для обеих ссылок.
TARGET="$("$PY" - <<'PYEOF'
import os, sys
from urllib.parse import urlparse
seen = []
for key in ("DATABASE_URL", "DATABASE_URL_SYNC"):
    u = urlparse(os.environ[key].replace("+asyncpg", "").replace("+psycopg", ""))
    host = (u.hostname or "").lower()
    if not (host in {"localhost", "::1"} or (host.startswith("127.") and host.count(".") == 3)):
        sys.exit(f"ОТКАЗ: {key} указывает на {host!r} — этот скрипт пишет только в localhost.")
    seen.append(f"{host}:{u.port or 5432}/{u.path.lstrip('/')}")
if seen[0] != seen[1]:
    sys.exit(f"ОТКАЗ: DATABASE_URL ({seen[0]}) и DATABASE_URL_SYNC ({seen[1]}) смотрят в разные базы.")
print(seen[0])
PYEOF
)" || exit 1
export PYTHONPATH="$ROOT"
echo "База: $TARGET   (env: $ENV_FILE)   код: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD)@$(git -C "$ROOT" rev-parse --short HEAD)"

if [[ "$mode" == "summary" ]]; then
  exec "$PY" "$ROOT/scripts/by_ingest_local_summary.py"
fi

if [[ "$mode" == "run" && $yes -eq 0 ]]; then
  read -r -p "Применить миграции (alembic upgrade head) и записать слоты в $TARGET? [y/N] " ans
  [[ "$ans" =~ ^[YyДд]$ ]] || { echo "Отменено."; exit 1; }
fi

if [[ "$mode" == "run" ]]; then
  echo "alembic: $("$PY" -m alembic current 2>/dev/null | tail -n1) → head"
  "$PY" -m alembic upgrade head
fi

set +e
"$PY" "$ROOT/scripts/ingest_by_local.py" ${flags[@]+"${flags[@]}"} ${rest[@]+"${rest[@]}"}
code=$?
set -e
if [[ "$mode" == "run" ]]; then
  echo; "$PY" "$ROOT/scripts/by_ingest_local_summary.py" || true
fi
exit $code
