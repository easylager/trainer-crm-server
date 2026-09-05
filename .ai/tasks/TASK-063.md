---
task_id: TASK-063
title: Ручное наполнение первого города данными (операционная)
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-048, TASK-049, TASK-073]
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-06
city: Минск
lane: CONTENT
pr_url:
---

# Task

## Objective

Заполнить руками **карточки** Минска из досье TASK-073 и эталон слотов там, где парсера ещё нет — чтобы гейт «карточку открывают» проверялся на реальных данных.

## Business Context

Код профиля и медиа — TASK-048/049. Сбор фактов и фото — TASK-073. Парсеры несут **слоты МК**. Эта задача — **загрузка в продукт** (админка / SQL на копии), не повторный ресёрч.

## Scope

### In Scope
- Минск, целевые МК-арены из TASK-073.
- Загрузить в `arena_profiles` проверенные поля досье; загрузить фото только с `license` из досье (через админку TASK-049).
- Ручные `ice_sessions` **только** для арен без рабочего адаптера (или как эталон на одну неделю для TASK-066). Где SPEC+061 уже дают слоты — не дублировать руками.
- Замерить время загрузки одной арены из готового досье.

### Out of Scope
- Сбор фактов с сайтов — TASK-073.
- Реализация media-слоя — TASK-049.
- Автосбор слотов — TASK-061.

## Acceptance Criteria

### AC-001
В Минске целевые МК-арены из TASK-073 загружены: профиль published, ≥1 лицензионное фото если досье его дало, слоты либо от парсера либо ручной эталон на 7 дней если адаптера нет.
Requirement: CONFIRMED
Verification method: SQL + сверка с досье
Notes: Loader UPSERTs all 7 profiles as `published` from verified fields. **No media rows** — every photo is skip (нужно разрешение / wait-for-grant / no file). Session seed is implemented (`source_id=etalon_073`, ≤7 days) but **0 rows on this train** because SPEC `expected.json` is not on `release/ice-discovery`. Pytest seeds 1 zamok slot on `trainer_crm_test` (rolled back).

### AC-002
Для каждой заполненной арены записан источник расписания и дата, на которую данные верны.
Requirement: CONFIRMED
Verification method: ручная проверка таблицы источников
Notes: Profile `verified_at` comes from the dossier header (2026-09-06). Session rows would set `source_id=etalon_073` and `valid_until` = end of the 7-day horizon. Per-arena schedule source: see Load result below (dossier `source` column + fixture path when present).

### AC-003
Измерено и записано среднее время заполнения и обновления одной арены.
Requirement: CONFIRMED
Verification method: запись результата в этот файл по завершении
Notes: see Load result.

## How to run

Dry-run (default, no DB writes):

```bash
PYTHONPATH=. python scripts/load_minsk_arena_cards.py
```

Apply on local test DB only:

```bash
DATABASE_URL=postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm_test \
  PYTHONPATH=. python scripts/load_minsk_arena_cards.py --apply
```

`--apply` refuses cloud/prod hosts and refuses database names other than `trainer_crm_test` unless `--allow-local-dev-db` (local `trainer_crm` only). Never production.

Tests: `pytest tests/ops/test_load_minsk_arena_cards.py`

## Load result (2026-09-06)

Dry-run of 7 TASK-073 dossiers on `feat/TASK-063-load-minsk-cards`. Prod DB not touched. Apply verified on `trainer_crm_test` inside pytest (transaction rollback) for zamok.

