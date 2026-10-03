# Ingest льда с белорусского IP (СДЮШОР / Юность)

Пошагово: как вручную обновить расписание катков, которые не отдают сайт без IP
Беларуси, и как часто это делать, чтобы в приложении было актуальное расписание.

Теория (планировщик, `schedule_stale`, алерты): [ops/ice-freshness-and-alerts.md](../ops/ice-freshness-and-alerts.md).

## Кто что обновляет

| Источник | Где крутится | Нужен BY IP |
|---|---|---|
| Минск-Арена, Чижовка, Замок, большинство региональных BY | `notification_service` на Railway | нет |
| **ledlife.by** (СДЮШОР, `minsk-ledlife`, arena_id 4) | см. ниже | **да** |
| **junost.by** (ХК «Юность», arena_id 8) | см. ниже | **да** |

На Railway у `notification_service` **нет** `BY_EGRESS_PROXY_URL` → задания
`ledlife_origin_html_v1` и `junost_origin_html_v1` там получают статус `blocked` и
**сами не подтягивают** расписание. Пока не появится BY-прокси в env воркера, прод
обновляют **с ноутбука в РБ** (этот runbook).

Автоопрос остальных катков: цикл раз в **60 с**, после успешного прогона следующий
запрос примерно через **45 мин** (днём). Расписание считается устаревшим
(`schedule_stale: true`), если успешного `ok` не было дольше **6 часов** (порог по
умолчанию, см. `stale_after_hours` в конфиге задания).

## Как часто гонять ingest с ноутбука

Цель — чтобы у СДЮШОР и Юности в API не висел `schedule_stale` и сеансы совпадали с
сайтом.

| Режим | Как часто | Зачем |
|---|---|---|
| **Минимум в сезон МК** | **2–3 раза в день** (утро, после обеда, вечер) | Укладываемся в порог 6 ч, пользователь видит свежие даты |
| **Комфортно** | **каждые 3–4 часа** в часы работы катков | Ближе к поведению остальных арен (45 мин на воркере) |
| **После простоя** | один раз сразу | Восстановить витрину после отпуска/выходных |
| **Межсезонье / пустой сайт** | по необходимости | Парсер вернёт `empty` — это нормально, старые сеансы не сотрутся |

Практичный ориентир: **поставить напоминание 09:00 и 18:00** в будни, в выходные —
ещё раз около полудня, если идут массовые катания.

