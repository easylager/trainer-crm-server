---
task_id: TASK-076
title: Лёд = токены приложения; «Тренеры» остаётся в хроме Льда
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-053, TASK-074, TASK-075]
execution_mode: SUPERVISED
lane: UI
created_at: 2026-09-06
updated_at: 2026-09-06
branch: feat/TASK-076-ice-app-tokens-coach-lens
pr_url: https://github.com/easylager/trainer-crm-server/pull/49
---

# Task

## Objective

Экраны «Лёд» и карточка арены остаются по **структуре** как сейчас, но по **цвету и компонентам** совпадают с остальным Mini App (GLIDE teal, не янтарный прототип). Чип «Тренеры» **не** уводит на старый `catalog.html`: список живёт в том же хроме, что и «Покататься».

## Strategy

```yaml
strategy:
  state_required: true
  research_required: true
  research_areas:
    - Ice tab vs catalog chrome mismatch
    - media/ice_sessions empty vs skate lens
    - prototype amber vs app teal tokens
  clarification_required: false
  planning_required: true
  verification_level: elevated
```

Workflow chain: `research → plan → implement → design-review → verify`

## Business Context

Владелец 2026-09-06 сверстал план с реальностью, не с доской:

1. Карточек катков не видно.
2. Фото арен нет.
3. Структура Льда верна, палитра **не** согласована с приложением.
4. «Тренеры» открывает чужой экран.

Пункты 1–2 — **не этот TASK** (данные: TASK-077). Здесь только 3–4. Не переоткрывать 052/053/074/075: они закрывали **прототип** (янтарь). Новый SoT цвета — живое приложение, не `arenas-client-app-prototype.html`.

## Design Reference

- **Структура / IA:** прототип «Лёд — список», чипы Покататься / Тренеры / Группы, карточка арены.
- **Цвет / CTA / чипы / карточки:** `theme.css` + `mini-app-client-theme.css` (`--glide-brand`, `--app-cta-fill` / `#45B9BB`, `--accent-rgb`). Комментарий DEC-005: teal CTA, not amber.
- **Не копировать** хардкод `#c2761a` из `ice-tab.css` / прототипа.

Различие МК vs занятие тренера — полоска/лейбл («Билет на месте» vs «Записаться»), не второй бренд-цвет на чипах и шапке.

## Scope

### In Scope

- `static/webapp/ice.html`, `ice-tab.js`, `ice-tab.css`, `ice-tab-model.js`
- `static/webapp/arena.html`, `arena-card.css` (и JS только если CTA/чипы завязаны на янтарь)
- Чип `coach`: остаться на `ice.html`; не вызывать `ClientShell.navigate('catalog?tab=catalog')`
- Список линзы «Тренеры» в том же хроме (поиск, город, список/карта как у Льда, карточки в языке `ice-acard`)
- Группы уже остаются на списке — не ломать

### Out of Scope

- Засев `ice_sessions` / `media` / `--apply` лоадера — TASK-077
- Менять правило «Покататься» = только будущие МК-слоты
- Парсеры, скедулер, `src/ingestion/`
- Переписывать воронку `catalog.html` целиком (можно оставить deep-link на карточку тренера)
- PR в `master`

## Acceptance Criteria

### AC-001
Чипы, акценты, CTA на `ice.html` и шапке карточки арены используют токены приложения (`--app-cta-fill` / `--accent-rgb`), без янтарного `#c2761a` как бренд-цвета экрана.
Status: CONFIRMED
Verification: grep на `#c2761a` в ice/arena CSS + visual vs Главная/Записи

### AC-002
Чип «Тренеры» не открывает `catalog.html` как замену экрана. Пользователь остаётся в `ice.html` (тот же хедер города, поиск, чипы, список/карта).
Status: CONFIRMED
Verification: unit на `intentChipAction` + browser: chip → URL всё ещё `ice`

### AC-003
Линза «Тренеры» показывает список в языке карточек Льда (не 4-шаговая воронка catalog). Пустой список — честный empty в том же хроме, не редирект.
Status: CONFIRMED
Verification: unit на модель + browser

### AC-004
Тап по тренеру из этой линзы ведёт на существующий профиль/запись тренера (deep-link), не ломая booking. МК по-прежнему read-only.
Status: CONFIRMED
Verification: browser + unit (нет `goBooking` со строк skate)

### AC-005
Линза «Покататься» по-прежнему скрывает арены без будущего `public_skate|open_ice`. Пустой стейт не «чинят» показом всех катков.
Status: CONFIRMED
Verification: existing skate-lens tests

## Comprehension Tips

### Facts

