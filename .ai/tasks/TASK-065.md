---
task_id: TASK-065
title: Seed ice_parser_jobs from the Minsk census (no auto-discovery of 150 rinks)
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-048, TASK-071]
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-06
city: Минск
---

# Task

## Objective

Загрузить в `ice_parser_jobs` известные источники Минска из переписи и реестра парсеров. Конвейеру нужны строки заданий, не поиск 150 площадок.

## Business Context

V1 — не «найти сайт катка автоматически». Сайты уже найдены в TASK-064 и спеках `.ai/parsers/`. Осталось превратить реестр в enabled/disabled jobs. Автопоиск VK/Telegram и таблица `arena_sources` — не этот TASK (старая формулировка отменена 2026-09-05).

## Scope

### In Scope
- Импорт из `.ai/data/minsk-parser-registry.yaml` (и/или `.ai/parsers/minsk-*.md` `job.config`) в `ice_parser_jobs`.
- Одна арена — один job (1:1, как TASK-071).
- `is_enabled=false` если `requires_by_egress` (Юность, ledlife) или нет фикстуры / источник blocked.
- `is_enabled=true` только для катков с готовой спекой без BY-блокера (Минск-Арена stub уже сеется в 071 — не дублировать конфликтом unique arena_id).
- Идемпотентный повтор импорта (повторный прогон не плодит jobs).
- Команда или миграция/скрипт, который можно прогнать на staging.

### Out of Scope
- Таблица `arena_sources` и автопоиск 150 катков.
- TASK-059 observations bus.
- Реализации парсеров — TASK-061 (job может указывать `parser_key`, которого ещё нет в registry: тогда 071 уже пишет прогон `error`, это ок).
- Включение BY-egress jobs.
- Instagram scrape.

## Acceptance Criteria

### AC-001
После импорта у каждой спеки Минска с `parser_key` есть строка `ice_parser_jobs` с URL/config из спеки, без хардкода в скедулере.
Requirement: CONFIRMED
Verification method: automated/integration (fixture registry → rows)

### AC-002
Jobs с `requires_by_egress=true` создаются выключенными и не запускаются скедулером.
Requirement: CONFIRMED
Verification method: automated/unit

### AC-003
Повторный импорт не создаёт дубликат по `arena_id`.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-004
Катки skip (не МК) не получают enabled job.
Requirement: CONFIRMED
Verification method: automated/unit

## Edge Cases

### EDGE-001
Seed 071 для Минск-Арены уже есть — импорт обновляет config, не падает на unique.
Severity: MEDIUM
Status: OPEN

## Technical Notes
- Модуль `src/ingestion/`. Не HTTP-скрейп в админке.
- Реестр: `.ai/data/minsk-parser-registry.yaml`. Спеки: `.ai/parsers/minsk-*.md`.

## Tests
- integration: import registry → jobs (AC-001, AC-003, EDGE-001)
- unit: BY-egress disabled (AC-002); skip arenas (AC-004)

## Execution History
- **TASK_CREATED** (2026-09-04) — старая формулировка `arena_sources` + автопоиск
- **REFRAMED** (2026-09-06) — координатор: V1 = seed jobs из переписи; depends_on TASK-071, не TASK-059
- **IN_PROGRESS** (2026-09-06) — идемпотентный импорт `ice_parser_jobs` из `.ai/data/minsk-parser-registry.yaml` + `.ai/parsers/minsk-*.md`. BY-egress jobs (Юность, ledlife) создаются выключенными. Skip (не МК) не получают job. EDGE-001: upsert обновляет seed 071, не дублирует unique `arena_id`.
