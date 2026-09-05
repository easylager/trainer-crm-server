---
task_id: TASK-071
title: ice_parser_jobs + скедулер + абстрактная стратегия парсера
status: MERGED
phase: done
epic: EPIC3
depends_on: [TASK-048, TASK-050]
execution_mode: SUPERVISED
created_at: 2026-09-05
updated_at: 2026-09-06
city: Минск
design: .ai/DESIGN-INGESTION-PARSERS-V1.md
pr_url: https://github.com/easylager/trainer-crm-server/pull/28
---

# Task

## Objective

Завести сущность «задание на сбор льда» и скедулер, который по `next_run_at` запускает **конкретную стратегию** парсера и передаёт ей метаданные из БД. Без этого каждый каток нельзя настроить отдельно, а крон превращается в хаос из URL в коде.

## Business Context

В табе «Лёд» клиенту нужны только **массовое / свободное катание**. У катков разные публикации: стабильная HTML-сетка (Замок), неделя (Чижовка), JSON/виджет на один день ([Минск-Арена saleframe `/service/55`](https://saleframe.minskarena.by/service/55)). Универсальный LLM-конвейер на 150 вёрсток — не V1. V1 = параметризованный парсер на арену (`DESIGN-INGESTION-PARSERS-V1.md`).

## Scope

### In Scope
- Таблица **`ice_parser_jobs`**: `arena_id` (unique пока 1:1), `parser_key`, `is_enabled`, `cadence` (`hourly|daily|weekly`), `next_run_at`, `last_run_at`, `config jsonb` (URL, API, service_id, флаги вроде `requires_by_egress`, allowlist kind), `notes`.
- Абстракция `IceParser` + регистрация по `parser_key`. На вход — job row; на выход — **сырой `Extraction`** (снимок + поля источника). Не `INSERT` в `ice_sessions`.
- **Общий** `IceSessionNormalizer` + `IceSessionValidator`: любой адаптер после extract даёт один DTO `CanonicalSlotDraft` (поля TASK-050). Скедулер/паблишер принимает только прошедшее валидацию.
- Скедулер: выбирает due jobs → extract → transform → validate → пишет прогон (схема прогонов — TASK-072, здесь достаточно интерфейса/заглушки записи).
- **Рантайм:** цикл регистрируется в `src/bot/notification_service.py` (`asyncio.create_task`), **не** в FastAPI lifespan и не в `webapp.py`. Модуль логики — `src/ingestion/`.
- Админ не обязан в этом TASK: достаточно SQL/seed для Минска.
- Seed job для Минск-Арены: `parser_key=minskarena_saleframe_v1`, `cadence=daily`, `config` из [`.ai/parsers/minsk-arena.md`](../parsers/minsk-arena.md) (`url` виджета + `api_host=https://abws.minskarena.by`, `service_id=55`, `prices_already_minor=true`, `default_duration_minutes=45`).

### Out of Scope
- Реализации всех катков Минска — TASK-061 (первый адаптер saleframe может быть stub, который компилируется).
- `ice_scrape_runs` TTL и % успеха — TASK-072.
- Публикация в `ice_sessions` — TASK-061; контракт DTO и валидатор — **здесь**, чтобы 061 не завёл второй формат.
- LLM.
- Celery, Redis-очередь, Airflow, отдельный ingest-кластер.
- Скрейп внутри HTTP-хендлера админки.

## Acceptance Criteria

### AC-001
Job с `next_run_at` в прошлом подхватывается скедулером; после попытки `next_run_at` сдвигается согласно `cadence`.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-002
Скедулер передаёт в стратегию `config jsonb` без хардкода URL в самом скедулере.
Requirement: CONFIRMED
Verification method: automated/unit (fake parser видит url из config)

### AC-003
Неизвестный `parser_key` → прогон `error`, другие jobs не блокируются.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-004
`is_enabled=false` никогда не запускается.
Requirement: CONFIRMED
Verification method: automated/unit

### AC-005
Два фейковых парсера с разным сырьём (JSON виджета vs HTML-строка) после normalizer+validator дают **одинаковую форму** `CanonicalSlotDraft` (набор полей, типы, minor-цены). Стратегия не содержит SQL и не обходит валидатор.
Requirement: CONFIRMED
Verification method: automated/unit

### AC-006
Цикл скедулера запускается из `notification_service` (или эквивалентного worker-entrypoint `python -m …`), не из процесса API. Статический проход: нет `IceIngestScheduler` в FastAPI lifespan / `webapp.py`.
Requirement: CONFIRMED
Verification method: static + unit (модуль импортируется воркером)

## Technical Notes
- Модуль `src/ingestion/`; не `webapp.py`.
- Имя таблицы **`ice_parser_jobs`**, не `parsers`: парсер — код, job — строка расписания.
- Канон слота — `.ai/DESIGN-INGESTION-PARSERS-V1.md` §3.1. Не плодить `ZamokSession` / `SaleframeTicket` в БД.
- Рантайм — `.ai/DESIGN-INGESTION-PARSERS-V1.md` §2.1.

## Execution History
- **TASK_CREATED** (2026-09-05) — решение владельца: стратегия на каток + скедулер по метаданным
- **CANONICAL** (2026-09-05) — extract отдельно от transform/validate; единый DTO до публикации
- **RUNTIME** (2026-09-05) — цикл в notification_service, не uvicorn; без Celery
- **IN_PROGRESS** (2026-09-06) — PR https://github.com/easylager/trainer-crm-server/pull/28 against `release/ice-discovery`. Status stays IN_PROGRESS until merge. Not MERGED.
- **MERGED** (2026-09-06) — squash `0200398` → `release/ice-discovery`. Scheduler in `notification_service`; stub scrape runs until TASK-072.
