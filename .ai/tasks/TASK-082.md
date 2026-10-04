---
task_id: TASK-082
title: Таб Лёд — лоадер карты и скрыть «Группы» без набора
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-075, TASK-076]
execution_mode: SUPERVISED
lane: UI-tab
created_at: 2026-09-06
updated_at: 2026-09-06
branch: feat/TASK-082-ice-map-loader-groups
---

# Task

## Objective

Пока Яндекс не нарисовал карту — не пустой серый прямоугольник, а лоадер. Чип «Группы» не показывать, пока в городе нет ни одной открытой группы.

## Scope

- `static/webapp/ice.html`, `ice-tab.js`, `ice-tab.css`, `ice-tab-model.js`, `ice-map.js`, `ice-map-model.js` + API `GET /api/public/ice/cities`, `POST /api/public/ice/interest`.
- Пробный `GET /api/public/training-groups?city_id=&limit=1`.
- Не трогать `arena-card.*`, ingestion, `master`.

## Acceptance Criteria

### AC-001
Вкладка «Карта» до тайлов показывает «Загрузка карты…» со спиннером на `.ice-map-stage`.

### AC-002
Чип «Группы» `hidden`, пока `total` групп в городе = 0. Если сохранён intent=group — сброс на skate.

### AC-003
Смена города не оставляет камеру Минска. Нет катков — empty, не чужая карта.

### AC-004
В дропдауне Льда только города с `map_rink_count > 0` или `trainer_count > 0`. Тренеры без катка: «Скоро добавим катки» + кнопка пишет `ice_city_interest`.

