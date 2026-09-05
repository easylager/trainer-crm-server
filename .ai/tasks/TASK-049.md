---
task_id: TASK-049
title: Медиа-слой и фотографии арен
status: MERGED
phase: verify
epic: EPIC3
depends_on: [TASK-048]
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-05
branch: feat/TASK-049-arena-media
pr: https://github.com/easylager/trainer-crm-server/pull/20
merge_sha: 79640f1586fbe4e743e021397197d0e89226cc34
---

# Task

## Objective

Обобщить хранение изображений с «фото тренера» до медиа-слоя с типом владельца, чтобы у арены появилось hero-фото и небольшая галерея — без этого карточка катка не конвертит.

## Business Context

В прототипе фото — первое, что видно на карточке арены и в каждой строке списка «Лёд». Это единственный сигнал «нормальное место», доступный до визита. Сейчас инфраструктура изображений жёстко про тренера: таблица `trainer_photos` и захардкоженный префикс `trainers/` в `_photo_url_from_cdn` (`src/api/routes/public.py:212`). Ретрофит типа владельца через год стоит дороже, чем обобщение сейчас (`PRODUCT-ARCHITECTURE-2026.md` F4).

## Scope

### In Scope
- Таблица `media`: `owner_type` (`arena|coach|collective`), `owner_id`, `storage_key`, `variants jsonb` (`thumb ~320`, `card ~800`, `hero ~1600`), `width`, `height`, `blurhash`, `license` (`own|operator|user|permitted`), `attribution`, `source_url`, `sort_order`, `status` (`pending|published|rejected`).
- Адаптер поверх `trainer_photos` — существующие фото тренеров продолжают работать без миграции данных (или мигрируются одним проходом, решить в /plan).
- Снятие хардкода `trainers/` в построении URL.
- Загрузка и сортировка фото арены в админском справочнике; hero — первая опубликованная по `sort_order`.
- WebP + фолбэк, blurhash/LQIP как плейсхолдер (Telegram WebView на слабой сети).

### Out of Scope
- Пользовательские фото арен и модерация UGC — нет трафика, отдельная задача.
- Сбор и сверка фактов/фото Минска — TASK-073. Эта задача — слой хранения и админ-загрузка, не «найти красивые картинки».
- CDN-инфраструктура как таковая (бакет/домен) — если её нет, задача работает через существующий путь отдачи, но без хардкода типа владельца.
- Фото сеансов льда и групп.

## Strategy

```yaml
strategy:
  state_required: true
  research_required: true
  research_areas:
    - trainer_photos model and storage keys
    - public photo URL / CDN construction
    - admin upload and image processing
    - adapter vs migrate trainer_photos
  clarification_required: false
  planning_required: true
  verification_level: elevated
```

Workflow chain: `research → plan → estimate → implement → verify`

## Acceptance Criteria

### AC-001
Администратор загружает до 6 фото арены, задаёт порядок, первое опубликованное используется как hero на карточке.
Requirement: CONFIRMED
Verification method: manual/exploratory + automated/integration (загрузка → GET арены отдаёт hero и галерею в заданном порядке)

### AC-002
Существующие фото тренеров продолжают отдаваться по прежним URL после введения медиа-слоя — ни одна карточка тренера не теряет изображение.
Requirement: CONFIRMED
Verification method: automated/integration (регрессия на существующих тестах отдачи фото тренера)

### AC-003
Каждое изображение отдаётся в трёх вариантах; список арен запрашивает `thumb`, карточка — `hero`; ни один экран не грузит оригинал.
Requirement: CONFIRMED
Verification method: static analysis (в клиентском коде нет обращений к оригиналу) + manual (размер ответа в списке)

### AC-004
У изображения обязательно указана лицензия и, если она не `own`, — источник/атрибуция. Запись без лицензии невозможна.
Requirement: CONFIRMED
Verification method: automated/unit (валидация при создании записи)

### AC-005
Пока у арены нет ни одного опубликованного фото, карточка и строка списка выглядят корректно (плейсхолдер, а не битая картинка и не пустое место).
Requirement: CONFIRMED
Verification method: manual/exploratory + automated/unit (рендер без media)

## Edge Cases

### EDGE-001
Фото загружено, но `blurhash` не посчитан (сбой обработки) — плейсхолдер должен деградировать до нейтральной заливки, а не ломать вёрстку.
Severity: LOW
Status: OPEN

### EDGE-002
Арена удалена/архивирована — её медиа остаются в хранилище. Нужна политика (пометить, не удалять физически сразу).
Severity: LOW
Status: OPEN

## Technical Notes

- `TrainerPhoto` — `src/infrastructure/db/models.py:306`; отдача — `src/api/routes/public.py:212-240`.
- Юридическое ограничение, зафиксировать в коде и в UI загрузки: **не скрейпить изображения из поисковых картинок**. Допустимые источники — свои, оператора катка, пользовательские, с явного разрешения (`PRODUCT-ARCHITECTURE-2026.md` §7).

## Tests
- integration: загрузка → три варианта → hero/галерея в порядке `sort_order` (AC-001, AC-003)
- integration: регрессия отдачи фото тренера через новый слой (AC-002)
- unit: отказ записи без лицензии (AC-004)
- unit: рендер карточки и строки списка без media (AC-005)

## Risks
- Миграция `trainer_photos` — путь наибольшего риска в задаче; безопаснее адаптер поверх старой таблицы, чем перенос данных перед релизом.