| arena_id | slug | profile | photo | sessions | blockers | ops min |
|---|---|---|---|---|---|---|
| 2 | minskarena | **published** — district, phone, website, hours note (admin), amenities all unknown/unset, socials IG+FB | skip (no photo) | skip — no `expected.json` on train | — | 2 |
| 3 | zamok | **published** — fullest: district, 2 phones, website, daily 10:00–23:00, season 1–12, 4 amenities true (parking/accessibility unset), VK/FB/IG | skip ×9 нужно разрешение | skip — no fixture on train; pytest seeded 1× public_skate `etalon_073` | — | 4 |
| 4 | minsk-ledlife | **published** — district + website + short_description; phone/hours/amenities **NULL/{}** | skip ×3 (403 + нужно разрешение) | skip empty/403-only even if fixture present | **ledlife.by 403** | 2 |
| 5 | ledby | **published** — district, phone (admin A1), website, daily касса 10:00–22:00, 4 amenities, IG+VK | skip ×6 нужно разрешение | skip — no fixture on train | — | 2 |
| 6 | chizhovka | **published** — district, phone, website, daily 07:00–23:00, 3 amenities, 4 socials | skip ×3 нужно разрешение | skip — no fixture on train | — | 2 |
| 7 | minsk-diamond | **published** — district, phone, website, hours 10:00–22:00 (days not claimed daily), 2 amenities, socials empty (not in dossier table) | **skip DiaMond PNG wait-for-grant**; other URLs skip | skip — no fixture on train | wait grant for bannerled.png | 3 |
| 8 | minsk-junost | **published** — district Комаровка (suburb, not invented city_district), phone, website, 3 amenities; hours unknown | skip ×3 (403 / нужно разрешение) | skip empty/403-only | **junost.by 403** | 2 |

Mean operator time from a *ready* dossier (read card + dry-run + confirm photo/session decisions): **~2.4 min/arena**. Script parse mean **~0.2 ms/arena**; full batch dry-run **~2 ms**. Research time is TASK-073, not this task.

### Photo decisions (no `media` inserts)

All CDN uploads skipped. DiaMond `photos/minsk-diamond/bannerled.png` is operator-hosted locally but TASK-073 still said wait for grant — **not** inserted as published media. Google/search images are never downloaded.

Detail: `.ai/data/arena-cards/TASK-063-load-report.md`

### Session seed

| arena | would seed if fixture on train | this train |
|---|---|---|
| 2 minskarena | ≤7 days public_skate from `minsk-arena/expected.json` | skipped (file absent) |
| 3 zamok | ≤7 days from `minsk-zamok/expected.json` | skipped (file absent); unit test seeds 1 |
| 4 ledlife | skip (403-only / empty sessions) | skip |
| 5 ledby | ≤7 days from `minsk-ledby/expected.json` | skipped (file absent) |
| 6 chizhovka | ≤7 days from `minsk-chizhovka/expected.json` | skipped (file absent) |
| 7 diamond | ≤7 days from `minsk-diamond/expected.json` | skipped (file absent) |
| 8 junost | skip (403-only / empty sessions) | skip |

When SPEC fixtures land on the train, re-run `--apply` on `trainer_crm_test`. `valid_until` = end of the 7-day horizon; `source_id=etalon_073`. TASK-061 adapters are not called.

## Open Questions

- **Q-001 — РЕШЕНО 2026-09-04:** первый город = **Минск**. Москва — после воспроизводимой модели.

## Risks
- Соблазн заполнить «красиво все арены» вместо 10–15 с полным расписанием — для гейта волны 2 важнее глубина, чем ширина.
- Ручные данные протухают через неделю. Если TASK-062 (алерты по устареванию) ещё не сделан, нужен человек, который перезаполняет — иначе первый же гейт будет измерен на протухших данных.
- Session etalon cannot land until SPEC `expected.json` is on `release/ice-discovery` (or copied into the apply environment).

## Execution History
- **TASK_CREATED** (2026-09-04) — EPIC3, волна 2; статус BLOCKED до ответа на Q-001
- **UNBLOCKED** (2026-09-04) — владелец продукта: первый город Минск; status → READY
- **SPLIT** (2026-09-05) — ресёрч карточки/фото → TASK-073; 063 = загрузка в продукт + ручные слоты только без адаптера
- **IN_PROGRESS** (2026-09-06) — CONTENT/SCHEMA ops loader `scripts/load_minsk_arena_cards.py` + tests. Dry-run parses 7 dossiers; apply on `trainer_crm_test` updates zamok; unknown amenities unset; no media; no prod writes. PR against `release/ice-discovery` (not merged).
