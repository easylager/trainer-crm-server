---
task_id: TASK-074
title: Карточка арены — закрыть vs прототип (edges, 360px, темы)
status: MERGED
phase: execute
epic: EPIC3
depends_on: [TASK-052]
execution_mode: SUPERVISED
lane: UI-card
created_at: 2026-09-06
updated_at: 2026-09-06
branch: feat/TASK-074-arena-card-close
---

# Task

## Objective

Довести экран карточки арены до утверждённого прототипа. Первый проход TASK-052 на train есть; **не закрыто:** visual 360px / светлая+тёмная тема, EDGE «идёт сейчас», плейсхолдер без фото, «закрыт до …» приоритетнее ленты.

## Business Context

G-R2 меряется на этом экране: клиент видит лёд и переходит к тренеру. Расхождение с прототипом — стоп и вопрос, не «улучшить».

## Design Reference

`.ai/design/arenas-client-app-prototype.html` — экраны **«Арена (есть расписание)»** и **«Арена (расписания нет)»**.

## Scope

### In Scope
- `static/webapp/arena.html`, `arena-card.js`, `arena-card.css`, `arena-card-model.js` (и тесты к ним).
- EDGE-001 TASK-052: нет фото → hero-плейсхолдер, не пустой блок.
- EDGE-002: сеанс идёт сейчас → читается как «идёт».
- EDGE-003: арена закрыта на сезон → «закрыт до …» выше ленты.
- AC-007 TASK-052: 360 px, светлая и тёмная тема Telegram, без горизонтального скролла.
- Сверка блоков с прототипом: порядок, легенда ленты, ghost «Билет на месте» на МК (не «Записаться»).

### Out of Scope
- `ice.html`, `ice-tab.*`, `ice-map.*` — TASK-075.
- `catalog-main.js`.
- `src/ingestion/`.
- Профиль тренера / онбординг.
- PR в `master`.

## Acceptance Criteria

### AC-001
Карточка уровня A совпадает с прототипом по порядку блоков, цветовому коду строк (синяя полоса МК + ghost «Билет на месте»; янтарная — занятие + «Записаться»/«Заявка») и легенде под лентой.
Requirement: CONFIRMED
Verification method: design-review vs prototype + automated/unit на модель ленты

### AC-002
Сеанс с `starts_at <= now < ends_at` показывается как «идёт», не пропадает между «прошло» и «сегодня».
Requirement: CONFIRMED
Verification method: automated/unit

### AC-003
Нет hero-фото → плейсхолдер; сезонное закрытие перекрывает ленту текстом «закрыт до …».
Requirement: CONFIRMED
Verification method: automated/unit

### AC-004
360 px и обе темы без горизонтального скролла; cache-buster ассетов карточки обновлён.
Requirement: CONFIRMED
Verification method: design-review (узкий viewport) + grep cache-buster

## Technical Notes
- Данные только из публичного Ice API (TASK-051). Уровень A/B/C не считать на клиенте заново.
- МК read-only. Не вызывать `goBooking` со строки `public_skate` / `open_ice`.
- Git: branch from `release/ice-discovery`, PR `--base release/ice-discovery`. **Never master.**

## Tests
- unit: «идёт сейчас», пустой день недели, нет фото, сезонное закрытие
- не ломать существующие tests вокруг arena-card

## Execution History
- **TASK_CREATED** (2026-09-06) — координатор: 052 MERGED как первый проход; close-out vs прототип. Train only.
- **IN_PROGRESS** (2026-09-06) — TDD close-out: live session stays as «идёт» (past dropped), hero placeholder, seasonal «закрыт до …» over the ribbon, legend/stripe in the model. Visual 360px/themes still need a human screenshot.
- **MERGED** (2026-09-06) — https://github.com/easylager/trainer-crm-server/pull/45 squash `3c66356` → `release/ice-discovery`. Не в master. 360px/темы — ручной скриншот.
