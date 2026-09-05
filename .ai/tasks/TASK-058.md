---
task_id: TASK-058
title: Тренер в нескольких городах — trainer_cities вместо одного city_id
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: []
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-06
pr_url: https://github.com/easylager/trainer-crm-server/pull/30
---

# Task

## Objective

Сделать географию тренера списком городов, а не одним полем, чтобы тренер с аренами в двух городах находился в обоих каталогах и не пропадал с карточек арен одного из них.

## Business Context

`trainer_profiles.city_id` — одиночный FK, а каталог фильтрует тренеров по городу профиля (`src/infrastructure/repositories/trainer_repository.py:1303`, `AND p.city_id = :city_id`), а не по городам его арен. При этом `trainer_arenas` уже many-to-many и городонезависима — модель данных к мультигороду готова, узкое место ровно одно (`RESEARCH-ARENAS-SCALE-2026-09-02.md` §2.6, T-10).

Для эпика это значит: тренер «Минск + Москва» не появится в блоке «Тренеры на этой арене» на карточке катка того города, который не указан у него в профиле.

## Scope

### In Scope
- Таблица `trainer_cities (trainer_id, city_id, is_primary)` + бэкфилл из `trainer_profiles.city_id` и из городов арен тренера.
- Каталог фильтрует через `EXISTS (SELECT 1 FROM trainer_cities ...)`, а не по `p.city_id`.
- Подсчёт тренеров на арене (`catalog_repository`, счётчики `trainer_count`) переписывается вместе — сейчас он тоже завязан на город профиля.
- `trainer_profiles.city_id` остаётся как «основной город» для обратной совместимости и текстов; не удаляется.
- Список арен в профиле тренера перестаёт быть ограниченным одним городом (иначе сохранение профиля продолжит терять арены другого города).

### Out of Scope
- Переработка UI выбора арены в профиле и онбординге — TASK-054 (переиспользуемый компонент).
- Витрина/допуск — TASK-057.
- Таймзоны по городам — все города UTC+3, вопрос закрыт (T-5).

## Acceptance Criteria

### AC-001
Тренер с аренами в Минске и Москве находится в каталоге обоих городов и показывается в блоке «Тренеры на этой арене» на карточках арен обоих городов.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-002
Сохранение профиля тренером не удаляет его арены в городах, которые форма не показывала.
Requirement: CONFIRMED
Verification method: automated/integration (профиль с ареной в другом городе → сохранение телефона → арены и основная площадка на месте)

### AC-003
Счётчик тренеров на арене считает тренеров по городам их арен, а не по городу профиля, и совпадает с фактическим списком на карточке арены.
Requirement: CONFIRMED
Verification method: automated/integration (счётчик == длина списка)

### AC-004
Бэкфилл не меняет видимость ни одного существующего тренера: до и после миграции каталог каждого города возвращает то же или большее множество тренеров, но не меньшее.
Requirement: CONFIRMED
Verification method: automated/integration (снимок выдачи до/после на тестовых данных)

## Edge Cases

### EDGE-001
Тренер без города в профиле, но с аренами — бэкфилл берёт города из арен; если арен тоже нет, тренер остаётся без городов и не виден в каталоге. Это корректно: заглушку-город не выдумываем.
Severity: MEDIUM
Status: RESOLVED

### EDGE-002
Несколько городов помечены `is_primary` (ошибка данных) — уникальный частичный индекс `uq_trainer_cities_one_primary`.
Severity: LOW
Status: RESOLVED

## Technical Notes
- Миграция: `0197_trainer_cities` (не 0196 — тот номер занят TASK-071 `0196_ice_parser_jobs`, ещё не на train). `down_revision` пока `0195_trainer_arenas_is_public`; после merge 071 переставить на `0196_ice_parser_jobs`.
- Фильтр каталога: `EXISTS trainer_cities` в `list_active_with_details` (не JOIN, чтобы не раздувать DISTINCT).
- Счётчики: `catalog_repository.list_services` / `list_arenas` тоже через EXISTS.
- Профиль: `set_trainer_arenas(..., replace_city_ids=)` — diff только по городам формы; JS не затирает arena_ids, которых нет в загруженном списке города.
- Триггеры держат `trainer_cities` в синхроне с `trainer_profiles.city_id` и публичными `trainer_arenas`.

## Tests
- integration: тренер в двух городах виден в обоих каталогах и на обеих аренах (AC-001)
- integration: сохранение профиля не теряет арены другого города (AC-002)
- integration: счётчик == список (AC-003)
- integration: снимок выдачи до/после бэкфилла (AC-004)
- unit: уникальность `is_primary` (EDGE-002)

## Risks
- Затрагивает основной каталожный запрос — следить за планом выполнения: `EXISTS` по `trainer_cities` не должен ухудшить и без того тяжёлый запрос каталога (там уже есть `DISTINCT` + `LEFT JOIN` + подзапрос по слотам).

## Execution History
- **TASK_CREATED** (2026-09-04) — EPIC3, волна 1; блокер B6
- **IN_PROGRESS** (2026-09-06) — PLACE: trainer_cities + catalog EXISTS + scoped arena replace
- **PR** (2026-09-06) — https://github.com/easylager/trainer-crm-server/pull/30 (base `release/ice-discovery`; do not merge until 071 is on the train and `down_revision` is retargeted)
