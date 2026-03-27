---
description: "Task list — аудит и улучшение UX тренерского бота (004-trainer-bot-ux-audit)"
---

# Tasks: Аудит и улучшение UX тренерского бота

**Input**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/trainer-ux-checklist.md](./contracts/trainer-ux-checklist.md)  
**Prerequisites**: plan.md, spec.md

**Tests**: по [конституции п. III](../../.specify/memory/constitution.md) — регрессионные тесты при изменении поведения или исправлении бага; иначе ручной прогон чеклиста.

**Organization**: задачи сгруппированы по user story спеки (US1–US3). Сначала артефакт аудита и бэклог (блокируют код).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно параллельно (разные зоны файлов / Mini App после фикса бота).
- **[US1]** / **[US2]** / **[US3]**: соответствие спеке; без тега — общая инфраструктура аудита.

## Path Conventions

Корень репозитория: `src/bot/`, `static/webapp/trainer-*.html`, `specs/004-trainer-bot-ux-audit/`, `tests/`.

---

## Phase 1: Setup — артефакт аудита

**Purpose**: шаблон для FR-001 (документированные сценарии и находки).

- [x] T001 Создать `specs/004-trainer-bot-ux-audit/audit-findings.md`: таблицы **TrainerScenario** (список сценариев с `id` и шагами), **AuditFinding** (F-xxx, severity, constitution, repro, expected_ux, status), **BacklogItem** (порядок внедрения) по полям [data-model.md](./data-model.md); без PII.

---

## Phase 2: Foundational — аудит и бэклог (блокирует реализацию)

**Purpose**: FR-001, FR-002; до закрытия этой фазы не мержить UX-правки без явного согласования.

- [x] T002 Пройти [quickstart.md](./quickstart.md): не менее **5** сценариев тренера; зафиксировать находки в `audit-findings.md` (все `severity` ≥ `minor` по продуктовому решению).
- [x] T003 Пройти [contracts/trainer-ux-checklist.md](./contracts/trainer-ux-checklist.md); занести ✓/✗ и заметки в `audit-findings.md` или ссылку на раздел «Чеклист».
- [x] T004 Упорядочить **BacklogItem** в `audit-findings.md`: все `blocker`/`major` имеют `order` и привязку к сценарию (FR-002).

**Checkpoint**: бэклог согласован; можно начинать US1–US3 по приоритету `order`.

---

## Phase 3: User Story 1 — Ключевые пути без тупиков (Priority: P1)

**Goal**: нет блокирующих неясностей в навигации; отмена/назад; обратная связь при ожидании (спека US1, SC-001).

**Independent Test**: прогон P1-сценариев из `audit-findings.md` без тупиков; замер SC-004 для двух выбранных сценариев до/после (зафиксировать в `audit-findings.md` или заметках релиза).

### Implementation — по бэклогу (ссылка на `finding_id`)

- [x] T005 [US1] Исправить находки бэклога, затрагивающие **вход по ссылке, `/start`, `guide`**, клавиатуры помощи — `src/bot/handlers/trainer_handlers.py`, при необходимости `src/bot/messages.py`.
- [x] T006 [US1] Исправить находки по **расписанию / `editor` / слоты / создание записи из расписания** (callbacks `schedule:*`, `slot:*`, создание букинга) — `trainer_handlers.py`, `messages.py`.
- [x] T007 [US1] Исправить находки по **«Мои записи»** (список, пагинация, деталь, подтверждение/отмена/отказ/отзыв/recurring) — `trainer_handlers.py`, `messages.py`.
- [x] T008 [US1] Исправить находки по **заявкам клиентов** (список, деталь, ответ, комментарии в state) — `trainer_handlers.py`, `messages.py`.
- [x] T009 [US1] Исправить находки по **`clients`, `passes`, `subscription`, `stats`** и связанным Web App кнопкам — `trainer_handlers.py`, `messages.py`; при затрагивании веба — соответствующие `static/webapp/trainer-*.html`.
- [x] T010 [US1] Добавить или выровнять **индикацию ожидания** (`send_chat_action` typing и/или короткий статус) для операций дольше порога из § VII там, где бэклог/аудит указали пробел — `trainer_handlers.py`.

