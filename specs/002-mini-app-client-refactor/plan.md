# Implementation Plan: Клиентский опыт — Mini App и Telegram-бот (UX + рефакторинг)

**Branch**: `002-mini-app-client-refactor` | **Date**: 2026-03-23 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/002-mini-app-client-refactor/spec.md`

## Summary

Провести **аудит UX и пользовательских путей** клиентского Telegram-бота (`src/bot/client_app.py`, `handlers/client_handlers.py`, `messages.py`) и **клиентских Mini App** (`static/webapp/client-*.html`, связка с Web App из бота), зафиксировать находки в артефактах фичи, устранить **блокирующие и сильные** проблемы (FR-002, FR-003, FR-004), выровнять **минимум две** клиентские HTML-страницы по § VIII (SC-003), при необходимости — точечный **рефакторинг** хендлеров без смены доменной логики. Метрика SC-004: **качественная** оценка до/после (чеклист ревью) + опционально учёт обращений в поддержку, если есть теги/процесс.

## Technical Context

**Language/Version**: Python 3.x (aiogram 3.x), статический HTML/CSS/JS в Mini App  
**Primary Dependencies**: aiogram, FastAPI (косвенно через API бота); `theme.css` для токенов § VIII  
**Storage**: PostgreSQL через существующие use case’ы; для фичи — без новых сущностей БД (аудит — артефакты markdown)  
**Testing**: pytest (регрессия бота/WebApp по конституции п. III — при изменении инвариантов); ручной smoke в Telegram  
**Target Platform**: Telegram клиенты (iOS/Android/Desktop), WebView Mini App  
**Project Type**: существующий монолит — адаптеры `src/bot/`, статика `static/webapp/`  
**Performance Goals**: без деградации: `send_chat_action` и ответы бота остаются в привычных пределах; Mini App — без роста критичного пути  
**Constraints**: секреты только из env; не ломать обратную совместимость публичных сценариев бота без миграции в спеке  
**Scale/Scope**: один клиентский бот; ~5 `client-*.html`; крупный `client_handlers.py` (~2.5k строк) — рефакторинг поэтапно

## Constitution Check

*GATE: Passed — фича усиливает § V, VII, VIII; домен не меняется без отдельного согласования.*

Сверка с [.specify/memory/constitution.md](../../.specify/memory/constitution.md):

- [x] **I — Архитектура**: изменения преимущественно в `src/bot/` и `static/webapp/`; новая бизнес-логика в application не требуется для UX-фиксов.
- [x] **II — DDD**: без новых агрегатов; термины спеки = доменные.
- [x] **III — Тесты**: регрессионные тесты при исправлении багов с воспроизведением; для чисто текстовых правок — минимум ручная проверка + чеклист.
- [x] **IV — Безопасность**: аудит без PII в артефактах (FR-006).
- [x] **V — UX**: цель фичи.
- [x] **VI — Производительность**: не фокус нагрузки; при добавлении typing — без лишних запросов к API.
- [x] **VII — Боты**: основная зона работы.
- [x] **VIII — Mini App**: вторая зона (клиентские страницы).

## Project Structure

### Documentation (this feature)

```text
specs/002-mini-app-client-refactor/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── client-ux-checklist.md
└── tasks.md             # /speckit.tasks
```

### Source Code (repository root)

```text
src/bot/
├── client_app.py
├── messages.py
└── handlers/
    └── client_handlers.py    # основной объём; возможное поэтапное разбиение роутеров

static/webapp/
├── theme.css
├── client-bookings.html
├── client-buy-pass.html
├── client-certificates.html
├── client-passes.html
├── client-requests.html
└── book.html / catalog.html   # стыковка с ботом при Web App
```

**Structure Decision**: правки копирайта и разметки — в `messages.py` и хендлерах; стили клиентских страниц — через существующие токены `theme.css`; новые общие строки — по возможности из одного места (`messages.py`).

## Phases (execution)

### Phase 0 — Research

Выход: [research.md](./research.md) — метод аудита, решения по SC-004, список сценариев и известных рисков (in-memory state, HTTPS vs inline booking).

### Phase 1 — Design & contracts

- [data-model.md](./data-model.md) — сущности «найдено», «сценарий», приоритет (без БД).
- [contracts/client-ux-checklist.md](./contracts/client-ux-checklist.md) — проверка § VII / § VIII для ручного прогона.
- [quickstart.md](./quickstart.md) — как проходить аудит и мержить правки.

### Phase 2 — Tasks

Следующий шаг: `/speckit.tasks` → `tasks.md`.

## Complexity Tracking

Нарушений конституции, требующих отдельного оправдания, нет.
