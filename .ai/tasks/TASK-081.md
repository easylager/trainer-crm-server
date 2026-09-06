---
task_id: TASK-081
title: Карточка арены — тело не прятать через data-screen
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-052]
execution_mode: SUPERVISED
lane: UI
created_at: 2026-09-06
updated_at: 2026-09-06
branch: feat/TASK-081-arena-card-visible
---

# Task

## Objective

На карточке арены снова видно hero, ленту льда и Practice: сейчас `#arenaRoot` с `data-screen` скрыт глобальным `[data-screen] { display: none }` из `mini-app-components.css`.

## Scope

- `static/webapp/arena.html`, `arena-card.css`, `tests/api/test_arena_card_webapp.py`.
- Не трогать каталог, Ice tab, ingestion, `master`.

## Acceptance Criteria

### AC-001
`#arenaRoot` не использует `data-screen` без класса `active`. После открытия `/webapp/arena?ref=5` в корне есть `.arena-hero` (не пустой экран с одним заголовком).
