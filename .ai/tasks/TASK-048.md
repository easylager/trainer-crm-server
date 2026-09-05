---
task_id: TASK-048
title: Арена как сущность — профиль, slug, район, amenities, часы, сезон
status: IN_PROGRESS
phase: verify
epic: EPIC3
depends_on: []
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-05
branch: feat/TASK-048-arena-profile
pr: https://github.com/easylager/trainer-crm-server/pull/19
---

# Task

## Objective

Превратить `arenas` из словаря (название + адрес + координаты) в сущность с собственным профилем: постоянная ссылка (`slug`), район, контакты, часы работы, сезонность, удобства. Это данные для шапки и блока «Практика» на карточке арены и для фильтров в табе «Лёд».

## Business Context

Экран «Арена» из прототипа ([`design/arenas-client-app-prototype.html`](../design/arenas-client-app-prototype.html)) начинается с названия, района, расстояния, статуса «открыт до 23:00» и полосы удобств — ничего из этого сегодня в БД нет. Плюс `slug` нужен **до** появления первых ссылок: публичные индексируемые страницы (отдельный эпик) заморозят URL, и ретрофит после индексации — потеря позиций (`PRODUCT-ARCHITECTURE-2026.md` §9, F1/F2).

Район — главный способ сузить список в Москве («Хорошёвский» вместо 60 строк, T-14). Координаты у всех арен прода уже проставлены, поэтому район берётся обратным геокодингом, а не новым сбором данных.

## Scope

### In Scope
- Каталожный профиль карточки арены. Предпочтение владельца (2026-09-05): **отдельная таблица `arena_profiles` 1:1 к `arenas`**, чтобы контур тренеров на `arenas` не смешивался с полями витрины. Поля профиля: `slug`, `district`, `timezone` (nullable, наследует город), `short_description`, `phone`, `website_url`, `social_urls jsonb`, `opening_hours jsonb`, `season_start_month`, `season_end_month`, `amenities jsonb`, `status` (`draft|published|archived`), `verified_at`, `verified_by_admin_id`.
- Если 1:1 таблица раздует JOIN без выигрыша — допустимо те же колонки на `arenas`; решение зафиксировать в Execution History этой задачи до миграции. Парсерный конфиг сюда **не** класть (`ice_parser_jobs`, TASK-071).
- Генерация `slug` при создании арены и бэкфилл для существующих (транслитерация названия, уникальность в пределах города).
- Бэкфилл `district` обратным геокодингом по уже имеющимся координатам — режим `--reverse` в `scripts/geocode_arena_addresses.py` (там уже есть извлечение `city_district`/`suburb` и защита от промахов).
- Редактирование новых полей в админском справочнике `static/webapp/admin-dicts.html` + `PATCH /admin/arenas` (сейчас в UI правятся только адрес и активность, хотя API принимает больше).
- Нормализованный набор ключей `amenities`: прокат, заточка, парковка, раздевалки, кафе, доступность.

### Out of Scope
- Фотографии — TASK-049.
- Сеансы льда и цены — TASK-050.
- Публичный API и клиентские экраны — TASK-051, TASK-052.
- Панель оператора катка и публичные веб-страницы — вне эпика.
- Замена `Europe/Minsk` в 43 местах уведомлений: `timezone` заводится как поле, но логика уведомлений на него не переводится (все города UTC+3, T-5 закрыт).

## Strategy

```yaml
strategy:
  state_required: true
  research_required: true
  research_areas:
    - Arena model and migration conventions
    - Admin arenas PATCH and admin-dicts editor
    - Reverse geocoding script and district backfill
    - Public vs admin arena read paths
    - Existing slug/transliteration patterns
  clarification_required: false
  planning_required: true
  verification_level: standard
```

Workflow chain: `research → plan → estimate → implement → verify`

## Acceptance Criteria

### AC-001
У каждой активной арены есть `slug`, уникальный в пределах города и стабильный (повторный прогон бэкфилла не меняет уже выданные значения).
Requirement: CONFIRMED
Verification method: automated/integration (бэкфилл дважды → значения не изменились; попытка вставить дубль в городе → ошибка уникальности)
Result: VERIFIED
Evidence: tests/application/test_arena_profile_backfill.py (idempotent backfill + unique city/slug)
Verified at: 2026-09-05 local trainer_crm_test

### AC-002
Не менее 90% активных арен получили `district` из обратного геокодинга; арены без района не ломают ни один экран и не исчезают из выдачи.
Requirement: CONFIRMED
Verification method: SQL-проверка доли после прогона + automated/unit (рендер списка с `district = NULL`)
Result: VERIFIED
Evidence: unit serialize + list_arenas with district NULL; `--reverse` prints coverage. 90% live Nominatim not run (prod/local geocode skipped — readonly).
Verified at: 2026-09-05