**Checkpoint**: все P1-находки из бэклога со статусом `fixed` или `deferred` с обоснованием; US1 приёмка по спеке.

---

## Phase 4: User Story 2 — Язык и обратная связь (Priority: P2)

**Goal**: понятные ошибки, пустые состояния, успехи; согласованность с клиентским ботом для тех же сущностей (спека US2, SC-003).

**Independent Test**: не менее **3** типов состояний (ошибка / пусто / успех) проверены сторонним ревьюером без глоссария.

- [x] T011 [US2] Выровнять **сообщения об ошибках и отказе в доступе** с бэклогом P2 и при необходимости с клиентским ботом — `messages.py`, точечно `trainer_handlers.py`.
- [x] T012 [US2] Выровнять **пустые состояния** (нет заявок, нет слотов, нет записей и т.д.) и **краткие подтверждения успеха** — `messages.py`, `trainer_handlers.py`.
- [x] T013 [P] [US2] Если аудит указал расхождения на **Mini App**: пустые/ошибочные состояния на затронутых `static/webapp/trainer-*.html` (токены § VIII). *(в этой итерации правок HTML нет)*

**Checkpoint**: US2 закрыт по `audit-findings.md` для приоритета P2 в рамках спринта фичи.

---

## Phase 5: User Story 3 — Кнопки и структура сообщений (Priority: P3)

**Goal**: порядок кнопок, подписи назад/отмена, структура длинных сообщений, эмодзи по § VII (спека US3).

- [x] T014 [US3] Привести **inline/reply-клавиатуры** к правилам § VII (ряды, основное действие, отмена, деструктивные действия) по бэклогу P3 — `trainer_handlers.py`.
- [x] T015 [US3] Структурировать **длинные ответы** (заголовки, списки, шаги) и согласовать **эмодзи** (общий набор или отсутствие) — `trainer_handlers.py`, `messages.py`.

**Checkpoint**: US3 закрыт; чеклист § VII для бота без ✗ по критичным пунктам.

---

## Phase 6: Polish & приёмка

**Purpose**: кросс-срез спеки и конституции; метрики SC.

- [x] T016 [P] Обновить статусы находок в `audit-findings.md` (`fixed` / `wontfix` / `deferred`); для `deferred` — причина (FR-002/SC-002).
- [x] T017 Повторный полный прогон [contracts/trainer-ux-checklist.md](./contracts/trainer-ux-checklist.md); все пункты ✓ или задокументированы исключения.
- [x] T018 Зафиксировать **SC-001** (≥5 сценариев, ≥90% без блокеров) и **SC-004** (два сценария, до/после) в `audit-findings.md` или `research.md`.
- [x] T019 [P] Добавить или обновить **pytest**-тесты под изменённое поведение — `tests/` (конституция III).
- [x] T020 [P] Сверка с [.specify/memory/constitution.md](../../.specify/memory/constitution.md) § VII; при правках Mini App — § VIII.

---

## Dependencies & Execution Order

| Phase | Зависит от | Блокирует |
|-------|------------|-----------|
| 1 | — | T002+ |
| 2 | T001 | T005+ |
| 3 (US1) | T004 | US2/US3 при конфликте с теми же строками — обычно US1 первым |
| 4 (US2) | Точки бэклога P2 | — |
| 5 (US3) | Бэклог P3 | — |
| 6 | US1–US3 по объёму фичи | релиз |

**Параллельно**: T013 с T011/T012 при разных файлах; T019/T020 с T016–T018 при готовности кода.

---

## Implementation Strategy

1. Завершить Phase 1–2 (аудит + бэклог).
2. Закрыть US1 (T005–T010), остановиться на checkpoint — прогон P1.
3. US2 → US3 → Polish.
4. Остановка для демо после US1 возможна при договорённости (MVP = только P1 из бэклога).

---

## Notes

- Конкретные правки кода всегда ссылаются на строки **finding_id** в `audit-findings.md`, чтобы не плодить расхождения со спекой.
- Не добавлять PII в `audit-findings.md` и PR-описания.
- При редактировании общих констант в `messages.py` проверить влияние на `client_handlers.py` / клиентский бот (grep по символам).
