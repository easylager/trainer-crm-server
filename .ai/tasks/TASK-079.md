---
task_id: TASK-079
title: Минск-Арена — официальные фото карточки (фасад комплекса)
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-073, TASK-063, TASK-077]
execution_mode: SUPERVISED
lane: CONTENT
created_at: 2026-09-06
updated_at: 2026-09-06
branch: feat/TASK-079-minskarena-card-photo
---

# Task

## Objective

Закрыть единственный пробел стенда «Покататься»: у Минск-Арены (`arena_id=2`) нет hero/thumb. Найти кадры на официальном сайте/ABWS (не Google, не сток, не Instagram scrape), записать в досье и загрузить в **local** стенд 076.

## Scope

### In Scope
- Досье `.ai/data/arena-cards/minsk-minskarena.md`: Photos + проверяемые amenities (parking/cafe), если есть именованные объекты катка.
- `--apply --only-arena-ids 2 --no-seed-sessions` на local `trainer_crm` (стенд 076 uploads). Не ingest, не prod.
- Короткий отчёт `.ai/data/arena-cards/TASK-079-minskarena-photos.md`

### Out of Scope
- UI (`ice-tab.*` / `arena-card.*`) — TASK-076 PR #49
- BY-egress junost/ledlife
- Менять slug `manezh` (бэкфилл 048; отдельный SCHEMA)
- Выдумывать прокат/заточку/часы МК
- PR в `master`

## Acceptance Criteria

### AC-001
Досье Минск-Арены содержит ≥1 URL фото с `license=operator` и `source_url` на minskarena.by или abws.minskarena.by. Концерт/шоу/логотип SVG/графический баннер МК — не hero.
Status: CONFIRMED
Verification: `.ai/data/arena-cards/minsk-minskarena.md` Photos — 3 operator URLs (ABWS objects + `/object.html`). Rejected concert/show/SVG/graphic in Conflicts.

### AC-002
На стенде `GET /api/public/ice/arenas?intent=skate&city_id=2` у id=2 `thumb` не null; `GET /api/public/arenas/2` отдаёт `hero`.
Status: CONFIRMED
Verification: 2026-09-06 stand :8000 — id=2 thumb 200 jpeg; card hero+gallery=3; skate list 5/5 thumbs.

### AC-003
Лоадер по-прежнему отказывается писать в cloud/prod.
Status: CONFIRMED
Verification: script unchanged this TASK; apply used local `localhost:5432/trainer_crm` + `--allow-local-dev-db`.

## Execution History

- **TASK_CREATED** (2026-09-06) — follow-up стенда: 4/5 thumbs, Минск-Арена skip.
- **CONTENT** (2026-09-06) — ABWS `/api/v3/arena/home` objects «Арена» / «Конькобежный стадион» + `object-bg.jpg`. Amenities parking+cafe. Apply только id=2 на стенд 076. Branch not pushed.
