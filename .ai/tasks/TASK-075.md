---
task_id: TASK-075
title: Таб «Лёд» и карта — закрыть vs прототип
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-053, TASK-054]
execution_mode: SUPERVISED
lane: UI-tab
created_at: 2026-09-06
updated_at: 2026-09-06
branch: feat/TASK-075-ice-tab-map-close
---

# Task

## Objective

Довести таб «Лёд» (список + карта) до утверждённого прототипа. TASK-053/054 на train — первый проход; карта — только таб, Яндекс, AC-004/005 профиля/онбординга **не** этот TASK.

## Business Context

Линза «Покататься» показывает арену **только** при будущем слоте МК/свободного. Карта — способ выбрать каток, не украшение. Без ключа Яндекса — empty state, не откат на OSM.

## Design Reference

`.ai/design/arenas-client-app-prototype.html` — **«Лёд — список»**, **«Лёд — карта»**.  
Живой прототип тайлов: `.ai/design/ice-tab-map-yandex.html` (если есть на ветке).

## Scope

### In Scope
- `static/webapp/ice.html`, `ice-tab.js`, `ice-tab.css`, `ice-tab-model.js`, `ice-map.js`, `ice-map-model.js` (и тесты).
- Список: шапка города, поиск, чипы намерения, живая строка взр/дет/прокат, переключатель Список/Карта.
- Линза «Покататься»: только арены с ≥1 будущим `public_skate|open_ice`.
- Карта: кластеры, bbox, «рядом со мной» только по кнопке, шит нашей карточки арены (не карточка организации Яндекса).
- EDGE: геолокация отклонена — карта полезна; город без арен — честный empty, не пустая карта.
- Cache-buster ассетов таба/карты.

### Out of Scope
- `arena.html`, `arena-card.*` — TASK-074.
- `catalog-main.js` (кроме неизбежной точки входа таба, если уже есть — не раздувать).
- Профиль тренера и онбординг (TASK-054 AC-004/AC-005 остаются waived).
- OSM / Leaflet fallback.
- `src/ingestion/`.
- PR в `master`.

## Acceptance Criteria

### AC-001
Экран списка совпадает с прототипом: чипы, поиск, живая строка с тремя ценами, линза «Покататься» без арен без будущих слотов.
Requirement: CONFIRMED
Verification method: automated/unit на модель списка + design-review vs prototype

### AC-002
Карта: кластеры с числом, загрузка по bbox при панорамировании, пин уровня A с ближайшим сеансом, шит → `arena.html` той же арены.
Requirement: CONFIRMED
Verification method: automated/unit на модель карты + manual/exploratory если есть ключ

### AC-003
«Рядом со мной» не запрашивает геолокацию при старте; отказ геолокации не блокирует карту.
Requirement: CONFIRMED
Verification method: automated/unit

### AC-004
Нет `YANDEX_MAPS_JS_API_KEY` → empty state таба карты, **без** OSM.
Requirement: CONFIRMED
Verification method: automated/unit

## Technical Notes
- Провайдер: Yandex Maps JS API. Ключ `YANDEX_MAPS_JS_API_KEY` / `GET /api/public/ice/map-config`.
- Git: branch from `release/ice-discovery`, PR `--base release/ice-discovery`. **Never master.**

## Tests
- unit/integration уже существующие `ice-tab` / `ice-map` — не регрессировать
- новые кейсы: skate lens filter, geo denied, missing key, bbox payload

## Execution History
- **TASK_CREATED** (2026-09-06) — координатор: 053/054 MERGED как первый проход; close-out vs прототип. Профиль/онбординг не в scope. Train only.
- **IN_PROGRESS** (2026-09-06) — close-out list+map vs prototype: client skate-lens filter, bbox payload without city_id, pin sheet → arena.html, missing-key/empty-city without OSM, geo-denied keeps map.
