---
description: "Task list — детализация образования тренера с модерацией полного профиля (003-trainer-education-details)"
---

# Tasks: Детализация образования тренера с модерацией полного профиля

**Input**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/trainer-education-moderation.md](./contracts/trainer-education-moderation.md), [quickstart.md](./quickstart.md)  
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: По конституции п. III — pytest обязателен для изменений в уведомлениях/модерации/контрактах; минимум integration + негативный сценарий отклонения.

**Organization**: задачи сгруппированы по user stories (US1–US3). Сначала foundation (схема БД, базовые use case’ы, профильный moderation flow), затем UX/API и верификация.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно выполнять параллельно (разные файлы и слои без конфликта зависимостей).
- **[US1]** / **[US2]** / **[US3]**: привязка к user story спеки; без тега — инфраструктурная задача.

## Path Conventions

Корень репозитория: `src/`, `alembic/versions/`, `tests/`, `specs/003-trainer-education-details/`.

---

## Phase 1: Setup — подготовка артефактов и миграции

**Purpose**: создать базу для реализации FR-001..FR-004 и FR-012.

- [X] T001 Создать Alembic-миграцию для таблицы `trainer_education` (поля, enum-статусы, индексы, FK, `supersedes_id`) в `alembic/versions/`.
- [X] T002 Создать Alembic-миграцию для `trainer_education_moderation_events` с FK и ограничениями reason/decision в `alembic/versions/`.
- [X] T003 [P] Подготовить enum/константы статусов и типов образования в доменном слое (`src/application/` и/или `src/api/schemas.py`) без магических строк.

**Checkpoint**: schema готова; миграции применяются локально без ошибок.

---

## Phase 2: Foundational — доменная логика и репозитории

**Purpose**: реализовать FR-001..FR-013 до UI/API.

- [X] T004 Реализовать репозиторные операции CRUD + list для образования тренера в `src/infrastructure/repositories/trainer_repository.py` (с учетом лимита до 20 записей).
- [X] T005 Реализовать доменные use case’ы в `src/application/trainer_use_cases.py`: create/edit/list education, валидации обязательных/optional полей, state transitions.
- [X] T006 Реализовать механизм pending revision при редактировании approved записи (`supersedes_id`, сохранение approved snapshot).
- [X] T007 Реализовать применение moderation decision для education в рамках общего профильного потока (без отдельной карточки education) в `src/application/trainer_use_cases.py`.
- [X] T008 Добавить аудит/журнал событий модерации (`trainer_education_moderation_events`) с атомарным обновлением статусов.

**Checkpoint**: domain/repository готовы и покрывают full-profile moderation integration rule.

---

## Phase 3: User Story 1 — Тренер добавляет образование без перегруза (P1)

**Goal**: минимальный ввод (3 обязательных поля), сохранение и статус `pending_moderation`.

**Independent Test**: тренер создаёт запись с 3 полями и видит её в профиле со статусом модерации.

- [X] T009 [US1] Добавить/обновить API schema для `POST/PATCH/GET /api/trainers/{trainer_id}/education` в `src/api/schemas.py`.
- [X] T010 [US1] Реализовать API endpoints образования тренера в `src/api/routes/trainers.py` (валидация, коды ответов, формат контрактов).
- [ ] T011 [US1] Добавить bot-flow ввода образования в `src/bot/handlers/trainer_handlers.py` с 3 обязательными шагами и optional "Пропустить".
- [X] T012 [US1] Централизовать тексты статусов/ошибок образования в `src/bot/messages.py` (русский, единый тон, без тех. деталей).

**Checkpoint**: US1 работает end-to-end для тренера.

---

## Phase 4: User Story 2 — Админ модерирует через полный профиль (P2)

**Goal**: решение по education принимается в единой карточке полного профиля, не фрагментарно.

**Independent Test**: админ видит полный профиль в карточке модерации, approve/reject обновляет education-статусы и уведомляет тренера.

- [X] T013 [US2] Изменить/дополнить админский moderation flow в `src/bot/handlers/admin_handlers.py` (или соответствующем модуле) для передачи education в full profile payload.
- [X] T014 [US2] Добавить обработку `affected_sections=["education"]` в API/домене профильной модерации (`src/api/routes/trainers.py`, `src/application/trainer_use_cases.py`).
- [X] T015 [US2] Реализовать уведомления тренеру о результате модерации в `src/bot/handlers/trainer_handlers.py` + `src/bot/messages.py`.
- [X] T016 [US2] Гарантировать, что образование не отправляется отдельной модерационной карточкой (удалить/запретить отдельный trigger, если существует).

**Checkpoint**: US2 закрыт, модерация идёт только через единый профильный канал.

---

## Phase 5: User Story 3 — Free-text + опциональный справочник (P3)

**Goal**: запуск MVP без тяжёлых справочников, с возможностью расширения.

**Independent Test**: тренер добавляет вручную вуз/курс; система сохраняет и отправляет в общий moderation flow.

- [X] T017 [US3] Добавить нормализацию и ограничения free-text полей (`institution_name`, `program_or_title`) в application layer.
- [ ] T018 [US3] Добавить в API опциональный endpoint/флаг для подсказок справочника (stub/no-op допустим), не влияющий на основной create flow.
- [X] T019 [US3] Обновить клиентское отображение профиля тренера (API публичного чтения или webapp путь) так, чтобы показывать только `approved` записи.

**Checkpoint**: US3 закрыт, без блокирующей зависимости от каталога учреждений.

---

## Phase 6: Polish & Verification

**Purpose**: закрыть success criteria и конституцию.

- [X] T020 [P] Добавить/обновить integration tests для API education (`tests/api/`): create, edit approved->revision, public approved-only.
- [X] T021 [P] Добавить tests для модерации (`tests/application/` или `tests/bot/`): approve/reject, reason required, event logging.
- [ ] T022 [P] Добавить regression test: education change попадает только в full profile moderation payload (без отдельной карточки).
- [ ] T023 Прогнать quickstart сценарии A-E и зафиксировать результаты в `specs/003-trainer-education-details/quickstart.md` или заметках фичи.
- [ ] T024 Проверить соответствие § VII/§ VIII конституции и обновить артефакты при необходимости.

---

## Dependencies & Execution Order

| Phase | Depends On | Blocks |
|-------|------------|--------|
| Phase 1 | — | все последующие |
| Phase 2 | T001-T003 | US1-US3 |
| Phase 3 (US1) | Phase 2 | Phase 4/5 partially |
| Phase 4 (US2) | T007, T010-T012 | релиз moderation |
| Phase 5 (US3) | Phase 3 | финальная приемка |
| Phase 6 | US1-US3 | релиз |

**Parallel examples**:
- T003 можно параллельно с T001/T002.
- T020/T021/T022 можно частично параллелить после готовности соответствующих слоев.

---

## Implementation Strategy

1. Завершить миграции и доменную логику (Phase 1-2).
2. Реализовать US1 (ввод/CRUD) и убедиться, что pending flow стабилен.
3. Реализовать US2 с ключевым ограничением: только full profile moderation payload.
4. Добавить US3 и завершить тестами/верификацией.

---

## Notes

- Любые сложные компромиссы в логике синхронизации `affected_sections` помечать коротким inline-комментарием на английском (конституция § I).
- Не добавлять PII в логи и артефакты спеки.
- Сохранять обратную совместимость текущего профиля тренера при включении education блока.