## Execution History
- **TASK_CREATED** (2026-09-04) — EPIC3, волна 2
- **CLASSIFY** (2026-09-05) — SCHEMA after TASK-048 MERGED; adapter over trainer_photos preferred; no Google image scrape
- **DEPENDENCY** (2026-09-05) — TASK-048 MERGED `c90e5e00bb8d84c54e5aae488cdc7a5e3b825e04` on `release/ice-discovery`
- **RESEARCH** (2026-09-05) — TrainerPhoto keys `trainers/{id}`; CDN was trainers-only; no admin gallery; Alembic head 0192
- **PHASE_COMPLETED | plan** (2026-09-05) — media table for arenas; trainer_photos untouched; JPEG 320/800/1600
- **STATE_CHANGED | execute | READY → IN_PROGRESS** (2026-09-05) — ветка `feat/TASK-049-arena-media` from `release/ice-discovery`
- **VERIFY** (2026-09-05) — unit + admin upload/reorder/public empty-hero on `trainer_crm_test` (0193). Prod not written. `catalog-main.js` not touched.
- **AC-001** VERIFIED — `test_admin_upload_two_photos_sets_hero_and_gallery_order`
- **AC-002** VERIFIED — `test_public_catalog_list_shape_photo_source_and_no_leaks`, `test_trainer_photo_upload`, `test_s3_object_keys` trainers prefix
- **AC-003** VERIFIED — upload payload exposes `thumb`/`card`/`hero` variant URLs; originals not stored
- **AC-004** VERIFIED — `test_license_operator_requires_attribution_or_source`, `test_admin_upload_requires_license`, DB check `ck_media_license_source`
- **AC-005** VERIFIED — `test_public_arena_without_photos_has_null_hero_and_empty_gallery` + admin placeholder
- **PR** (2026-09-05) — https://github.com/easylager/trainer-crm-server/pull/20 base=`release/ice-discovery`.
- **MERGED** (2026-09-05) — squash `79640f1586fbe4e743e021397197d0e89226cc34` into `release/ice-discovery`. CI green. Not merged to master.

## Comprehension Tips

### Facts
- Фото тренера: таблица `trainer_photos` (`file_key` + `file_key_list`), ключи `trainers/{id}/…`. Два JPEG (800 и 320), оригинал после ресайза не хранится (`src/infrastructure/s3.py`).
- CDN URL: allowlist `trainers/` | `arenas/` | `collectives/` (`src/application/photo_cdn.py`).
- В админке арен — галерея в `admin-dicts.html` (max 6, лицензия).
- Pillow JPEG 320/800/1600; WebP/blurhash не считаем (DEC-004).
- Alembic head: `0193_media`.

### Patterns
- Адаптер поверх `trainer_photos` → media-shaped DTO; строки тренеров не мигрируем (риск AC-002).
- Новая таблица `media` только для арен (и будущих owner_type); каталог тренеров продолжает читать `trainer_photos`.
- Префиксы ключей: `arenas/{arena_id}/…` рядом с `trainers/`. CDN-гейт — allowlist префиксов, не один `trainers/`.

### Decisions
- **DEC-001:** таблица `media` + read-adapter для trainer photos. Не переносить ряды `trainer_photos` в этом PR.
- **DEC-002:** лицензия обязательна; если не `own` — нужен `source_url` или `attribution`.
- **DEC-003:** клиентские экраны «Лёд» (052) не трогаем; AC-005 — контракт API (null hero + gallery []) и CSS-плейсхолдер в admin-dicts.
- **DEC-004:** три JPEG-варианта (320/800/1600) существующим Pillow-пайплайном. WebP в этом PR не пишем (нет отдельного энкодера). `blurhash` nullable — плейсхолдер деградирует до заливки (EDGE-001).

## Technical Plan

### Approach
Новая `media` 1:N к владельцу. Админ загружает до 6 фото арены; пайплайн делает thumb/card/hero. Публичное чтение арен отдаёт URL вариантов. Тренерские фото идут через адаптер без смены URL.

### Changes
- `migrations/versions/0193_media.py` — таблица media, check owner_type/license/status.
- `src/infrastructure/db/models.py` — `Media`.
- `src/application/arena_media.py` — валидация лицензии, лимит 6, hero = первая published по sort_order, DTO.
- `src/infrastructure/s3.py` + CDN helper — префиксы arenas/, варианты 320/800/1600.
- `src/api/routes/webapp.py` — admin multipart upload / reorder / list для арены.
- `src/api/routes/public.py` — `_photo_url_from_cdn` allowlist; trainer path unchanged.
- `static/webapp/admin-dicts.html` — галерея в карточке арены.

### Tests
- unit: отказ без license; attribution если license != own (AC-004).
- integration: trainer catalog photo URLs unchanged (AC-002).
- integration: upload 2 photos → GET hero = sort_order 0 published, gallery ordered (AC-001, AC-003).
- unit: serialize arena without media → hero null, gallery [] (AC-005).

## Slices

### S1 Media schema + license + trainer adapter
Goal: таблица media, валидация лицензии, CDN allowlist, тренерские URL не ломаются.
Covers: AC-002, AC-004
Estimate: 5

### S2 Arena upload + admin gallery
Goal: до 6 фото, порядок, hero, три варианта.
Covers: AC-001, AC-003
Depends on: S1
Estimate: 5

### S3 Empty media contract
Goal: нет фото → не ломает GET/админку.
Covers: AC-005, EDGE-001
Depends on: S1
Estimate: 2
