---
task_id: TASK-083
title: BY-egress VPS для ledlife/junost — провижининг и подключение к скедулеру
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-071, TASK-072]
execution_mode: SUPERVISED
lane: INGEST
created_at: 2026-09-06
updated_at: 2026-09-06
---

# Task

## Objective

Дать воркеру `notification_service` реальный белорусский исходящий IP, чтобы можно было безопасно включить `ice_parser_jobs` для `ledlife` и `junost` (сейчас `requires_by_egress=true`, `is_enabled=false`; скедулер безусловно блокирует такие job — `src/ingestion/scheduler.py:72-83`, `error_code="requires_by_egress"`).

## Business Context

**PDEC-004** (`.ai/decisions.md`, ACCEPTED 2026-09-06 владельцем): небольшой VPS в Беларуси (hoster.by / A1 Cloud, ~$3–5/мес) + туннель (WireGuard/SSH) обратно к тому же Docker-образу, а не коммерческий BY-резидентный прокси и не ручной ввод. Globalping-проверка (см. EPIC3 «Открытые вопросы» / DESIGN-INGESTION-PARSERS-V1.md §6.2) уже показала: BY IP через прокси не спуфится, спуфинг заголовков запрещён спекой — нужен настоящий IP.

## Scope

### In Scope
- Завести VPS у белорусского хостера (hoster.by или A1 Cloud) — **ручное действие владельца** (оплата, аккаунт); эта задача не покупает инфраструктуру сама.
- Поднять туннель (WireGuard или SSH reverse tunnel) от прод-образа `notification_service` до VPS так, чтобы HTTP-запросы `ledlife`/`junost` парсеров шли через BY-исходящий узел.
- Механизм в коде, которым воркер узнаёт «сейчас исходящий трафик реально BY» — не полагаться на голое `is_enabled=true`; например явный конфиг/env (`BY_EGRESS_PROXY_URL` или аналог) плюс сохранение текущей безусловной блокировки как fallback, если конфиг пуст.
- Включить `is_enabled=true` и `requires_by_egress` остаётся `true` (флаг не снимается — он теперь просто удовлетворён) для job `ledlife` и `junost` в `.ai/data/minsk-parser-registry.yaml` / `ice_parser_jobs`.
- Один прогон каждого job на реальном сайте (`ledlife.by/massovye_kataniya/`, `junost.by/seansy_massovogo_kataniya_na_vyhodnyh/`) через новый egress; сверка результата с существующими спеками/фикстурами (парсер-код уже есть, если фикстуры валидны).

### Out of Scope
- Сами парсер-адаптеры `ledlife`/`junost`, если их ещё нет как класса — это TASK-061 lane, не эта задача (проверить фактическое состояние перед стартом).
- Header-spoofing или иные способы подделать geo — прямо запрещено (`DESIGN-INGESTION-PARSERS-V1.md` §6.2).
- Коммерческий резидентный прокси, ручной ввод админом — отклонённые альтернативы PDEC-004.
- PR в `master`.

## Acceptance Criteria

### AC-001
VPS в Беларуси поднят и туннель до `notification_service` работает; исходящий IP воркера подтверждён как BY (напр. через Globalping или запрос к сервису geo-IP с самого туннеля).
Status: OPEN
Verification: ручная проверка + запись IP/провайдера в Execution History (без секретов в git)

### AC-002
`ledlife` job даёт `ok`/`empty` прогон (не `blocked`/`error` из-за geo) минимум один раз на реальном сайте. `junost` — тот же критерий, но только после того, как `junost_weekend_grid_v1` будет засеян в `ice_parser_jobs` (TASK-065 lane); до тех пор эта задача покрывает только `ledlife`.
Status: OPEN
Verification: запись в `ice_scrape_runs`, скрин/лог прогона

### AC-003
Без настроенного BY-egress (конфиг пуст/недоступен) скедулер по-прежнему блокирует эти job с тем же `error_code="requires_by_egress"` — регресса безопасности нет.
Status: VERIFIED
Verification: `tests/ingestion/test_scheduler.py::test_requires_by_egress_job_still_blocked_without_worker_config` (fallback, unchanged behavior) и `::test_requires_by_egress_job_runs_when_worker_has_by_egress_configured` (позитивный путь) — `pytest tests/ingestion/ -q` → 73 passed.

