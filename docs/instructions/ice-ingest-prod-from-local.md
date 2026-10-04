# Ingest льда в прод с ноутбука (Railway)

Короткий runbook: **один раз** обновить расписание массовых катаний в **прод-БД**
после деплоя или если нужно не ждать `notification_service` (~45 мин до следующего
due у job).

Теория (планировщик, что трогается в БД): [ops/ice-freshness-and-alerts.md](../ops/ice-freshness-and-alerts.md).

СДЮШОР / Юность (обязательный BY IP): отдельно — [ice-ingest-by-egress.md](ice-ingest-by-egress.md).

## Когда нужно

- Выкатили парсер или enrich (например остатки Korona на ТЦ Замок) — в API появятся
  новые поля только после ingest.
- Хотите **сразу** пересобрать слоты всех due MK-jobs, а не ждать цикл на Railway.

На Railway тот же ingest крутится в **`ice-platform-notification`** (`run_ice_ingest_scheduler_loop`, опрос ~60 с). Ручной прогон — **разовое** ускорение после деплоя, не штатный режим.

### Остатки мест на Замке (Korona)

Цифры на чипах обновляются при каждом успешном прогоне `zamok_html_v1` (tczamok + koronaticket). В спеке задано **`poll_minutes: 15`** — планировщик перечитывает источник примерно каждые 15 минут днём (см. `next_poll_at` в `src/ingestion/freshness.py`), без ручного `run_ice_ingest_once`.

После смены `poll_minutes` в спеке один раз применить конфиг на проде:

```bash
bash scripts/run_ice_ingest_prod_local.sh scripts/seed_ice_parser_jobs.py --apply --i-know-this-is-prod
```

Либо точечно в SQL (если seed не гоняете):

```sql
UPDATE ice_parser_jobs
SET config = config || '{"poll_minutes": 15}'::jsonb
WHERE parser_key = 'zamok_html_v1';
```

## Предусловия

1. Репозиторий, `.venv`, зависимости — как для разработки.
2. [Railway CLI](https://docs.railway.com/guides/cli) залогинен, проект **trainer-crm**, окружение **production**.
3. Понимание: скрипт **пишет** в прод (`ice_sessions` для арен с включёнными
   `ice_parser_jobs`). Нужен явный `--i-know-this-is-prod`.

## Рекомендуемая команда

Из корня репозитория:

```bash
bash scripts/run_ice_ingest_prod_local.sh
```

Скрипт:

1. Читает **`DATABASE_PUBLIC_URL`** с сервиса Postgres (`Postgres-W--1` по умолчанию) —
   хост `*.proxy.rlwy.net`, доступен с Mac.
2. Подставляет остальные переменные с **`api-server`** (в т.ч. `BY_EGRESS_PROXY_URL`, если задан).
3. Запускает `scripts/run_ice_ingest_once.py --i-know-this-is-prod`.

Переопределение имён сервисов (если в Railway переименовали):

```bash
export RAILWAY_POSTGRES_SERVICE=Postgres-W--1
export RAILWAY_API_SERVICE=api-server
bash scripts/run_ice_ingest_prod_local.sh
```

Успех для Замка в логе выглядит так:

```text
arena_id=3 parser_key=zamok_html_v1 status=ok … slots_published=87 …
```

## Почему не `railway run -s api-server` напрямую

У `api-server` в `DATABASE_URL` часто хост **`postgres-w--1.railway.internal`**. С ноутбука
DNS его не резолвит → `socket.gaierror: nodename nor servname provided, or not known`.

| Переменная | Где | С ноутбука |
|---|---|---|
| `DATABASE_URL` | api-server | internal — **не работает** |
| `DATABASE_PUBLIC_URL` | Postgres | public TCP — **работает** |

В `--service` передаётся **имя сервиса в Railway** (`api-server`), не URL вроде
`https://api-server-production-dcd9.up.railway.app/`.

## Ручной вариант (без обёртки)

```bash
PUB="$(railway run -s Postgres-W--1 -- printenv DATABASE_PUBLIC_URL)"
# asyncpg для нашего кода:
export DATABASE_URL="postgresql+asyncpg://${PUB#postgresql://}"

railway run -s api-server -- env DATABASE_URL="$DATABASE_URL" PYTHONPATH=. \
  python3 scripts/run_ice_ingest_once.py --i-know-this-is-prod
```

URL **не коммитить** в `.env`.

## Что ожидать в выводе

| Строка | Смысл |
|---|---|
| `status=ok` + `slots_published>0` | Слоты записаны |
| `status=empty` | На сайте нет будущих сеансов в горизонте — нормально |
| `status=blocked` + `requires_by_egress` | ledlife/junost с ноутбука без BY-прокси — см. [ice-ingest-by-egress.md](ice-ingest-by-egress.md) |
| `ice ingest scheduler is already running` | Параллельный тик на Railway; подождать и повторить |
| `WARNING: … --i-know-this-is-prod` | Ожидаемо при записи в прод |

Проверка в приложении: карточка арены → чипы времени (для Замка — подпись `N мест`, кроме «Ближайший»).

## Связанные файлы

- `scripts/run_ice_ingest_prod_local.sh` — обёртка (public DB + api-server env)
- `scripts/run_ice_ingest_once.py` — один тик планировщика, все due MK jobs
- `scripts/local_by_egress_proxy.sh` — ingest ledlife/junost с BY IP
