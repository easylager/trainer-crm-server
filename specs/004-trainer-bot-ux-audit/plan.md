# Implementation Plan: Аудит и улучшение UX тренерского бота

**Branch**: `004-trainer-bot-ux-audit` | **Date**: 2026-03-24 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/004-trainer-bot-ux-audit/spec.md`

## Summary

Провести **аудит UX тренерского Telegram-бота** (команды меню, сценарии расписания, заявок, записей, клиентов, абонементов, подписки, статистики) и **связанных Mini App** (`static/webapp/trainer-*.html`, открываемых из бота), зафиксировать находки в артефактах фичи ([data-model.md](./data-model.md), при необходимости отдельная таблица в PR), согласовать **приоритетный бэклог** исправлений и устранить проблемы по **FR-001–FR-005** и success criteria спеки. Доменные правила бронирований/оплат **не меняются**, кроме случаев, когда без этого нельзя устранить блокирующий UX (тогда — явная отметка в отчёте).

## Technical Context

**Language/Version**: Python 3.x (aiogram 3.x), статический HTML/CSS/JS в Mini App  
**Primary Dependencies**: aiogram; use case’ы из `src/application/` через хендлеры; `ParseMode.HTML` в [trainer_app.py](../../src/bot/trainer_app.py)  
**Storage**: PostgreSQL через существующие use case’ы; новых сущностей БД для аудита нет (артефакты — markdown в `specs/004-*`)  
**Testing**: pytest — при изменении поведения с инвариантами; для чисто текстовых/клавиатурных правок — регрессионный сценарий или ручной прогон по [contracts/trainer-ux-checklist.md](./contracts/trainer-ux-checklist.md)  
**Target Platform**: Telegram (клиенты iOS/Android/Desktop), WebView Mini App  
**Project Type**: монолит — `src/bot/trainer_app.py`, [handlers/trainer_handlers.py](../../src/bot/handlers/trainer_handlers.py), [messages.py](../../src/bot/messages.py), `static/webapp/trainer-*.html`  
**Performance Goals**: без лишних round-trip; при добавлении `send_chat_action` / промежуточных сообщений — без заметного удлинения критичного пути (сверка SC-004 спеки)  
**Constraints**: секреты только из env; не ломать вход по `start=link_<token>` и существующие callback-префиксы без миграции в спеке  
**Scale/Scope**: один тренерский бот; крупный `trainer_handlers.py` (~1.9k+ строк) — UX-фиксы в первую очередь; выделение подроутеров **вне скоупа** этой спеки, если не требуется для читаемости правок

## Constitution Check

*GATE: пройден до Phase 0; перепроверить после списка исправлений.*

Сверка с [.specify/memory/constitution.md](../../.specify/memory/constitution.md):

- [x] **I — Архитектура**: изменения в `src/bot/` и при необходимости `static/webapp/`; бизнес-логика остаётся в `src/application/`; хендлеры только оркестрация.
- [x] **II — DDD**: термины спеки и сообщений = доменные («тренер», «слот», «заявка»).
- [x] **III — Тесты**: при фиксе бага — тест на регрессию; иначе чеклист + ручной smoke.
- [x] **IV — Безопасность**: в артефактах аудита не публиковать PII и секреты.
- [x] **V — UX**: цель фичи; согласованность с клиентским ботом по § VII где затрагиваются общие состояния.
- [x] **VI — Производительность**: списки с пагинацией не раздувать; тяжёлые отчёты не в фокусе UX-фичи.
- [x] **VII — Telegram-боты**: основная зона.
- [x] **VIII — Mini App**: страницы `trainer-*.html` при затрагивании визуала/пустых состояний.

## Project Structure

### Documentation (this feature)

```text
specs/004-trainer-bot-ux-audit/
├── plan.md
├── research.md
├── data-model.md
├── audit-findings.md       # живой журнал аудита и бэклога (FR-001, FR-002)
├── quickstart.md
├── contracts/
│   └── trainer-ux-checklist.md
└── tasks.md                # /speckit.tasks
```

### Source Code (repository root)

```text
src/bot/
├── trainer_app.py              # точка входа, команды меню, ParseMode
├── messages.py                 # общие строки; сверка с клиентским ботом для общих состояний
└── handlers/
    └── trainer_handlers.py     # основной объём сценариев тренера

static/webapp/
├── theme.css
├── trainer-bookings.html
├── trainer-clients.html
├── trainer-pass-products.html
├── trainer-pay-subscription.html
├── trainer-requests.html
└── trainer-stats.html
```

**Structure Decision**: правки копирайта, клавиатур и разметки — в `messages.py` и `trainer_handlers.py`; стили Mini App — через `theme.css` и § VIII; новые общие формулировки по возможности централизовать в `messages.py`.

## Phases (execution)

### Phase 0 — Research

Выход: [research.md](./research.md) — метод аудита, решения по метрикам (SC-001, SC-004), известные риски (длинный файл хендлеров, Web App callbacks, устаревшие inline-кнопки).

### Phase 1 — Design & contracts

- [data-model.md](./data-model.md) — сущности находок и сценариев (без БД).
- [contracts/trainer-ux-checklist.md](./contracts/trainer-ux-checklist.md) — ручная приёмка § VII / § VIII для тренерского бота и страниц.
- [quickstart.md](./quickstart.md) — как запускать бота, проходить сценарии, фиксировать находки.

### Phase 2 — Tasks

Следующий шаг: `/speckit.tasks` → `tasks.md`.

## Complexity Tracking

Нарушений конституции, требующих отдельного обоснования, не запланировано.