## Technical Notes
- Точка входа блокировки: `src/ingestion/scheduler.py:69-83` (`config_requires_by_egress`).
- **Реализовано (AC-003):** `IceIngestScheduler(..., by_egress_configured: bool = False)` — конструкторская инъекция, не чтение env напрямую внутри планировщика (совпадает со стилем остальных зависимостей класса). `job.config["requires_by_egress"]` никогда не снимается; блокировка снимается только когда воркер сам подтверждает egress.
- Источник флага в проде: `Settings.by_egress_proxy_url` (`src/shared/config.py`, env `BY_EGRESS_PROXY_URL`) → `src/ingestion/loop.py` передаёт `by_egress_configured=bool(get_settings().by_egress_proxy_url)` при создании планировщика внутри `notification_service`. Пусто/не задано → прежнее поведение (безопасный дефолт).
- `.env.example` получил закомментированный плейсхолдер `BY_EGRESS_PROXY_URL` с пояснением — без реального значения.
- Секреты (VPS-доступ, ключи туннеля) — только в реальном `.env`/секрет-хранилище, никогда в `.env.example` или в git.
- Реестр парсеров: `.ai/data/minsk-parser-registry.yaml` фиксирует BY-geo-block на обоих сайтах (спуфинг X-Forwarded-For не помог) — **но в `ice_parser_jobs` сегодня реально существует и заблокирован только `ledlife_origin_html_v1`** (arena_id 4, «Манеж»; проверено координатором 2026-09-06 напрямую в БД). `junost_weekend_grid_v1` описан в реестре, но ещё не засеян как job (TASK-065 lane) — эта задача снимает BY-egress-блокировку для `ledlife` сейчас; для `junost` то же самое понадобится **после** его сидинга в `ice_parser_jobs`, отдельным шагом, не одновременно. (Ранее здесь ошибочно стояло `ledlife` = arena_id 5 — это на самом деле `ledby_html_v1`/led.by, другой, уже включённый и здоровый сайт.)
- **Мастер-скрипт для AC-001 (человеческие шаги):** `scripts/provision-by-egress-vps.sh` — интерактивный wizard, проводит владельца через выбор/оплату VPS (hoster.by / A1 Cloud), генерацию WireGuard-туннеля (или SSH `-D` фолбэк), проверку исходящего IP через ipinfo.io (сырой ответ печатается для ручной проверки — скрипт не доверяет себе на слово), запись `BY_EGRESS_PROXY_URL` в локальный `.env` и подсказку по включению `is_enabled` для job ledlife/junost. Не запускался целиком (блокируется на человеческом вводе/платном хостинге) — проверен `bash -n` и статической трассировкой.

## Execution History
- **TASK_CREATED** (2026-09-06) — координатор: follow-up из PDEC-004 (`.ai/decisions.md`, PR #53) после подтверждения владельцем «свой VPS в Беларуси». Инфраструктура ещё не поднята — задача READY, не в работе.
- **RENUMBERED** (2026-09-06) — TASK-082 → TASK-083: номер TASK-082 занят параллельным PR #56 («Ice map loader and hide empty Группы chip»), коллизия обнаружена координатором до мержа.
- **AC-003_VERIFIED** (2026-09-06) — конфигурационный fallback в `scheduler.py`/`config.py`/`loop.py` + два unit-теста; `scripts/provision-by-egress-vps.sh` создан для AC-001. AC-001/AC-002 остаются OPEN — требуют реального VPS и оплаты владельцем, агент их выполнить не может. `status` → `IN_PROGRESS` (не `MERGED`): инфраструктурная часть не сделана.
- **PREMISE_CORRECTED** (2026-09-06) — G-R2 hardening pass поймал две фактические ошибки: (1) `ledlife` = arena_id 4 «Манеж», не 5 (5 — это `ledby_html_v1`/led.by, отдельный уже включённый и здоровый сайт); (2) `junost_weekend_grid_v1` есть только в `.ai/data/minsk-parser-registry.yaml`, в `ice_parser_jobs` его нет — сегодня заблокирован только `ledlife`. AC-002 и Technical Notes поправлены.
