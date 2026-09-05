---
task_id: TASK-072
title: ice_scrape_runs — статусы прогонов, TTL, процент успеха источника
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-071]
execution_mode: SUPERVISED
created_at: 2026-09-05
updated_at: 2026-09-06
city: Минск
design: .ai/DESIGN-INGESTION-PARSERS-V1.md
pr_url: https://github.com/easylager/trainer-crm-server/pull/31
---

# Task

## Objective

Хранить каждую попытку сбора стейтфул, чистить старьё и дать админу процент успешных прогонов по каждому `ice_parser_jobs`, чтобы чинить сломанный адаптер, а не гадать.

## Business Context

Клиентский список «покататься» показывает арену **только если есть будущий слот МК/свободного**. Если парсер честно нашёл ноль — это не уровень A и не повод рисовать вчерашнее. Админ должен видеть: `ok` / `empty` / `error` / `blocked` и долю `ok` за 7 и 30 дней. Иначе «почему Чижовка пропала» не расследуется.

## Scope

### In Scope
- Таблица **`ice_scrape_runs`**: `job_id`, `arena_id`, `started_at`, `finished_at`, `status` (`ok|empty|error|blocked`), `http_status`, `slots_found`, `error_code`, `error_summary`, `raw_ref` (снимок, опционально).
- Правило клиента (контракт для TASK-051/053): арена в табе «Лёд» (линза «покататься») **только** при ≥1 `ice_sessions` с `kind in (public_skate, open_ice)` и `starts_at > now` и не просроченным `valid_until`.
- `empty` / `error` / `blocked` **не удаляют** будущие слоты от прошлого `ok`.
- TTL: прогоны > 90 дней удалять, оставить последний любой + последний `ok`; слоты с `ends_at` старше 14 дней — удалять.
- Админский разрез: success rate по job/арене за 7д и 30д; пометка «результата нет» если последний завершённый прогон не `ok` и нет будущих слотов.

### Out of Scope
- Внешний APM.
- Автоотключение job при падении % — только отображение + алерт (текст в admin-бот можно связать с TASK-062).

## Acceptance Criteria

### AC-001
Каждый запуск стратегии оставляет строку прогона со статусом; без прогона и без прохождения валидатора канона нельзя «тихо» обновить слоты.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-002
Прогон `empty` при существующих будущих слотах оставляет их на месте.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-003
Доля `ok` за 30 дней считается как `ok / all_finished` по job и видна в админском разрезе (хотя бы API/SQL, полный UI не обязателен).
Requirement: CONFIRMED
Verification method: automated/unit + ручная проверка запроса

### AC-004
TTL-джоб не удаляет последний `ok` прогон даже если ему > 90 дней.
Requirement: CONFIRMED
Verification method: automated/integration

## Execution History
- **TASK_CREATED** (2026-09-05)
- **IN_PROGRESS** (2026-09-06) — `ice_scrape_runs` persistence via `SqlAlchemyScrapeRunRecorder`, TTL loop in `notification_service`, success rate 7d/30d + «результата нет». Alembic `0198_ice_scrape_runs`. PR https://github.com/easylager/trainer-crm-server/pull/31
