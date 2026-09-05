---
task_id: TASK-073
title: Досье карточек арен Минска — факты, сверка, фото с лицензией
status: MERGED
phase: done
epic: EPIC3
depends_on: []
execution_mode: SUPERVISED
created_at: 2026-09-05
updated_at: 2026-09-05
city: Минск
lane: CONTENT
---

# Task

## Objective

Собрать и **сверить** данные для карточки катка (не для слотов МК): адрес/район, телефон, сайт, часы, сезон, amenities, короткое описание и **легальные** фото. Результат — досье на каждую публичную МК-арену Минска, из которого админ заполняет `arena_profiles` + медиа. Парсер это не делает.

## Business Context

Клиент открывает карточку из-за места, а не из-за JSON слотов. Схема (TASK-048) и загрузчик фото (TASK-049) — код. Без проверенного контента карточка пустая даже после merge 048. Слоты массового катания собирает ingest (SPEC/061). Сюда они **не** входят — иначе досье протухнет вместе с кассой.

Юридически: **не скачивать картинки из Google/Яндекс**. Только сайт катка, соцсеть катка с явной публикацией, свои съёмки, разрешение оператора (`license` в TASK-049).

## Scope

### In Scope
- Пилот: публичные МК Минска из `.ai/data/minsk-arenas-prod.csv` + реестр (Замок, Минск-Арена, Чижовка, led.by, Юность, DiaMond, ledlife если доступен; **не** лыжероллер / JUSTSKATE / Финт как «покататься»).
- Один файл на арену: `.ai/data/arena-cards/minsk-<slug>.md` (факты + источники + дата сверки + уверенность).
- Поля карточки = TASK-048: phone, website, socials, opening_hours, season, amenities, short_description, district (проверить против геокода).
- Фото: список URL **источника**, предложенный `license` (`operator|own|permitted`), attribution, что на кадре (фасад / лёд / холл). Сами файлы класть в `.ai/data/arena-cards/photos/<slug>/` **только** если лицензия явная; иначе только URL + «нужно разрешение».
- Сверка: каждый факт — источник + дата. Противоречие сайт vs вывеска vs звонок — писать в `conflicts`, не угадывать.

### Out of Scope
- Код `media` / админ-загрузка — TASK-049.
- Запись в прод и админку — TASK-063 (берёт эти досье).
- Слоты, цены сеансов, прокат как поле слота — SPEC / 050 / 061.
- Скрейп поисковых картинок, стоки «ледовый дворец», фото с карточек конкурентов.

## Acceptance Criteria

### AC-001
На каждую целевую МК-арену Минска есть досье с заполненными или явно `unknown` полями профиля и хотя бы одним решением по фото (есть лицензионный кадр **или** честный «фото нет / ждём разрешение»).
Requirement: CONFIRMED
Verification method: список файлов в `.ai/data/arena-cards/` vs целевой список в этом TASK

### AC-002
У каждого не-`unknown` факта указан URL или «звонок ДД.ММ» и `verified_at`. Нет фактов без источника.
Requirement: CONFIRMED
Verification method: ручной проход 2 досье + выборочно остальные

### AC-003
Ни один файл в `photos/` не взят из поисковой выдачи; у каждого локального файла есть `license` + attribution в досье.
Requirement: CONFIRMED
Verification method: сверка досье ↔ папки photos

## Technical Notes
- Lane **CONTENT**: пишет только `.ai/data/arena-cards/`. Не `src/`, не `models.py`, не `.ai/parsers/`.
- Прод-БД: тот же read-only протокол, что SPEC (`SET default_transaction_read_only = on`). Имена/id арен — из CSV, не выдумывать.
- Параллельно SCHEMA/SPEC уже сейчас. Загрузка в продукт — после merge 048 и 049.

## Execution History
- **TASK_CREATED** (2026-09-05) — владелец: отдельный топик контента карточек, не смешивать с парсерами и с кодом медиа-слоя
- **SLICE_CORE_MERGED** (2026-09-06) — https://github.com/easylager/trainer-crm-server/pull/22 squash `d158bd14c9f429d5c173b6bc8b33407840da7563` → `release/ice-discovery`. Досье: minskarena, zamok, chizhovka, ledby.
- **MERGED** (2026-09-06) — https://github.com/easylager/trainer-crm-server/pull/21 squash `319cd479fb7953c82101b2329fc5226e94491c09` → `release/ice-discovery`. Досье diamond / junost / ledlife. Не в master. Перед TASK-063: звонок по конфликтам телефонов; BY-egress для junost/ledlife; фото — URL + «нужно разрешение», не CDN.