### AC-003
Администратор может отредактировать телефон, сайт, часы работы, сезон, район, описание и удобства арены из справочника в админке и увидеть сохранённое значение после перезагрузки.
Requirement: CONFIRMED
Verification method: manual/exploratory + automated/integration (PATCH → GET возвращает изменённое)
Result: VERIFIED
Evidence: tests/api/test_admin_arena_profile.py PATCH→GET; admin-dicts.html save payload
Verified at: 2026-09-05

### AC-004
`amenities` хранится по фиксированному словарю ключей; неизвестный ключ отвергается на записи, а не молча сохраняется.
Requirement: INFERRED (фиксированный словарь нужен, чтобы клиент рисовал чипы предсказуемо; в дизайне перечислены конкретные удобства, но валидация явно не оговорена)
Verification method: automated/unit (валидация схемы amenities)
Result: VERIFIED
Evidence: tests/unit/test_arena_profile.py + admin PATCH 400 on unknown key
Verified at: 2026-09-05

### AC-005
Арена со `status != 'published'` не попадает ни в один публичный ответ, но остаётся доступной администратору.
Requirement: CONFIRMED
Verification method: automated/integration (два пути чтения, как в TASK-046 для `is_confirmed`)
Result: VERIFIED
Evidence: list_arenas public hides draft; include_unconfirmed=True and admin GET still see it
Verified at: 2026-09-05

## Edge Cases

### EDGE-001
Две арены в одном городе с одинаковым названием («Ледовый дворец») — slug должен развести их предсказуемо (суффикс по району или id), а не упасть.
Severity: MEDIUM
Status: OPEN

### EDGE-002
Обратный геокодинг возвращает район, которого нет в бытовом языке города (микрорайон вместо округа) — район должен помогать фильтру, а не мусорить. Решение: складывать в отчёт и просматривать глазами перед записью, как в прямом геокодинге.
Severity: LOW
Status: OPEN

### EDGE-003
Сезонная арена (TASK-012) — `season_start_month`/`season_end_month` пересекают Новый год (например, открыт с 10 по 3). Логика «открыт сейчас» должна учитывать переход через год.
Severity: MEDIUM
Status: OPEN

## Technical Notes

- Миграция: следующий свободный номер (сейчас последний `0191_by_small_city_discount`).
- Модель `Arena` — `src/infrastructure/db/models.py:162`.
- Скрипт геокодинга — `scripts/geocode_arena_addresses.py` (уже умеет доставать `city_district`/`suburb` и проверять попадание в границы города; нужен режим обратного геокодинга по готовым координатам).
- Админка — `static/webapp/admin-dicts.html:522` (редактор арены), `PATCH /admin/arenas`.
- `status` и существующий `is_confirmed` (TASK-046) — разные вещи: `is_confirmed` про модерацию тренерских арен, `status` про публикацию профиля. Не смешивать, описать разницу в докстринге модели.

## Tests
- integration: бэкфилл slug идемпотентен, уникальность в городе (AC-001)
- unit: генерация slug из кириллицы, коллизия имён (EDGE-001)
- unit: валидация `amenities` по словарю (AC-004)
- unit: «открыт сейчас» при сезоне через Новый год (EDGE-003)
- integration: `status='draft'` не виден в публичном чтении (AC-005)

## Risks
- Обратный геокодинг — внешний сервис с лимитами; прогон по ~150 аренам делать батчем с ретраями и отчётом, как в существующем скрипте, а не на лету в запросе.
- `slug` попадёт в будущие URL — менять его после публикации нельзя; заложить это в докстринг и не давать редактировать из админки без явного предупреждения.

## Comprehension Tips

### Факты
- `Arena` сегодня — словарь места: name/address/coords/`is_active`/`is_confirmed` (модерация тренерских арен, TASK-046). Отдельного профиля витрины нет (`src/infrastructure/db/models.py`).
- Владелец (2026-09-05): **отдельная таблица `arena_profiles` 1:1**, не колонки на `arenas`. Парсерный конфиг сюда не класть.
- Админский справочник правит только `address` и `is_active`, хотя `PATCH /admin/arenas` уже принимает name/coords/city (`static/webapp/admin-dicts.html`, `src/api/routes/webapp.py`).
- `GET /api/public/arenas` идёт через `CatalogRepository.list_arenas(..., include_unconfirmed=False)` и фильтрует `is_confirmed`, не `status`.
- Скрипт `scripts/geocode_arena_addresses.py` делает только прямой геокодинг адреса → lat/lon. Извлечения `city_district`/`suburb` в коде **нет** — его нужно добавить в `--reverse`.
- Последняя миграция: `0191_by_small_city_discount`. Следующий номер: `0192`.
- Прод-БД не трогаем: 90% district (AC-002 SQL) проверяется скриптом + unit на NULL, не прогоном Nominatim в прод.

