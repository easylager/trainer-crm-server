---
task_id: TASK-057
title: Витрина и допуск — разделить trainer_arenas на «где меня искать» и «где мне можно вести»
status: MERGED
phase: done
epic: EPIC3
depends_on: []
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-06
pr_url: https://github.com/easylager/trainer-crm-server/pull/27
---

# Task

## Objective

Добавить `trainer_arenas.is_public` и развести два разных смысла, которые сегодня несёт одна таблица: «эта арена показывается в моей витрине» и «мне разрешено ставить здесь слот/бронь».

## Business Context

Сейчас одна связь отвечает сразу за две вещи. Из-за этого: (а) блок «Тренеры на этой арене» на новой карточке будет показывать тренеров, которые там не принимают, а просто однажды провели занятие; (б) запрошенная тренерами механика «не привязываюсь к арене, но при записи говорю где» невозможна — постановка слота на непривязанную арену отвечает «Площадка не привязана к вашему профилю» (`RESEARCH-ARENAS-SCALE-2026-09-02.md` §2.7, T-11).

## Scope

### In Scope
- Миграция: `trainer_arenas.is_public BOOLEAN NOT NULL DEFAULT true` (существующие связи остаются витринными — поведение не меняется).
- Каталог и карточка арены показывают и фильтруют только `is_public = true`.
- При постановке слота/брони на арену, к которой тренер не привязан, связь создаётся автоматически с `is_public = false` — в пределах городов тренера и только для активных арен. Существующие проверки `EXISTS (SELECT 1 FROM trainer_arenas ...)` продолжают работать: строка просто появляется в момент использования.
- Управление публичностью в профиле тренера: арена в списке может быть «показывать в моей карточке» или «только для расписания».

### Out of Scope
- Мультигород тренера — TASK-058 (ограничение «в пределах городов тренера» до её выполнения читается как «город профиля»).
- Формат «выездной тренер» (`arena_work_format=mobile`) как таковой не меняется.
- Подсчёт тренеров на арене — переписывается в TASK-058 вместе с городами.

## Acceptance Criteria

### AC-001
Тренер с форматом «выезд» или без привязки может поставить запись на конкретный каток; клиент видит это место в брони; при этом каталог и карточка арены не показывают эту арену как площадку тренера.
Requirement: CONFIRMED
Verification method: automated/integration (создать бронь на непривязанной арене → связь создана с `is_public=false`; в публичном списке тренеров арены его нет)

### AC-002
Существующие связи после миграции остаются публичными — ни один тренер не пропадает из каталога в момент выката.
Requirement: CONFIRMED
Verification method: automated/integration (бэкфилл: все существующие строки `is_public=true`) + SQL-проверка на проде после миграции

### AC-003
Тренер может в профиле переключить арену между «показывать в карточке» и «только для расписания», и это сразу отражается в публичной выдаче.
Requirement: CONFIRMED
Verification method: manual/exploratory + automated/integration

### AC-004
Автосоздание связи не даёт тренеру ставить слоты на арены неактивные или вне его городов.
Requirement: CONFIRMED
Verification method: automated/integration (арена другого города / `is_active=false` → отказ, связь не создаётся)

## Edge Cases

### EDGE-001
Тренер снял публичность у единственной арены — его карточка остаётся без площадок. Нужно решить, показывать ли его в каталоге вообще и с какой подписью.
Severity: MEDIUM
Status: OPEN

### EDGE-002
Автосозданная непубличная связь остаётся навсегда после единственной разовой записи — со временем накапливается «мусорный» список площадок в профиле.
Severity: LOW
Status: OPEN

## Technical Notes
- Таблица `trainer_arenas` — `src/infrastructure/db/models.py` (M2M рядом с `Arena`).
- Места проверки допуска: `src/api/routes/webapp.py` (постановка слотов и ручная запись, проверки `EXISTS ... trainer_arenas`), `src/application/booking_use_cases.py`.
- Публичная выдача: `src/infrastructure/repositories/trainer_repository.py` (список тренеров каталога), `catalog_repository.py` (арены и счётчики).

## Tests
- integration: автосоздание непубличной связи при записи на непривязанную арену (AC-001)
- integration: бэкфилл — все старые связи публичны (AC-002)
- integration: переключение публичности → изменение публичной выдачи (AC-003)
- integration: отказ для чужого города / неактивной арены (AC-004)

## Risks
- Задача трогает и публичную выдачу, и допуск к записи — при ошибке тренеры либо пропадают из каталога, либо получают доступ к чужим аренам. Тесты на оба направления обязательны.

## Execution History
- **TASK_CREATED** (2026-09-04) — EPIC3, волна 1; блокер B5
- **IN_PROGRESS** (2026-09-06) — PLACE: `trainer_arenas.is_public` DEFAULT true; auto-create `is_public=false` on slot/booking; catalog filters public only; profile chip toggle. EDGE-001 left open (hiding the last public arena can drop the trainer from catalog; no new empty-state). PR: https://github.com/easylager/trainer-crm-server/pull/27
- **MERGED** (2026-09-06) — squash `498060c` into `release/ice-discovery`. CI green. Not merged to master.
