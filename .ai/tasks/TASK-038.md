---
task_id: TASK-038
title: Сохранение позиции скролла в расписании при возврате из карточки записи
status: READY
phase: verify
priority: HIGH
created_at: 2026-09-03
updated_at: 2026-09-03
---

# Task

## Objective

При открытии карточки записи в расписании и возврате назад (кнопка «назад», системная
кнопка Telegram, `history.back()`) страница должна остаться на том же месте прокрутки,
где была до открытия карточки. Сейчас она всегда возвращается наверх (к понедельнику).

## Business Context

Источник — прямой брифинг тренера (`.ai/tasks/TASK-001-schedule-scroll-position.md`):
тренер пролистывает расписание вниз к нужному дню, открывает запись, закрывает её —
и вынужден заново листать. Мелкий, но частый раздражитель на каждый день использования.

## Scope

### In Scope

- `static/webapp/schedule-editor-main.js` — единственный живой источник экрана расписания
  (`schedule.html` не подключён ни в одном роуте `src/api/app.py`, это мёртвый файл —
  проверено, не трогать).
- Функции `showBookingStack`, `syncAfterBookingPop`.

### Out of Scope

- Прочие сценарии сброса скролла в этом файле (`openCenterDayEditFromCalendar` и другие
  явные `scrollTo(0, 0)` на строках ~5389, ~7062, ~8763) — не про эту жалобу, не трогать.
- Восстановление скролла при смене недели/дня — не про эту жалобу.

## Comprehension Tips

### Facts

- `syncAfterBookingPop()` (`schedule-editor-main.js:1021-1035`) безусловно вызывает
  `window.scrollTo(0, 0)` (строка 1023) и затем один из трёх веток рендера
  (`loadSlots()` / `refreshCalendarChrome()+renderCalendar()` / `loadSlots()`).
- Вызывается из трёх мест: `1092`, `1098` (внутри обработчика «назад» из карточки, когда
  `history.state.ui !== 'sched-detail'`) и `1295` (глобальный `popstate`-листенер).
- `showBookingStack(view)` (`951-959`) переключает CSS-класс `active` между тремя
  полноэкранными «экранами» (`screenMain`/`screenBookingDetail`/`screenBookingDecline`).
  Похоже, именно скрытие `screenMain` (или сама смена активного «экрана») обнуляет
  практический скролл документа — явный `scrollTo(0,0)` довершает это уже намеренно.
- `openBookingDetail(bookingId)` (`1668-1677`) — единственная функция, переводящая с
  главного экрана на карточку записи; вызывает `showBookingStack('detail')`.
- В этом же файле уже есть рабочий паттерн «запомнить-восстановить скролл» —
  `finishCenterCalendarEdit` (~7076-7083): `var scrollY = window.scrollY || 0;` перед
  переключением экрана, затем `requestAnimationFrame(() => window.scrollTo(0, scrollY))`
  после. Решение ниже — тот же приём, не новая абстракция.

### Implications

- Сохранять позицию нужно один раз, в момент ухода с главного экрана (в
  `showBookingStack`, когда `view !== 'main'` и `main` был активен до переключения) —
  это покрывает не только явный переход в карточку, но и decline-экран, не дублируя
  логику захвата в нескольких местах.
- Восстанавливать — в `syncAfterBookingPop`, после веток рендера (через
  `requestAnimationFrame`, как в существующем паттерне), а не безусловным `scrollTo(0,0)`.

## Acceptance Criteria

### AC-001
Открыть карточку записи с любой позиции скролла в расписании (не наверху), закрыть
карточку (кнопка «назад» на экране) — скролл возвращается к исходной позиции, а не к 0.
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: браузерная проверка (Playwright, замоканный Telegram WebApp initData, реальный HMAC
подписанный localhost:8000): scrollTo(420) → открыть карточку (screenBookingDetail active) →
history.back() (тот же путь, что вызывает #btnBack → goBackFromBookingDetail) → scrollY=420,
screenMain active. Точное совпадение.
Verified at: uncommitted working tree, 2026-09-03

### AC-002
То же самое при закрытии карточки системной кнопкой «назад» Telegram (`popstate`).
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: тот же сценарий с scrollTo(610), закрытие через нативный Playwright
`page.goBack()` (system back, тот же popstate-путь) → scrollY=610, screenMain active.
Точное совпадение.
Verified at: uncommitted working tree, 2026-09-03

### AC-003
Первое открытие расписания (без предварительного скролла) не регрессирует —
скролл остаётся на 0, никакого неожиданного прыжка.
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: свежая навигация на /webapp/schedule-editor, без взаимодействия — window.scrollY=0.
Verified at: uncommitted working tree, 2026-09-03

## Technical Plan

1. В `showBookingStack(view)`: перед переключением `classList.toggle('active', ...)`
   на `main`, если `view !== 'main'` и `main.classList.contains('active')` — записать
   `state.scheduleScrollY = window.scrollY || 0`.
2. В `syncAfterBookingPop()`: убрать безусловный `window.scrollTo(0, 0)` сразу после
   `showBookingStack('main')`. В каждой из трёх веток после запуска рендера
   (`loadSlots()` / `renderCalendar()` / финальный `loadSlots()`) добавить восстановление
   через `requestAnimationFrame(function() { window.scrollTo(0, savedScrollY); })`, где
   `savedScrollY = state.scheduleScrollY || 0`, обнулив `state.scheduleScrollY` в начале
   функции.

## Slices

### S1 Сохранение и восстановление скролла
Goal: скролл переживает открытие/закрытие карточки записи.
Scope: showBookingStack, syncAfterBookingPop.
Covers: AC-001, AC-002, AC-003
Verification: manual (браузер, playwright snapshot)
Estimate: 1
Status: DONE

## Next Action

Все 3 AC verified. `/review`, затем закрытие задачи.

## Execution History

- **TASK_CREATED** — заведена 2026-09-03, план и слайсы уже готовы (реализация уже присутствовала
  в рабочем дереве на момент взятия задачи в работу).
- 2026-09-03 | PHASE_STARTED verify | реализация (`showBookingStack`/`syncAfterBookingPop` в
  `schedule-editor-main.js`) уже присутствовала в незакоммиченном рабочем дереве, 1-в-1 совпадает
  с Technical Plan
- 2026-09-03 | браузерная верификация через Playwright (`mcp__playwright__browser_run_code_unsafe`):
  замокан `window.Telegram.WebApp` с реальным HMAC-подписанным `init_data` (throwaway active
  тестовый тренер id=700, временные слоты/бронь — удалены после теста). Первые попытки ловили
  ложные срабатывания (401 из-за кавычек в `.env`-токене при ручном парсинге; `page.click()`
  сам скроллит элемент во вьюпорт, искажая замер до/после) — после перехода на нативный
  `element.click()` через `page.evaluate` все 3 AC подтвердились точным совпадением scrollY.
- 2026-09-03 | PHASE_COMPLETED verify | 3/3 AC VERIFIED
