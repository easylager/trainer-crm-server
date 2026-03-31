---
description: "Task list — клиентский бот + Mini App UX (002-mini-app-client-refactor)"
---

# Tasks: Клиентский опыт — Mini App и Telegram-бот

**Input**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [contracts/client-ux-checklist.md](./contracts/client-ux-checklist.md)  
**Prerequisites**: plan.md, spec.md  
**Tests**: по [конституции § III](../../.specify/memory/constitution.md) — регрессия при изменении поведения; иначе ручной smoke + чеклист.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно параллелить (разные файлы, без общей зависимости в одной задаче).
- **[US1]** / **[US2]** / **[US3]**: user stories из spec.md.

Пути от корня репозитория.

---

## Phase 1: Аудит и артефакты (FR-001)

**Purpose**: Явный список находок до/рядом с кодом.

- [x] **T001** [US1] Создать [audit-findings.md](./audit-findings.md): таблица сценариев (каталог → запись, заявки, мои записи, справка, поддержка), колонки: finding id, severity (`blocker` / `major` / `minor`), шаги воспроизведения, ожидаемое поведение, статус (`open` / `fixed` / `deferred`). Без PII (FR-006).

---

## Phase 2: User Story 1 — Бот: пути, тексты, ожидание (P1)

**Goal**: FR-002, FR-003, FR-004 и сценарии US1; соответствие § VII.

**Independent Test**: ручной прогон по [contracts/client-ux-checklist.md](./contracts/client-ux-checklist.md) (раздел «Клиентский Telegram-бот»).

### Реализация и проверка

- [x] **T002** [US1] Зафиксировать в `audit-findings.md` уже внедрённое: отдельные строки `CLIENT_BOOK_SESSION_EXPIRED`, `CLIENT_BOOK_WEBAPP_FOOTER` в [src/bot/messages.py](../../src/bot/messages.py) и использование в [src/bot/handlers/client_handlers.py](../../src/bot/handlers/client_handlers.py) (ветка HTTPS + callback booking) — статус `fixed`, ссылка на коммит/PR.

- [x] **T003** [US1] Пройти сценарий **HTTPS + Mini App**: команда `/book` и callback `book` — тексты не противоречат друг другу и FR-004; при необходимости выровнять [src/bot/messages.py](../../src/bot/messages.py) (`CLIENT_MENU_BOOKING_MOVED`, `CLIENT_BOOK_CHOOSE_SLOT`, подписи к Web App).

- [x] **T004** [US1] Долгие операции бота: добавить `send_chat_action` (typing) минимум для загрузки каталога / списка слотов **или** зафиксировать в `audit-findings.md` осознанный отказ с ссылкой на § VII (ожидание ~1–2 с).

- [x] **T005** [US1] Пройти [src/bot/handlers/client_handlers.py](../../src/bot/handlers/client_handlers.py) на остаточные ответы с `CLIENT_BOOK_NO_TRAINER` там, где по смыслу нужна «сессия устарела» vs «нет тренера»; правки в [src/bot/messages.py](../../src/bot/messages.py) при необходимости.

- [x] **T006** [P] [US1] Edge: нет слотов / пустой каталог — сообщения ведут к альтернативе (другой тренер, заявка, позже); при расхождении со spec — правка текстов в `messages.py`.

- [x] **T007** [US1] SC-002: отметить в `audit-findings.md` или чеклисте, что ≥90% затронутых пользовательских строк в зоне изменений проверены на § VII (таблица/список файлов).

---

## Phase 3: User Story 2 — Mini App клиента (P2)

**Goal**: SC-003 — минимум **две** клиентские страницы согласованы с `theme.css` / § VIII.

**Independent Test**: визуальное сравнение в WebView (светлая/тёмная) + отсутствие новых «случайных» hex для ролей из [specs/001-mini-app-theme-css/contracts/theme-tokens.md](../001-mini-app-theme-css/contracts/theme-tokens.md).

### Пилот (обязательный минимум)

- [x] **T008** [US2] Проверить и при необходимости выровнять [static/webapp/client-bookings.html](../../static/webapp/client-bookings.html) под токены § VIII (подключение `theme.css`, `var(--app-*)`).

- [x] **T009** [P] [US2] То же для [static/webapp/client-requests.html](../../static/webapp/client-requests.html).

### Дополнительно (параллельно после T008–T009)

- [ ] **T010** [P] [US2] [static/webapp/client-passes.html](../../static/webapp/client-passes.html) — только при необходимости по аудиту или для расширения SC-003.

- [ ] **T011** [P] [US2] [static/webapp/client-certificates.html](../../static/webapp/client-certificates.html) — аналогично.

- [ ] **T012** [US2] [static/webapp/client-buy-pass.html](../../static/webapp/client-buy-pass.html) — по остаточному бэклогу или отложить с пометкой в `audit-findings.md`.

---

## Phase 4: User Story 3 — Поддерживаемость (P3)

**Goal**: US3 — без массового рефакторинга в этой итерации.

- [x] **T013** [US3] Добавить в `audit-findings.md` раздел **Backlog**: дубли строк в [src/bot/messages.py](../../src/bot/messages.py), кандидаты на вынос; опционально — разбиение `client_handlers.py` на подроутеры (отдельная фича/PR).

---

## Phase 5: Закрытие и метрики

- [x] **T014** Заполнить [contracts/client-ux-checklist.md](./contracts/client-ux-checklist.md) целиком для релиза; краткий итог в `audit-findings.md` или описание PR.

- [x] **T015** SC-004: зафиксировать способ качественной оценки (ревью 2 человек / короткий опрос / отложено) в `audit-findings.md` или [research.md](./research.md).

- [x] **T016** Прогнать релевантные тесты: `pytest` (если менялось поведение с инвариантами); иначе зафиксировать ручной smoke Telegram + WebView в PR.

---

## Dependencies & order

| Зависимость | Пояснение |
|-------------|-------------|
| T001 → T002–T007 | Сначала артефакт аудита; можно частично заполнять по мере фиксов. |
| T008–T009 | Можно параллелить [P] после завершения пилотного просмотра токенов. |
| T014–T016 | После выполнения основных задач US1–US2. |

---

## Parallel example

```text
T009 (client-requests) || T010 (client-passes)   # после T008 пилотного паттерна
```

---

## Implementation notes

- Не менять доменную логику в `src/application/` без отдельного согласования.
- Тренерский/админский боты вне скоупа, кроме общих констант в `messages.py` — сверить термины.

**Total tasks**: T001–T016  
**US1**: T001–T007  
**US2**: T008–T012  
**US3**: T013  
**Closure**: T014–T016
