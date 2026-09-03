---
task_id: TASK-039
title: Использованные абонементы не отделены от активных в списке выданных
status: READY
phase: estimate
priority: MEDIUM
created_at: 2026-09-03
updated_at: 2026-09-03
---

# Task

## Objective

В списке выданных абонементов и сертификатов (раздел «Абонементы» → вкладка «Выданные»)
активные должны идти раньше закрытых/использованных, а не вперемешку по дате выдачи.

## Business Context

Источник — `.ai/tasks/TASK-002-used-passes-organization.md`. Бо́льшая часть жалобы уже
закрыта существующим кодом (см. Comprehension Tips) — компактная сводка в карточке
клиента вообще не показывает использованные абонементы, а полный список «Выданные»
уже умеет фильтровать по статусу и визуально отличает активные/закрытые карточки.
Реально отсутствует только сортировка при фильтре «Все».

## Scope

### In Scope

- `src/application/trainer_issued_use_cases.py::list_trainer_issued_items` — сортировка
  результата перед пагинацией.

### Out of Scope

- Компактная сводка в карточке клиента (`static/webapp/trainer-clients-main.js:3572-3633`) —
  уже фильтрует только активные, ничего доделывать не нужно.
- UI вкладки «Выданные» (`static/webapp/trainer-pass-products-main.js`) — фильтр по статусу,
  цветовая маркировка `live`/`closed`, счётчик — уже реализованы, не трогаем.

## Comprehension Tips

### Facts

- `list_trainer_issued_items` (`trainer_issued_use_cases.py:70-278`) собирает пассы и
  сертификаты в один список `items`, помечая каждый `status_bucket` (`active`/`closed`,
  строки 148, 231), и сортирует **только** по `issued_at DESC` (строка 255) перед
  пагинацией (`items[off:off+lim]`, строка 269). При фильтре `status=all` активные и
  закрытые перемежаются по дате выдачи.
- Фронтенд (`trainer-pass-products-main.js:585-655`) рендерит `state.issuedItems` в том
  порядке, в котором пришли — клиентской сортировки нет и не нужно: пагинация серверная
  (`limit`/`offset`), поэтому сортировать нужно **до** среза страницы, то есть на бэкенде.

### Implications

- `items.sort()` в Python стабильна: повторная сортировка только по бакету поверх уже
  отсортированного по дате списка сохраняет порядок «новее выше» внутри каждого бакета
  — не нужно собирать составной ключ вручную.

## Acceptance Criteria

### AC-001
При фильтре статуса «Все» все элементы с `status_bucket == 'active'` идут в списке
раньше элементов с `status_bucket == 'closed'`; внутри каждой группы сохраняется
сортировка по `issued_at` (новые выше).
Requirement: CONFIRMED
Verification method: unit
Result: NOT_VERIFIED

### AC-002
Фильтры «Активные» и «Закрытые» и пагинация (`total`, `has_more`, `active_count`) не
меняют поведение — правка не трогает подсчёт, только порядок при `status=all`.
Requirement: CONFIRMED
Verification method: unit
Result: NOT_VERIFIED

## Technical Plan

После `items.sort(key=lambda x: x.get("issued_at") or "", reverse=True)` (строка 255)
добавить один стабильный сорт: `items.sort(key=lambda x: x.get("status_bucket") != "active")`.

## Slices

### S1 Активные выше закрытых при сортировке «Все»
Goal: список issued-items группирует активные перед закрытыми.
Scope: list_trainer_issued_items.
Covers: AC-001, AC-002
Verification: unit-тест на функцию с фикстурными данными разных статусов и дат.
Estimate: 1
Status: READY

## Next Action

Реализовать S1, добавить unit-тест.
