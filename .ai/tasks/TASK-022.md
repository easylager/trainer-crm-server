---
task_id: TASK-022
title: Длительность слота валидируется против пресета чужой арены
status: COMPLETE
phase: verify
priority: HIGH
created_at: 2026-09-02
updated_at: 2026-09-02
branch: onboarding-lossless-roundtrip
---

# Task

## Objective

Проверять длительность строки шаблона против пресета **той арены, которой эта строка
принадлежит**, а не против пресета основной арены тренера. Сейчас тренер, работающий на
двух аренах с разной фиксированной длительностью, не может сохранить расписание вообще —
и сообщение об ошибке говорит про «площадку этой сетки», не называя, про какую именно
площадку речь.

## Business Context

«Разная длина занятия на разных аренах» — один из двух названных владельцем продукта
случаев, ради которых затевается гибкость онбординга. Механизм для него уже есть
(`minute_to_duration`), но валидация его перекрывает: она предполагает, что у тренера
ровно одна сетка на всё расписание. Для одноарённого тренера это верно, для
двухарённого — нет, и именно двухарённый тренер и есть предмет TASK-023.

Отдельная стоимость — диагностируемость. Ошибка «Длительность зафиксирована для площадки
этой сетки — используйте указанное значение» не называет ни площадку, ни значение, ни
слот. Тренер, получивший её в мини-аппе, не может понять, что чинить.

Это предусловие для TASK-023: без него мультиарена внутри дня падает на сохранении.

## Scope

### In Scope

- `validate_duration_for_preset` и `validate_start_minutes_for_preset` — вызывать с пресетом
  арены строки (`src/application/arena_schedule_preset.py:77`, `:105`).
- `replace_templates_for_day` — резолвить пресет на строку, а не на весь вызов
  (`src/application/trainer_schedule_use_cases.py:146-163`).
- Текст ошибки: назвать арену, требуемую длительность и время слота.
- Ветка `loose_alignment` — пересмотреть: сейчас любой старт вне сетки отключает проверку
  стартов для **всех** строк дня.
- Тесты на две арены с разной фиксированной длительностью в одном дне и в разных днях.

### Out of Scope

- UI выбора длительности — здесь только серверная валидация.
- Ручной выбор длительности на арену в онбординге (ось B из исследования) — сознательно не делается.
- Пресеты по дням недели — TASK-025.

## Comprehension Tips

### Facts

- `replace_templates_for_day` резолвит **один** пресет на весь вызов:
  `preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)`
  (`trainer_schedule_use_cases.py:146`), а тот берёт `primary_arena_id` тренера
  (`arena_schedule_preset.py:112-135`).
- При `len(unique_durs) > 1` включается `loose_alignment` и каждая длительность
  проверяется против того же самого пресета основной арены (`:156-163`).
  Основная арена фиксирует 60, вторая — 45 → `validate_duration_for_preset(45, presetA)`
  бросает `ValueError`.
- `primary_arena_id` выставляется онбордингом только когда арена ровно одна
  (`trainer_quick_setup_use_cases.py:334-344`), но может быть уже проставлен раньше —
  регистрацией на сайте или профилем; комментарий там это фиксирует. То есть
  «мультиарённый тренер без primary» — не гарантия, а частый случай.
- `loose_alignment = off_grid or len(unique_durs) > 1` (`:157`): достаточно одного
  старта вне сетки, чтобы проверка стартов отключилась для всего дня. Это существующая
  лазейка, а не новая — но при мультиарене она станет нормой, а не исключением.
- `_day_grid` уже держит пресеты всех задействованных арен в словаре
  (`trainer_quick_setup_use_cases.py:299-345`) — источник данных есть.

### Implications

- Правка локальная: пресет резолвится на строку по её `arena_id`, с откатом на пресет
  тренера, когда `arena_id` у строки нет (`NULL` = «арена по умолчанию»).
- Понадобится дешёвый кэш пресетов внутри вызова: строк в дне единицы, арен — единицы,
  но ходить в БД на каждую строку незачем.
- `loose_alignment` после правки честнее считать **на строку**: старт валиден или нет
  относительно своей арены. Это ужесточение — проверить, что оно не ломает существующие
  сценарии schedule-editor, где точные слоты сознательно стоят вне сетки.

## Acceptance Criteria

