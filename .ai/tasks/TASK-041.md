---
task_id: TASK-041
title: Прошедшие записи сегодняшнего дня скрыты без повторного клика
status: COMPLETE
phase: review
priority: HIGH
created_at: 2026-09-03
updated_at: 2026-09-03
---

# Task

## Objective

Записи сегодняшнего дня, чьё время уже прошло, должны быть видны в расписании сразу
при открытии, без необходимости кликать на день второй раз.

## Business Context

Источник — `.ai/tasks/TASK-004-past-bookings-visibility.md`. Тренер заходит в расписание
в конце дня и не видит только что прошедшие записи, пока не тапнет день ещё раз.

## Scope

### In Scope

- `static/webapp/schedule-editor-main.js`: `filterOutPastSlots`, `scheduleStripDayNeedsPastReveal`.

### Out of Scope

- Скрытие прошедших **дней недели** (не сегодня) — отдельная, не обсуждаемая в брифе
  функция декluttering; `isEntireWeekInPast`/`state.showPastThisWeek` для прошлых дней
  недели не трогаем.

## Comprehension Tips

### Facts

- `filterOutPastSlots(slots)` (`schedule-editor-main.js:5504-5510`) прячет слоты сегодняшнего
  дня, у которых `isSlotEndedInPast(s)` истинно (конец слота раньше текущего времени).
- Вызывается один раз, в `renderCalendar()`: `baseSlots = entirePast || state.showPastThisWeek
  ? state.slots : filterOutPastSlots(state.slots)` (~строка 7650). `state.showPastThisWeek`
  по умолчанию `false` и сбрасывается в `false` при каждой загрузке новой недели.
  Единственный способ увидеть уже прошедшую сегодняшнюю запись — тапнуть день в нижней
  полоске (`onScheduleStripPickDay` ставит `state.showPastThisWeek = true`) — это и есть
  «повторный клик» из жалобы.
- `scheduleStripDayNeedsPastReveal(dateStr)` (~5542-5556) для сегодняшнего дня отдельно
  проверяет `isSlotEndedInPast`, чтобы решить, показывать ли в нижней полоске метку
  «нужно раскрыть».
- `isSlotEndedInPast` используется ещё в двух не связанных местах (визуальное
  затемнение прошедшего слота в списке/чипе) — функцию не удаляем, меняем только два
  вызывающих места.

### Implications

- Минимальная правка: `filterOutPastSlots` больше не прячет сегодняшние прошедшие слоты —
  прячет только слоты прошлых дат. `scheduleStripDayNeedsPastReveal` для сегодняшнего дня
  перестаёт требовать «раскрытия» (нечего раскрывать — уже показано).

## Acceptance Criteria

### AC-001
Открыть расписание в момент, когда у сегодняшнего дня есть хотя бы одна запись с уже
прошедшим временем окончания — эта запись видна в календаре сразу, без клика по дню.
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: браузерная проверка (Playwright, замоканный Telegram WebApp init_data, throwaway
активный тестовый тренер) — слот сегодня 00:00–01:00 (уже завершён), первая же загрузка
расписания без взаимодействия: booking видна (`[data-booking-id]` найден сразу).
Verified at: uncommitted working tree, 2026-09-04

### AC-002
Прошедшие дни **предыдущих** дней недели (не сегодня) по-прежнему скрыты до клика по
нижней полоске — поведение не регрессирует.
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: диф `scheduleStripDayNeedsPastReveal` не менял ветку `dateStr < todayStr` —
условие и тело идентичны до/после правки (единственное изменение — слияние
`dateStr > todayStr` в `dateStr >= todayStr`, что затрагивает только `dateStr === todayStr`).
Verified at: uncommitted working tree, 2026-09-04

### AC-003
Нижняя полоска дней не помечает сегодняшний день как «нужно раскрыть», раз всё уже
показано.
Requirement: INFERRED
Verification method: manual
Result: VERIFIED
Evidence: `scheduleStripDayNeedsPastReveal` теперь возвращает `false` для `dateStr >= todayStr`
безусловно — сегодняшний день никогда не помечается «нужно раскрыть».
Verified at: uncommitted working tree, 2026-09-04

## Technical Plan

1. `filterOutPastSlots`: убрать ветку `isSlotEndedInPast` для сегодняшней даты — фильтровать
   только `s.slot_date < todayStr`.
2. `scheduleStripDayNeedsPastReveal`: объединить условие `dateStr > todayStr` в
   `dateStr >= todayStr` (для сегодня и будущего — всегда `false`, раскрывать нечего),
   убрать отдельную ветку с `isSlotEndedInPast` для `todayStr`.

## Slices

### S1 Всегда показывать прошедшие записи сегодняшнего дня
Goal: сегодняшние прошедшие записи видны без второго клика.
Scope: filterOutPastSlots, scheduleStripDayNeedsPastReveal.
Covers: AC-001, AC-002, AC-003
Verification: manual (браузер)
Estimate: 1
Status: DONE

## Next Action

Задача завершена.

## Execution History

- **TASK_CREATED** — план и слайсы готовы (заведена 2026-09-03 параллельной сессией на
  `wip/schedule-editor-010-042`, восстановлена в `master` 2026-09-04).
- 2026-09-04 | реализация перенесена из `wip/schedule-editor-010-042` (совпадает 1-в-1 с
  Technical Plan): `filterOutPastSlots`, `scheduleStripDayNeedsPastReveal`.
- 2026-09-04 | браузерная верификация (Playwright, замоканный HMAC-подписанный Telegram
  init_data, throwaway тестовый тренер) — 3/3 AC VERIFIED. Тестовые данные удалены после.
- 2026-09-04 | REVIEW clean — диф ровно 2 функции, без побочных изменений.
- 2026-09-04 | COMPLETE
