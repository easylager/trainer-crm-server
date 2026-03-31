---
description: "Task list — shared Mini App theme.css (001-mini-app-theme-css)"
---

# Tasks: Shared Mini App theme (theme.css)

**Input**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [contracts/theme-tokens.md](./contracts/theme-tokens.md)  
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: не требуются по спеке (ручной smoke в Telegram WebApp).

**Organization**: US1 = пилот + токены; US2 = миграция остальных страниц параллельно по файлам.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: разные файлы, нет зависимости между миграциями страниц (после T005).
- **[US1]** / **[US2]**: приоритеты из spec.md.

## Path Conventions

Все пути от корня репозитория: `static/webapp/`, `specs/001-mini-app-theme-css/`.

---

## Phase 1: Setup (shared `theme.css`)

**Purpose**: Единый источник `--app-*` и тёмной ветки.

- [x] T001 Create `static/webapp/theme.css` with required `--app-*` tokens from `specs/001-mini-app-theme-css/contracts/theme-tokens.md`, light defaults from `specs/001-mini-app-theme-css/data-model.md`, and `@media (prefers-color-scheme: dark)` (or equivalent) per `specs/001-mini-app-theme-css/research.md`; optional bridge from `var(--tg-theme-*)` where documented.

---

## Phase 2: Foundational

**Purpose**: Нет отдельного блокирующего кода кроме `theme.css` — этот phase пропущен (foundation = T001).

**Checkpoint**: После T001 можно начинать US1.

---

## Phase 3: User Story 1 — Единый внешний вид (пилот) (Priority: P1)

**Goal**: `theme.css` подключён на двух пилотных страницах; дубликаты `:root`/hex для тех же ролей убраны (SC-001).

**Independent Test**: Сравнить `catalog.html` и `book.html` в светлой/тёмной теме WebView; в DevTools нет расходящихся hex для фона/акцента/ошибки относительно токенов.

### Implementation for User Story 1

- [x] T002 [US1] Add `<link rel="stylesheet" href="theme.css" />` as first stylesheet in `<head>` before inline `<style>` in `static/webapp/catalog.html`.
- [x] T003 [US1] Refactor `static/webapp/catalog.html`: replace duplicate `:root` Telegram vars and repeated hex with `var(--app-*)` / existing classes wired to tokens; keep layout-only rules local.
- [x] T004 [US1] Add the same `theme.css` `<link>` in `static/webapp/book.html` and refactor inline styles to use `var(--app-*)` where they duplicate pilot patterns.
- [x] T005 [US1] Reconcile inline script(s) in `static/webapp/book.html` that set `--tg-theme-*` with `theme.css` (move defaults to `theme.css` or document exception in `specs/001-mini-app-theme-css/research.md`).

**Checkpoint**: Пилот готов к мержу; остальные HTML без изменений всё ещё работают как раньше.

---

## Phase 4: User Story 2 — Постепенная миграция остальных страниц (Priority: P2)

**Goal**: Все Mini App подключают `theme.css` и не вводят новые «сырые» hex для ролей из контракта.

**Independent Test**: Каждая мигрированная страница открывается в WebView; немигрированные (до завершения) не ломаются.

### Implementation for User Story 2 (parallel per file)

- [x] T006 [P] [US2] Migrate `static/webapp/schedule.html`: add `theme.css` link, replace tokenized colors with `var(--app-*)`, remove redundant `:root` duplicates.
- [x] T007 [P] [US2] Migrate `static/webapp/schedule-editor.html` (same pattern).
- [x] T008 [P] [US2] Migrate `static/webapp/client-requests.html` (same pattern).
- [x] T009 [P] [US2] Migrate `static/webapp/client-certificates.html` (same pattern).
- [x] T010 [P] [US2] Migrate `static/webapp/client-bookings.html` (same pattern).
- [x] T011 [P] [US2] Migrate `static/webapp/client-buy-pass.html` (same pattern).
- [x] T012 [P] [US2] Migrate `static/webapp/client-passes.html` (same pattern).
- [x] T013 [P] [US2] Migrate `static/webapp/trainer-bookings.html` (same pattern).
- [x] T014 [P] [US2] Migrate `static/webapp/trainer-clients.html` (same pattern).
- [x] T015 [P] [US2] Migrate `static/webapp/trainer-pay-subscription.html` (same pattern).
- [x] T016 [P] [US2] Migrate `static/webapp/trainer-pass-products.html` (same pattern).
- [x] T017 [P] [US2] Migrate `static/webapp/trainer-requests.html` (same pattern).
- [x] T018 [P] [US2] Migrate `static/webapp/trainer-stats.html` (same pattern).
- [x] T019 [P] [US2] Migrate `static/webapp/admin-dicts.html` (same pattern).
- [x] T020 [P] [US2] Migrate `static/webapp/admin-stats.html` (same pattern).

**Checkpoint**: Все 17 HTML используют общий `theme.css` и токены для семантических цветов.

---

## Phase 5: Polish & cross-cutting

- [x] T021 Run `rg '#[0-9a-fA-F]{3,8}' static/webapp/*.html` and eliminate or justify remaining hex on migrated pages; document justified exceptions in `specs/001-mini-app-theme-css/research.md`. *(Частично: hex в legacy-блоках `!important` и IIFE остаются — см. research §6 «Техдолг».)*
- [x] T022 [P] Verify `specs/001-mini-app-theme-css/contracts/theme-tokens.md` matches final names in `static/webapp/theme.css`; update contract if any token was added during migration.
- [x] T023 [P] Manual smoke: open pilot + two migrated pages in Telegram WebApp (light/dark) per `specs/001-mini-app-theme-css/quickstart.md`.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (T001)** → blocks US1 implementation.
- **Phase 3 (T002–T005)** → depends on T001; sequential recommended for pilot (same patterns inform later tasks).
- **Phase 4 (T006–T020)** → depends on T001; **depends on T002–T005** only as reference (можно параллелить после пилота, если команда согласована с паттерном).
- **Phase 5** → after all desired migrations complete.

### User story order

- **US1 (P1)** must complete before declaring MVP; **US2 (P2)** can follow in one batch or multiple PRs.

### Parallel opportunities

- **T006–T020**: different files — up to 15 parallel workers after pilot patterns are stable.
- **T022–T023**: parallel after migrations.

---

## Parallel example (User Story 2)

```bash
# After T005, assign different HTML files to different contributors:
Task T006 → schedule.html
Task T007 → schedule-editor.html
# …through T020
```

---

## Implementation strategy

### MVP (минимальный инкремент)

1. T001 → T002–T005 (пилот `catalog.html` + `book.html`).
2. Stop, merge, manual smoke — **SC-001** satisfied.

### Full delivery

1. Complete T006–T020 in one or more PRs.
2. T021–T023 cleanup and verification.

---

## Notes

- Не удалять поведение `Telegram.WebApp` — только централизовать внешний вид.
- Новые hex **MUST** go through `theme.css` per constitution § VIII.

**Total tasks**: 23 (T001–T023)  
**US1**: 5 tasks (T002–T005 + foundation T001 scoped to US1 entry) — *T001 is setup; story work T002–T005 = 4 tasks*  
**US2**: 15 tasks (T006–T020)  
**Polish**: 3 tasks (T021–T023)