### AC-001
День с двумя строками — арена A с фиксированными 60 мин и арена B с фиксированными
45 мин — сохраняется без ошибки, обе строки получают свою длительность.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: tests/application/test_template_duration_per_arena.py::test_two_arenas_with_different_fixed_durations_save_in_one_day
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-002
Строка на арене с фиксированной длительностью 60 мин и длительностью 45 мин
отклоняется, даже если основная арена тренера фиксирует 45.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: tests/application/test_template_duration_per_arena.py::test_row_duration_is_checked_against_its_own_arena_not_the_primary
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-003
Текст ошибки называет арену, требуемую длительность и время слота.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: tests/application/test_template_duration_per_arena.py::test_error_names_the_arena_the_duration_and_the_time
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-004
Строка без `arena_id` валидируется против пресета тренера — поведение одноарённого
и безарённого тренера не изменилось.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: tests/application/test_template_duration_per_arena.py::test_row_without_arena_still_uses_the_trainer_preset
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-005
Существующие тесты schedule-editor на точные слоты вне сетки проходят без правок.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: tests/application/test_template_duration_per_arena.py::test_off_grid_starts_are_still_allowed; 233 теста по маске schedule/template/slot/arena — без новых падений
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-006
Полный прогон pytest не хуже базовой линии на момент старта задачи.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: полный прогон 1198 passed / 11 failed против базовой 1184 / 8; все 11 воспроизводятся на чистом дереве (3 из них времязависимые)
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

## Edge Cases

### EDGE-001
Арена без строки в `arena_schedule_presets`. `get_arena_schedule_preset_raw` должен
отдать дефолт (`quarter_15`, 6–23, длительность не зафиксирована), а не упасть.
Severity: MEDIUM
Status: RESOLVED
Resolution: `_presets_by_arena` использует `get_arena_schedule_preset_raw`, который уже
откатывается на `default_quarter_preset()` — длительность там не зафиксирована, проверка
для такой арены становится пустой.
Verification: `test_off_grid_starts_are_still_allowed` (арена без пресета)

### EDGE-002
Групповая строка с `group_arena_id`, отличным от арены индивидуальных строк того же дня.
Определить, против какого пресета она проверяется.
Severity: MEDIUM
Status: RESOLVED
Resolution: против пресета своей площадки — `group_arena_id`, а при его отсутствии
`trainer_default_slot_arena_id`, то есть ровно та арена, которая и запишется в строку.
Verification: `test_group_row_is_checked_against_its_group_arena`

### EDGE-003
Ужесточение проверки стартов «на строку» может отклонить день, который сегодня
проходит через `loose_alignment`. Нужен явный ответ: считаем это исправлением бага
или сохраняем послабление для точных слотов.
Severity: HIGH
Status: RESOLVED
Resolution: послабление сохранено — см. DEC-002. Проверка стартов не тронута, изменена
только проверка длительности.
Verification: `test_off_grid_starts_are_still_allowed`; ни один тест schedule-editor не правился

## Open Questions

### Q-001 — ОТВЕЧЕН
Сохраняем ли послабление `loose_alignment` для точных слотов после перехода на
per-row валидацию? — Affects: AC-005, EDGE-003
Ответ: сохраняем. См. DEC-002.

## Decisions

### DEC-001
Decision: Пресет резолвится по `arena_id` строки; при `arena_id IS NULL` — пресет тренера.
Reason: `arena_id NULL` в модели уже означает «арена тренера по умолчанию»
(`trainer_schedule_use_cases.py:138-139`), правило валидации обязано читать его так же.

## Decisions (продолжение)

### DEC-002
Decision: Проверка выравнивания стартов остаётся дневной и против сетки тренера;
per-arena стала только проверка длительности.
Reason: Вкладка «Точное время» существует ровно для того, чтобы ставить старты вне сетки —
ужесточение отняло бы заявленную возможность ради дефекта, который к стартам не относится.
Объём правки при этом сузился до одной причины отказа.
Alternatives: валидировать старты по арене строки — отклонено: сломало бы точные слоты
в разделе «Расписание», не починив ничего.

### DEC-003
Decision: Пустой день больше не валидирует длительность.
Reason: Применять её не к чему. Именно это ограничение обходил `empty_day_duration`
в онбординге; после правки обходной путь удалён вместе с причиной.
Verification: `test_empty_day_does_not_validate_a_duration_nothing_uses`

## Next Action

Задача закрыта. Осталось закоммитить вместе с TASK-021 (общая ветка).

## Execution History

- **COMPLETED** — 2026-09-02. Пресет резолвится на строку (`_presets_by_arena`), сообщение
  об ошибке называет площадку, требуемую длительность и время слота. Удалён обходной путь
  `empty_day_duration` в онбординге — он существовал только из-за этого дефекта.
  7 новых тестов: `tests/application/test_template_duration_per_arena.py`.
- **TASK_CREATED** — заведена 2026-09-02 по исследованию `.ai/RESEARCH-onboarding-multi-arena.md`, §5 пункт 4.