- Код R1–R3 UI на `origin/release/ice-discovery` @ `0ea90c1`, **не** в `master`, **не** в текущем WT `feat/TASK-068-profile-data-guards`.
- 048–075 на train **MERGED**. Доска/эпик в WT врут: «next = 053».
- Второй таб на train: «Лёд» → `ice.html`. Чип «Тренеры»: `intentChipAction` → `{ type: 'catalog', href: 'catalog?tab=catalog' }` (`ice-tab-model.js`).
- Default intent `skate` → API `GET /api/public/ice/arenas?intent=skate` фильтрует `future_count > 0`. Пустой список = нет живых слотов, не сломанный UI.
- Фото: `thumb` / `hero` только из published `media`. Лоадер 063 в отчёте **dry-run**; prod apply запрещён скриптом.
- `ice-tab.css` хардкодит amber `#c2761a`; приложение — teal `#45B9BB`.

### Patterns

- Один UI-писатель на `ice-tab.*` / `arena-card.css` (LANES.md). Не параллелить 076 с другим агентом в этих файлах.
- Данные параллельны: TASK-077 не трогает `static/webapp/`.

### Open Questions

- Q-001: **РЕШЕНО владельцем 2026-09-06:** «реши сам, главное не уходить в старый каталог». Default: **список тренеров города** в хроме Льда (карточки в языке `ice-acard`). Не арены-без-фильтра и не `catalog.html`.

## Technical Plan

### Approach

Не новый экран и не рестайл catalog. Снять редирект чипа; отрендерить `intent=coach` внутри существующего `renderList()`. Заменить янтарные литералы на CSS-переменные приложения. Карточка арены — те же переменные, полоски МК/занятия оставить как кодировку типа строки.

### Changes

1. `ice-tab-model.js` — `intentChipAction('coach')` → `{ type: 'list', intent: 'coach' }`; убрать обязательный `catalogHref` как навигацию экрана. Deep-link на тренера оставить.
2. `ice-tab.js` — ветка coach: загрузка списка тренеров (или арен с тренерами — см. Q-001 default тренеры), те же empty/error, что у skate.
3. `ice-tab.css` + `arena-card.css` — токены `--app-cta-fill` / `--accent-rgb`; убрать `#c2761a` как бренд.
4. Тесты модели чипа и списка.

### Data/API

- Skate/group: как сейчас, `GET /api/public/ice/arenas`.
- Coach: существующий публичный список тренеров города (catalog/public), не новый ingest. Если эндпоинта нет — узкий read-only, не бронь.

### Tests

- `intentChipAction('coach').type === 'list'`
- skate filter regression
- CSS/token: нет `#c2761a` в ice/arena brand rules
- browser: chip Тренеры, chip Покататься, карточка арены CTA

### Slices (один агент, подряд)

1. Токены (AC-001)
2. Чип без редиректа + список тренеров (AC-002, AC-003, AC-004)
3. Регресс skate (AC-005) + visual vs Главная

### Parallelism

| Агент | TASK | Пишет | Не пишет |
|---|---|---|---|
| UI (этот) | 076 | `static/webapp/ice-*`, `arena-card.css` | ingestion, loader |
| DATA | 077 | scripts/apply, local DB | `static/webapp/` |
| Не стартовать 3-го кодящего в UI | — | — | `catalog-main.js` без нужды |

Максимум **2** кодящих субагента. CONTENT-фото (скачать официальные файлы) можно третьим, без `src/` / `static/webapp/`.

## Risks

- Q-001 не подтверждён — если владелец хотел арены с тренерами, список тренеров будет «не то». Дешёвый откат: переключить payload, хром тот же.
- 074 AC янтарных занятий vs прототип **сознательно ломаем** по решению владельца 2026-09-06.
- Без TASK-077 визуал 076 проверяется на плейсхолдерах и пустом skate — это нормально.

## Execution History

- **TASK_CREATED** (2026-09-06) — координатор: сверка train vs доска; владелец закрыл SoT цвета (приложение, не прототип) и линзу «Тренеры» (не catalog.html).
- **PHASE_STARTED | plan** (2026-09-06)
- **RESEARCH** (2026-09-06) — 3 investigator: UI / data / git. Факты в Comprehension Tips.
- **PHASE_COMPLETED | plan** (2026-09-06)
- **IN_PROGRESS** (2026-09-06) — UI: Ice/arena chrome → `--app-cta-fill` / `--accent-rgb` (без `#c2761a`); чип «Тренеры» остаётся на `ice.html` и грузит `GET /api/public/trainers?city_id=`; тап по карточке — существующий `catalog?tab=catalog&trainer_id=`; skate lens без ослабления.
- **PR** (2026-09-06) — https://github.com/easylager/trainer-crm-server/pull/49 → `release/ice-discovery` (не master). Status IN_PROGRESS until merged.
