---
task_id: TASK-051
title: Публичный read-only API арен и сеансов льда
status: MERGED
phase: done
epic: EPIC3
depends_on: [TASK-048, TASK-050]
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-06
pr_url: https://github.com/easylager/trainer-crm-server/pull/26
---

# Task

## Objective

Дать клиентскому приложению один набор read-only эндпоинтов, покрывающий все экраны прототипа: список арен под таб «Лёд» (с «живой строкой» под выбранное намерение и уровнем A/B/C), карточку арены, ленту сеансов и список тренеров на арене.

## Business Context

Все клиентские задачи эпика (TASK-052…055) зависят от этого контракта. Он же фиксирует сквозное правило уровней арен: уровень **вычисляется на чтении** (есть непросроченные сеансы → A; есть контакты/фото/часы → B; только адрес → C), отдельной колонки нет, чтобы она не рассинхронизировалась.

## Scope

### In Scope
- `GET /api/public/ice/arenas` — список для таба «Лёд»: параметры `city_id` **или** `bbox`, `near` (lat/lon) с сортировкой по расстоянию, `intent` (`skate|coach|group`), `limit/cursor`. В ответе на каждую арену: имя, район, расстояние, `tier` (A/B/C), thumb-фото, и **одна** «живая строка» под выбранное намерение — ближайший сеанс с ценой, либо число тренеров и свободных слотов, либо число групп с набором.
- `GET /api/public/arenas/{id_or_slug}` — карточка: профиль, часы, сезон, amenities, контакты, hero+галерея, свежесть данных и источник, `tier`.
- `GET /api/public/arenas/{id}/sessions?from=&to=` — лента сеансов **в каноне TASK-050** (взр/дет/прокат, kind, локальная дата); сгруппированная по локальной дате арены; просроченные (по `valid_until`) не отдаются как актуальные. **Нет** поля `parser_key` / сырого HTML виджета — клиент не ветвится по арене.
- `GET /api/public/arenas/{id}/trainers` — тренеры арены с `can_book` (для честной кнопки «Записаться» / «Написать») и группами с набором.
- `GET /api/public/search?q=` — один поиск, три типа результатов: арена, тренер, город (Postgres `tsvector` + `pg_trgm`, без внешнего поискового движка).
- Снять молчаливое обрезание фильтра арен до 32 (`src/api/routes/public.py:185`, комментарий «cities have well under 32 arenas» больше не верен): либо поднять лимит с проверкой плана запроса, либо честно сообщать в ответе, что выбор урезан.
- Ранжирование списка: `tier` → расстояние → наличие сеансов в ближайшие 48 часов → полнота карточки.

### Out of Scope
- Клиентский UI — TASK-052/053/054/055.
- Запись и любые изменяющие операции — контур записи не трогаем.
- Публичные HTML-страницы для поисковиков — вне эпика (но `slug` в путях принимается уже сейчас, чтобы потом не менять URL).

## Acceptance Criteria

### AC-001
Список арен отдаётся по `city_id`, по `bbox` и по `near` с сортировкой по расстоянию; арена без координат не исчезает из списка (только из карты).
Requirement: CONFIRMED
Verification method: automated/integration (три режима + арена без координат присутствует в списке)

### AC-002
Уровень A/B/C вычисляется на чтении по фактическому наличию непросроченных сеансов и заполненности профиля; отдельной хранимой колонки нет.
Requirement: CONFIRMED
Verification method: automated/integration (арена с сеансами → A; убрать сеансы → B без записи в БД) + static analysis (нет колонки `data_tier`)

### AC-003
«Живая строка» меняется вместе с `intent` для одного и того же набора арен — порядок и текст зависят от намерения, состав арен принципиально нет.
Requirement: CONFIRMED
Verification method: automated/integration (три вызова с разными `intent` → одинаковый набор id, разные строки и порядок)

### AC-004
Просроченные по `valid_until` сеансы не отдаются как актуальные ни в списке, ни в ленте — лучше «мы не знаем», чем неверное расписание.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-005
Фильтр каталога больше не обрезает выбор арен молча: либо принимает больше 32, либо возвращает явный признак усечения.
Requirement: CONFIRMED
Verification method: automated/integration (выбор 40 арен → все применены или ответ содержит признак усечения)

### AC-006
Ответ карточки содержит свежесть и источник данных в виде, пригодном для строки «Расписание обновлено 2 дня назад · по данным сайта катка».
Requirement: CONFIRMED
Verification method: automated/integration (поля присутствуют; при отсутствии источника — честное отсутствие, а не выдуманная дата)

### AC-007
Список из 60 арен города отдаётся одним запросом без N+1 по тренерам/сеансам.
Requirement: INFERRED (порог производительности не задавался владельцем продукта; необходимость избежать N+1 следует из известной проблемы каталога — `PRODUCT-ARCHITECTURE-2026.md` §12)
Verification method: automated/integration (счётчик SQL-запросов на запрос списка) + ручной замер плана

## Edge Cases

### EDGE-001
`bbox` покрывает несколько городов (пограничная зона, зум на область) — валюта и таймзона у арен могут различаться; ответ обязан нести валюту рядом с каждой ценой, а не одну на список.
Severity: MEDIUM
Status: OPEN

### EDGE-002
Поиск по строке, совпадающей и с ареной, и с тренером («Замок») — порядок групп результатов должен быть предсказуем.
Severity: LOW
Status: OPEN

### EDGE-003
Арена уровня C у самого пользователя (100 м) и арена уровня A в 8 км — что выше в выдаче. Правило: `tier` важнее расстояния, но C рядом должна оставаться видимой в списке.
Severity: MEDIUM
Status: OPEN

## Technical Notes
- Новый модуль, не `webapp.py`: например `src/api/routes/public_arenas.py` + `src/application/arena_public_use_cases.py` (`PRODUCT-ARCHITECTURE-2026.md` F8).
- Индексы: `(city_id, is_active)` на аренах, гео-индекс под bbox/near, `(arena_id, starts_at_utc)` на сеансах.
- `can_book` берётся из существующего `get_trainer_booking_availability` — не изобретать второй источник правды.

## Tests
- integration: три режима списка, арена без координат (AC-001)
- integration: вычисление tier без хранимой колонки (AC-002)
- integration: intent меняет строку и порядок, не состав (AC-003)
- integration: просроченные сеансы не отдаются (AC-004)
- integration: >32 арен в фильтре (AC-005)
- integration: счётчик запросов на список из 60 арен (AC-007)

## Risks
- Соблазн добавить это в `webapp.py` — не делать; файл уже 419 KB и ~370 маршрутов.

## Execution History
- **TASK_CREATED** (2026-09-04) — EPIC3, волна 2
- **CANONICAL** (2026-09-05) — сеансы в API = ice_sessions, без формата источника
- **IN_PROGRESS** (2026-09-06) — public read-only Ice API on `feat/TASK-051-public-ice-api`. PR https://github.com/easylager/trainer-crm-server/pull/26 (base `release/ice-discovery`). **AC-003 deviation (owner rule):** `intent=skate` lists an arena only when it has a future non-expired `public_skate|open_ice` session. `intent=coach|group` may return a larger set (B/C profile venues). Live line still changes with intent. Tier A/B/C is computed on read; no `data_tier` column.
- **MERGED** (2026-09-06) — squash `be30612` into `release/ice-discovery`. CI green. Not merged to master.