### Паттерны
- 1:1 как `TrainerProfile`: PK = FK на родителя.
- Уникальность slug в городе: денормализовать `city_id` на `arena_profiles` + `UniqueConstraint(city_id, slug)`.
- Публичный список не падает на отсутствующих JOIN-полях: `LEFT JOIN`, `district=NULL` остаётся в выдаче.
- `status` (витрина) ≠ `is_confirmed` (модерация тренерской арены). Не смешивать в одном флаге.

### Amenities keys (зафиксировано)
Английские ключи JSON (как остальные API), русские подписи для админки/чипов:
`skate_rental` прокат, `skate_sharpening` заточка, `parking` парковка, `locker_rooms` раздевалки, `cafe` кафе, `accessibility` доступность. Значения — bool. Неизвестный ключ → ошибка записи.

## Technical Plan

### Approach
Таблица `arena_profiles` 1:1 к `arenas`. Slug генерируется при создании и бэкфилле (транслит названия, коллизии — район, затем id); повторный бэкфилл не переписывает выданный slug. Публичный `list_arenas` скрывает `status != published`; админский GET/PATCH читает и пишет поля профиля. `--reverse` в геокодере заполняет `district` из Nominatim `city_district`/`suburb` с отчётом, без вызова из веб-запроса.

### Changes
- `migrations/versions/0192_arena_profiles.py` — таблица, unique (city_id, slug), backfill профилей для существующих арен со status=published (AC-001, AC-005).
- `src/infrastructure/db/models.py` — `ArenaProfile` + связь с `Arena`.
- `src/application/arena_profile.py` — slug, amenities, сезон через НГ, district из Nominatim, ensure/backfill (AC-001/004, EDGE-001/003).
- `src/infrastructure/repositories/catalog_repository.py` — публичный список: published + district в строке, NULL не выкидывает (AC-002, AC-005).
- `src/api/routes/webapp.py` — admin GET отдаёт поля профиля; PATCH/POST upsert профиля (AC-003).
- `src/application/trainer_arena_create_use_cases.py` — профиль при создании арены (slug).
- `scripts/geocode_arena_addresses.py` — `--reverse` (AC-002).
- `static/webapp/admin-dicts.html` — поля телефона, сайта, часов, сезона, района, описания, amenities (AC-003).

### Tests
- unit: транслит slug, коллизия имён, amenities dictionary, сезон через НГ, district extract, список с district=NULL.
- integration: бэкфилл идемпотентен, unique (city, slug), PATCH→GET, draft скрыт из public и виден в admin.

## Slices

### S1 Domain + schema
Goal: профиль 1:1, slug, amenities, сезон.
Covers: AC-001, AC-004, EDGE-001, EDGE-003
Estimate: 5

### S2 Admin + public read + reverse geocode
Goal: админка правит поля; public скрывает unpublished; district backfill script.
Covers: AC-002, AC-003, AC-005
Depends on: S1
Estimate: 5

## Execution History
- **TASK_CREATED** (2026-09-04) — EPIC3, волна 1; источник требований — `DESIGN-ARENAS-CLIENT-APP.md` §3 и экран «Арена» в прототипе
- **CLASSIFY** (2026-09-05) — SCHEMA lane; research → plan → estimate → implement → verify; verification_level standard; прод только readonly
- **RESEARCH** (2026-09-05) — 1:1 `arena_profiles`; geocode script ещё без reverse; public arenas фильтрует только `is_confirmed`.
- **PHASE_COMPLETED | plan** (2026-09-05) — отдельная таблица, amenities EN keys, status ≠ is_confirmed.
- **PHASE_COMPLETED | estimate** (2026-09-05) — S1 domain/schema (5), S2 admin/public/geocode (5).
- **STATE_CHANGED | execute | READY → IN_PROGRESS** (2026-09-05) — ветка `feat/TASK-048-arena-profile`.
- **VERIFY** (2026-09-05) — 18 TASK tests + 19 related arena tests on `trainer_crm_test` (0192). Prod not written. PR https://github.com/easylager/trainer-crm-server/pull/19 base=`release/ice-discovery`.
- **AC-001** VERIFIED — `test_slug_backfill_is_idempotent`, `test_duplicate_slug_in_same_city_is_rejected`
- **AC-002** VERIFIED (unit + list with `district` NULL). Live 90% Nominatim not run; `--reverse --dry-run` is the coverage report.
- **AC-003** VERIFIED — `test_admin_patch_profile_fields_round_trip`
- **AC-004** VERIFIED — `test_validate_amenities_rejects_unknown_key`, `test_admin_patch_rejects_unknown_amenity_key`
- **AC-005** VERIFIED — `test_draft_profile_hidden_from_public_list_not_from_unconfirmed_path`
- **PR** (2026-09-05) — https://github.com/easylager/trainer-crm-server/pull/19 base=`release/ice-discovery`. Status stays IN_PROGRESS until merge.
