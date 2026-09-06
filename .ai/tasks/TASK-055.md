---
task_id: TASK-055
title: Связки — тизер «Лёд рядом» на главной и арены на карточке тренера
status: MERGED
phase: execute
epic: EPIC3
depends_on: [TASK-051]
execution_mode: AUTONOMOUS
created_at: 2026-09-04
updated_at: 2026-09-06
pr_url: https://github.com/easylager/trainer-crm-server/pull/34
---

# Task

## Objective

Связать новый раздел с существующими экранами двумя маленькими вставками: строкой-тизером ближайшего льда на главной и чипами арен на карточке тренера, ведущими обратно на карточки катков.

## Business Context

Главная — хаб удержания, он работает и не переделывается. Одна строка-тизер даёт вход в новый раздел тем, кто открывает приложение по привычке. Чипы арен на карточке тренера делают граф двусторонним: с арены к тренеру и с тренера обратно на арену — без этого новый раздел остаётся тупиковой веткой (`DESIGN-ARENAS-CLIENT-APP.md` §2.4).

## Design Reference

Экраны прототипа **«Главная»** (блок «Новое на главной»: янтарная строка «Лёд рядом — сегодня в 11:00 · Чижовка · 2,4 км · массовое, взр. 12 BYN») и **«Тренер»** (блок «Работает на аренах» с чипами и подпись про место занятия).

## Scope

### In Scope
- Строка-тизер на `client-home`: ближайший по времени сеанс на ближайшей арене; тап ведёт на карточку арены. Скрывается целиком, если в городе нет ни одной арены уровня A (не показывать пустое обещание).
- Чипы арен на карточке тренера (в каталоге и в «моём тренере»), ведущие на карточки арен; основная арена отмечена.
- Подпись места занятия на слотах карточки тренера — арена конкретного слота (совместно с TASK-056).

### Out of Scope
- Любая другая перестройка главной — хаб не трогаем.
- Уведомления о новом льде («на вашем катке добавили массовое катание») — отдельная задача после появления данных.

## Acceptance Criteria

### AC-001
На главной появляется одна строка с ближайшим сеансом и ареной; тап открывает карточку этой арены.
Requirement: CONFIRMED
Verification method: manual/exploratory + automated/unit

### AC-002
Если ближайшего сеанса нет (нет арен уровня A рядом), строка не показывается вовсе — без заглушек и «скоро».
Requirement: CONFIRMED
Verification method: automated/unit (пустые данные → блок отсутствует)

### AC-003
Карточка тренера показывает арены чипами; тап ведёт на карточку арены; основная арена визуально отмечена.
Requirement: CONFIRMED
Verification method: manual/exploratory + automated/unit

### AC-004
Остальная главная не изменилась: карточка «мой тренер», ближайшие записи, абонементы, серия — на месте и работают.
Requirement: CONFIRMED
Verification method: regression (существующие тесты hub) + manual

## Edge Cases

### EDGE-001
Тренер работает на 6 аренах — чипы не должны ломать вёрстку карточки; показывать N и «ещё M».
Severity: LOW
Status: OPEN

### EDGE-002
Ближайший сеанс начинается через 15 минут — формулировка должна быть осмысленной («сегодня в 11:00» против «через 15 минут»).
Severity: LOW
Status: OPEN

## Technical Notes
- Главная: `static/webapp/client-home.html`, `client-home-main.js`, стили `mini-app-client-home.css`; данные лучше добавить в существующий `/client/hub/bootstrap`, а не отдельным запросом при загрузке главной.
- Карточка тренера: `catalog.html#screenTrainerDetail`, `catalog-main.js`.

## Tests
- unit: рендер тизера с данными и без (AC-001, AC-002)
- unit: чипы арен, отметка основной, «ещё M» (AC-003, EDGE-001)
- regression: тесты хаба (AC-004)

## Risks
- Дополнительный запрос при загрузке главной ухудшит время до первого экрана — данные тизера класть в существующий bootstrap.

## Execution History
- **TASK_CREATED** (2026-09-04) — EPIC3, волна 3
- **IN_PROGRESS** (2026-09-06) — UI lane: hub teaser «Лёд рядом» from `/client/hub/bootstrap` (session city, future MK only) + trainer-card arena chips with primary mark and «ещё M». Map (TASK-054) not touched. PR https://github.com/easylager/trainer-crm-server/pull/34 (not merged).
- **TASK-055_MERGED** (2026-09-06) — squash `3786958` → `release/ice-discovery` https://github.com/easylager/trainer-crm-server/pull/34. Не в master.