Долгосрочно: BY VPS + `BY_EGRESS_PROXY_URL` на Railway — тогда тот же
`notification_service` будет опрашивать ledlife/junost сам, без ноутбука (см. раздел
в [ice-freshness-and-alerts.md](../ops/ice-freshness-and-alerts.md#белорусский-выход-by_egress_proxy_url)).

## Однократная настройка (Mac в Беларуси)

1. Клон репозитория, `.venv`, зависимости — как для обычной разработки.
2. **VPN выключен** (иначе ipinfo покажет не BY).
3. Установить tinyproxy: `brew install tinyproxy`.
4. Один раз:
   ```bash
   bash scripts/local_by_egress_proxy.sh setup
   ```
   Появятся `.local/tinyproxy-by.conf`, пароль в `.local/by-egress-proxy.env` (в git не
   попадает) и строка `BY_EGRESS_PROXY_URL=...` в `.env`.

## Полный прогон на прод (СДЮШОР + конькобежный + ремонт арен)

После деплоя `master` с repair-скриптами:

```bash
export DATABASE_URL='<Railway → Postgres → Connect → Public URL, asyncpg>'
bash scripts/local_by_egress_proxy.sh start   # отдельный терминал
bash scripts/prod_minsk_ice_rollout.sh
```

Скрипт по порядку: `repair_minsk_ledlife_arena_row` → `repair_minskarena_hockey_mk_target` → `seed_ice_parser_jobs` → `local_by_egress_proxy.sh ingest`.

Только БД без ingest: `bash scripts/prod_minsk_ice_rollout.sh --skip-ingest`.

## Каждый запуск ingest

### Терминал 1 — прокси (держать открытым)

```bash
cd /path/to/trainer-crm-server
bash scripts/local_by_egress_proxy.sh start
```

### Терминал 2 — прод-БД и ingest

1. Взять **публичный** Postgres URL из Railway (`DATABASE_PUBLIC_URL`), **не** коммитить:
   ```bash
   export DATABASE_URL='postgresql+asyncpg://…'
   ```
   В `.env` для других задач может быть `localhost` — для прода **важно** именно
   `export` в этой сессии (или временно подменить `DATABASE_URL` в `.env`).

2. Проверка прокси и сайтов:
   ```bash
   bash scripts/local_by_egress_proxy.sh check
   ```
   В блоке `via local proxy` страна должна быть **BY**. Для junost/ledlife — ответ не
   `403`.

3. Прогон:
   ```bash
   bash scripts/local_by_egress_proxy.sh ingest
   ```
   Это `run_ice_ingest_once.py --i-know-this-is-prod` с `BY_EGRESS_PROXY_URL` из `.env`.

   Флаг `--i-know-this-is-prod` **откажется**, если `DATABASE_URL` указывает на
   `localhost` — так защищаемся от записи в локальную БД «по ошибке».

4. В выводе искать строки вида:
   ```
   arena_id=4 parser_key=ledlife_origin_html_v1 status=ok … slots_published=…
   arena_id=8 parser_key=junost_origin_html_v1 status=ok|empty …
   ```
   - `ok` — сеансы записаны в прод.
   - `empty` — на сайте нет будущих слотов в разметке (часто устаревшие даты на
     junost.by), это не 403.
   - `blocked` — нет прокси или обрезанный HTML.

### Проверка в API

```bash
curl -s 'https://api-server-production-dcd9.up.railway.app/api/public/arenas/minsk-ledlife/sessions' \
  | jq '.sessions[0] | {local_date, starts_at_local, price_adult_minor, price_child_minor, age_note}'

curl -s 'https://api-server-production-dcd9.up.railway.app/api/public/ice/arenas?city_id=2' \
  | jq '.arenas[] | select(.id==4 or .id==8) | {id, slug, tier, freshness}'
```

Ожидание после удачного ingest: у ledlife есть сеансы, `freshness.schedule_stale` —
`false`, `schedule_observed_at` — недавнее время; цены взрослый/детский заполнены,
если страница `stoimost_uslug` пришла целиком.

## Локальная БД (без прода)

Для отладки парсера на `localhost`:

```bash
# DATABASE_URL из .env на локальный Postgres
PYTHONPATH=. .venv/bin/python scripts/run_ice_ingest_once.py
```

Без `--i-know-this-is-prod`. BY-прокси всё равно нужен для live-fetch ledlife/junost.

## Обновить HTML-фикстуры (опционально)

После смены вёрстки сайта или для регрессионных тестов:

```bash
# tinyproxy запущен, VPN выкл.
bash scripts/fetch_minsk_by_origin_fixtures.sh
```

Файлы лежат в `data/fixtures/minsk-ledlife/` и `data/fixtures/minsk-junost/`.

## Если что-то пошло не так

| Симптом | Что проверить |
|---|---|
| `ProdDatabaseError` / localhost | `export DATABASE_URL` на Railway URL |
| `blocked` / 403 | VPN, прокси `start`, `check` → BY |
| Слоты есть локально, на проде пусто | ingest шёл не в ту БД |
| Цены `null` | `stoimost_uslug` без таблицы цен — перезапросить страницу через прокси |
| Юность `empty` | На сайте нет актуальных дат в таблице — не баг прокси |
| `ice ingest scheduler is already running` | На Railway одновременно крутится воркер; подождать или повторить |

Метаданные арены СДЮШОР в проде (город Минск, slug `minsk-ledlife`): при необходимости
`PYTHONPATH=. python scripts/repair_minsk_ledlife_arena_row.py` с тем же `DATABASE_URL`
и `--i-know-this-is-prod` (см. help скрипта).

## Связанные файлы

- `scripts/local_by_egress_proxy.sh` — setup / start / check / ingest
- `scripts/run_ice_ingest_once.py` — one-shot, два прохода (сначала BY-egress)
- `data/parsers/minsk-ledlife.md`, `data/parsers/minsk-junost.md` — контракт парсеров
