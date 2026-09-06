---
task_id: TASK-080
title: Карточка арены — сайт/соцсети в Practice и «Открыть» день недели
status: MERGED
phase: done
epic: EPIC3
depends_on: [TASK-052, TASK-074]
execution_mode: SUPERVISED
lane: UI
created_at: 2026-09-06
updated_at: 2026-09-06
branch: feat/TASK-080-arena-practice-links
---

# Task

## Objective

В блоке Practice («Как добраться и что есть») показывать сайт катка и компактные соцсети, если они уже есть в публичном API. Кнопка «Открыть» в вкладке «Неделя» открывает **тот** день, а не сегодня.

## Business Context

`GET /api/public/arenas/{ref}` уже отдаёт `website_url`, `social_urls`, `short_description`. Сайт заполнен у пилотных катков, но на карточке его не видно. «Открыть» с середины недели уводит на сегодня — ломает просмотр расписания.

## Scope

### In Scope
- `static/webapp/arena-card.js`, `arena-card-model.js`, `tests/js/arena-card-model.test.js`.
- Cache-buster `arena-card.js` в `arena.html`.
- Practice: строка сайта (`Сайт катка`, `target=_blank rel=noopener`), компактные ссылки instagram/facebook/vk/telegram только из существующих ключей, однострочный `short_description` под заголовком.
- `data-action="open-day"`: `state.day` = today / tomorrow / ISO из `data-date`; рендер ленты принимает `YYYY-MM-DD`.

### Out of Scope
- `ice-tab.*`, `ice-map.*`, ingestion, loaders, `models.py`.
- Слоты тренеров на ленте льда, янтарная перекраска, букинг `ice_sessions`.
- Выдуманные URL. PR в `master`.

## Acceptance Criteria

### AC-001
При непустом `website_url` в Practice есть ссылка «Сайт катка» на этот URL. Соцсети — только заполненные ключи instagram/facebook/vk/telegram. Пустые поля не рисуются.
Requirement: CONFIRMED
Verification method: automated/unit (`practiceContacts`) + ручной просмотр карточки с сайтом

### AC-002
«Открыть» на дне недели открывает ленту этого дня: сегодня → вкладка Сегодня, завтра → Завтра, иначе лента той даты.
Requirement: CONFIRMED
Verification method: automated/unit (`dayTabFromIso`, `ribbonIsoForDay`)

## Tests
- `node --test tests/js/arena-card-model.test.js`

## Git
Branch from `origin/release/ice-discovery`. PR `--base release/ice-discovery`. Never master.

## Execution History
- **TASK_CREATED** (2026-09-06) — Practice missing website/socials; week «Открыть» always opened today.
- **IN_PROGRESS** (2026-09-06) — TDD helpers `practiceContacts`, `dayTabFromIso`, `ribbonIsoForDay`. 30/30 `tests/js/arena-card-model.test.js`.
- **MERGED** (2026-09-06) — squash `b4454c0` → `release/ice-discovery` (#52, "TASK-080: show rink website on the card and open the tapped week day"). Не в master.
