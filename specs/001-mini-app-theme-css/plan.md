# Implementation Plan: Shared Mini App theme (theme.css)

**Branch**: `001-mini-app-theme-css` | **Date**: 2026-03-23 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/001-mini-app-theme-css/spec.md`

**Note**: This plan follows `.specify/templates/plan-template.md` workflow.

## Summary

Вынести общие CSS custom properties и базовые компонентные стили в **`static/webapp/theme.css`**, ввести семантический слой **`--app-*`**, подключить файл во все Mini App и **поэтапно** убрать дублирующиеся `:root` и расходящиеся hex. Пилот: `catalog.html`, `book.html`; остальные страницы — по [research.md](./research.md). Соответствует конституции **§ VIII**.

## Technical Context

**Language/Version**: Статический HTML/CSS; существующий vanilla JS в страницах без изменения сборки.  
**Primary Dependencies**: N/A (нет CSS-фреймворка).  
**Storage**: N/A.  
**Testing**: Ручной smoke в Telegram WebApp; опционально позже — grep/CI на hex вне `theme.css`.  
**Target Platform**: Telegram WebView (iOS/Android/Desktop), светлая/тёмная тема.  
**Project Type**: Статические Mini App в `static/webapp/`.  
**Performance Goals**: Один дополнительный HTTP-запрос `theme.css` (кэшируемый); без роста критичного пути JS.  
**Constraints**: Не ломать немигрированные страницы; сохранить совместимость с `Telegram.WebApp` theme params где уже используется.  
**Scale/Scope**: ~15 HTML-файлов в `static/webapp/`; миграция итерациями.

## Constitution Check

*GATE: Passed for this feature — правки только в `static/webapp/` и документация спека; домен и API не меняются.*

Сверка с [.specify/memory/constitution.md](../../.specify/memory/constitution.md) (**Trainer CRM Belarus**):

- [x] **I — Архитектура**: логика приложения не затрагивается; только статика.
- [x] **II — DDD**: не применимо к CSS; без новых доменных сущностей.
- [x] **III — Тесты**: доменные инварианты не меняются; визуал — ручная проверка (зафиксировано в research).
- [x] **IV — Безопасность**: без секретов в CSS.
- [x] **V — UX**: единый визуальный язык Mini App усиливает согласованность с § VIII.
- [x] **VI — Производительность**: один маленький CSS-файл; без тяжёлых запросов.
- [x] **VII — Боты**: не затронуто.
- [x] **VIII — Mini App**: цель фичи — выполнить токены и единообразие.

## Project Structure

### Documentation (this feature)

```text
specs/001-mini-app-theme-css/
├── plan.md              # This file
├── spec.md
├── research.md
├── data-model.md        # Token inventory (no DB)
├── quickstart.md
└── contracts/
    └── theme-tokens.md
```

### Source Code (repository root)

```text
static/webapp/
├── theme.css            # NEW: :root --app-* + dark branch + shared utility classes (optional)
├── catalog.html         # Pilot
├── book.html            # Pilot
├── schedule.html
├── schedule-editor.html
├── client-*.html
├── trainer-*.html
├── admin-*.html
└── ...
```

**Structure Decision**: Один общий `theme.css` в корне `static/webapp/`; все страницы в той же директории — относительный `href="theme.css"`.

## Phases (execution)

### Phase 0 — Research ✅

Выход: [research.md](./research.md) (файл стилей, `--app-*`, тёмная тема, миграция).

### Phase 1 — Design & contracts ✅

- [data-model.md](./data-model.md) — инвентарь токенов.
- [contracts/theme-tokens.md](./contracts/theme-tokens.md) — контракт имён переменных.
- [quickstart.md](./quickstart.md) — как мигрировать страницу.

### Phase 2 — Tasks (не создаётся этой командой)

Следующий шаг: `/speckit.tasks` → `tasks.md` с разбиением по файлам и чекпоинтами пилота.

## Complexity Tracking

Нарушений конституции, требующих оправдания, нет.
