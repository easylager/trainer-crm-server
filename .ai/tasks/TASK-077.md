---
task_id: TASK-077
title: На стенде — живые слоты МК и фото арен
status: MERGED
phase: done
epic: EPIC3
depends_on: [TASK-049, TASK-061, TASK-063, TASK-065]
execution_mode: SUPERVISED
lane: DATA
created_at: 2026-09-06
updated_at: 2026-09-06
branch: feat/TASK-077-minsk-demo-slots-photos
---

# Task

## Objective

В **том стенде, который смотрит владелец**, на табе «Лёд» видны карточки катков с будущими слотами МК и hero/thumb с официальных фото. Это ops+данные на train, не новая фича списка.

## Strategy

```yaml
strategy:
  state_required: true
  research_required: true
  research_areas:
    - ice_sessions skate filter
    - media loader dry-run vs apply
  clarification_required: true
  planning_required: true
  verification_level: standard
```

Workflow chain: `research → plan → implement → verify`

## Business Context

Владелец не видит карточек и фото. Код списка и hero **уже на** `release/ice-discovery`. Default линза `intent=skate` скрывает арену без будущего `public_skate|open_ice`. `media` пустая, пока нет admin upload или `load_minsk_arena_cards.py --apply`. Не «чинить» пустой список показом всех арен — это TASK-076 AC-005 / правило эпика.

## Scope

### In Scope

- Выяснить стенд (local train / deploy train). **Не** писать в prod: лоадер и `run_ice_ingest_once.py` отказывают cloud host.
- Миграции 0192–0198 на этом стенде
- `--apply` лоадера досье на **local** DB (профили + фото, что `would-upload`)
- Прогон ingest / etalon seed, чтобы на «Покататься» был ≥1 будущий слот у пилотных катков (Замок, Минск-Арена, Чижовка, DiaMond, led.by — что проходит без BY-egress)
- Достать недостающие официальные файлы туда, где dry-run дал 0 upload (junost/ledlife 403, minskarena нет кадра) — только сайт/соцсеть катка, `license=operator`
- Короткий отчёт: какие арены с thumb + слотом, какие skip и почему

### Out of Scope

- UI таба / токены / чип «Тренеры» — TASK-076
- Включать `requires_by_egress` jobs без реального BY IP
- Apply на production
- PR в `master`

## Acceptance Criteria

### AC-001
На стенде владельца `GET /api/public/ice/arenas?intent=skate&city_id=<Минск>` возвращает ≥3 арен с непустой живой строкой (будущий слот).
Status: CONFIRMED
Verification: curl против стенда + скрин таба «Лёд»

### AC-002
У тех же арен list `thumb` и card `hero` не null (кроме явно skip в отчёте).
Status: CONFIRMED
Verification: API + UI

### AC-003
Скрипты по-прежнему отказываются писать в prod/cloud DB.
Status: CONFIRMED
Verification: existing refuse tests / dry run against non-local DSN

### AC-004
Отчёт: арена → фото (да/skip+причина) → слоты (да/нет+причина). Junost/ledlife без BY не включаются «чтобы было».
Status: CONFIRMED
Verification: markdown report in `.ai/data/arena-cards/`

## Comprehension Tips

### Facts

- Пустые карточки: `arena_public_use_cases.py` для `intent=skate` → `future_count > 0`.
- Лоадер: `scripts/load_minsk_arena_cards.py`; отчёт `TASK-063-load-report.md` = `mode: dry-run`. `--apply` только local. Follow-up фото #41.
- В репо один бинарь: `photos/minsk-diamond/bannerled.png`; остальное URL в досье.
- Адаптеры на train: minskarena_saleframe, zamok, chizhovka, ledby, diamond. BY-egress jobs выключены.
- Fixture-даты (напр. minsk-arena `2026-09-06`) быстро протухают — нужен ingest, не разовый etalon из прошлого.
- Worker: `notification_service` крутит `run_ice_ingest_scheduler_loop`. One-shot: `scripts/run_ice_ingest_once.py` (local only).

### Open Questions

- Q-002: какой стенд смотрит владелец (local Mini App на train vs задеплоенный бот)? Без ответа AC-001 нельзя закрыть. **HUMAN_GATE.**

## Technical Plan

### Approach

Сначала стенд. Потом migrate → apply карточек → ingest слотов → проверить skate API. Код UI не трогать. Если стенд = deploy без права `--apply`, завести тот же train локально и показать владельцу local URL / ngrok — не обходить prod-guard.

### Changes

- Операции и, при нужде, догрузка файлов в `.ai/data/arena-cards/photos/`
- Новый отчёт `.ai/data/arena-cards/TASK-077-stand-report.md`
- Код скриптов — только если apply/ingest ломается на train (багфикс), не новая архитектура

### Tests

- Не регрессировать refuse-prod
- Ручной curl skate list + один hero URL открывается

### Parallelism

Параллелен TASK-076 (разные файлы). Не параллелить второго DATA-агента на ту же БД.

## Risks

- Стенд = prod → стоп, не apply.
- Saleframe/HTML сегодня пустой → карточек легитимно нет; тогда ручной admin seed на 7 дней пилота, не ослаблять фильтр.
- Q-002 блокирует выполнение.

## Execution History

- **TASK_CREATED** (2026-09-06) — координатор: пустые карточки/фото = данные на стенде, не TASK-053.
- **PHASE_STARTED | plan** (2026-09-06)
- **PHASE_COMPLETED | plan** (2026-09-06)
- **HUMAN_GATE** (2026-09-06) — нужен стенд владельца (Q-002), иначе некуда apply.
- **PHASE_STARTED | execute** (2026-09-06) — DATA: local `trainer_crm` (localhost, not cloud). Migrations already 0198. Loader `--apply --allow-local-dev-db --only-arena-ids 2,3,5,6,7` (skip local arena 4 = Манеж). Live ingest for enabled MK jobs; junost/ledlife stay off. Skate API `city_id=2` → 5 items with live lines, 4 thumbs; minskarena photo skip (no ice/facade on origin). Report: `.ai/data/arena-cards/TASK-077-stand-report.md`.
- **PR** (2026-09-06) — https://github.com/easylager/trainer-crm-server/pull/50 (base `release/ice-discovery`). Coordinator merges.
- **MERGED** (2026-09-06) — squash `34a6486` → `release/ice-discovery` (#50). Не в master.
