---
task_id: TASK-021
title: Онбординг разрушает расписание, настроенное в «Расписании»
status: COMPLETE
phase: verify
priority: HIGH
created_at: 2026-09-02
updated_at: 2026-09-02
branch: onboarding-lossless-roundtrip
---

# Task

## Objective

Сделать экран онбординга безопасным при повторном открытии. Сейчас он читает шаблон
недели с потерями и перезаписывает его целиком, поэтому тренер, который что-то настроил
в разделе «Расписание», теряет часть настройки одним нажатием «Сохранить» — молча,
без единого предупреждения.

Инвариант, к которому идём:

> Онбординг владеет только теми строками шаблона, которые он умеет показать.
> Всё остальное он обязан увидеть, посчитать и оставить нетронутым.

## Business Context

Экран онбординга — не одноразовый. У вернувшегося тренера `already_done = true`,
заголовок становится «Ваше расписание», кнопка — «Сохранить»
(`static/webapp/trainer-onboarding-main.js:775-789`), и попасть туда можно из хаба
(`static/webapp/trainer-home-main.js:2757`, `:8064`). То есть это второй,
упрощённый редактор расписания, работающий поверх того же шаблона, что и основной.

Цена бага не в данных, а в доверии: тренер настроил слоты на :25, зашёл на знакомый
экран, нажал «Сохранить» — и его ученики видят другое время. Узнает он об этом от
ученика, а не от системы. Это ровно тот класс отказа, который убивает удержание на
второй неделе, и он же блокирует любое усложнение этого экрана: пока перезапись
разрушающая, добавлять туда мультиарену нельзя — это увеличит объём потерь.

Задача — предусловие для TASK-023 (мультиарена внутри дня) и TASK-024 (пресеты арен).

## Scope

### In Scope

- `GET /api/webapp/trainer/onboarding/quick-setup` — отдавать шаблон без потерь.
- `POST /api/webapp/trainer/onboarding/quick-setup` — перестать удалять то, чем экран не управляет.
- Формат `week` в обе стороны: часы → слоты (минута старта, арена, длительность).
- `parse_quick_setup_days` / `QuickSetupDay` / `_day_grid` — приём нового формата.
- Способ ограничить удаление в `replace_templates_for_day` строками `capacity = 1`
  для вызова из онбординга, не сломав два других вызова.
- Отображение в сетке онбординга слотов, которые не попадают на нарисованную часовую
  сетку (13:25), — read-only, но видимо и в счётчике «N окон в неделю».
- Регрессионные тесты на каждый из трёх сценариев потери.

### Out of Scope

- Мультиарена внутри одного дня — TASK-023. Здесь семантика «одна арена на день» сохраняется.
- Валидация длительности против пресета своей арены — TASK-022.
- Редизайн сетки (вкладки → кисти) — TASK-023.
- Заведение пресетов арен — TASK-024.
- Групповые занятия как поверхность: онбординг их не показывает и показывать не должен,
  задача только в том, чтобы он их не стирал.

## Comprehension Tips

### Facts

- **Потеря минут.** GET читает `EXTRACT(HOUR FROM start_time)::int`
  (`src/api/routes/webapp.py:7838`). Слот 13:25 приезжает на клиент как `13`. При
  сохранении `_day_grid` собирает старт как `h * 60 + offset`
  (`src/application/trainer_quick_setup_use_cases.py:376`), где `offset` — это
  `minute_offset` арены, а не исходные минуты слота.
- **Потеря второй арены в дне.** «First arena_id seen per day wins»
  (`src/api/routes/webapp.py:7849-7856`) — комментарий это признаёт как «mostly true
  label», но клиент отправляет эту же величину обратно, и она становится источником истины.
- **Потеря групповых строк.** GET фильтрует `capacity = 1` (`webapp.py:7837`), а
  `replace_templates_for_day` делает
  `DELETE FROM trainer_schedule_templates WHERE trainer_id = :tid AND day_of_week = :dow`
  без фильтра по `capacity` (`src/application/trainer_schedule_use_cases.py:174-180`).
  Онбординг вызывает его для **всех семи** дней недели, включая пустые
  (`trainer_quick_setup_use_cases.py:431`). Затрагивает тренеров с
  `group_classes_enabled` (`src/api/routes/webapp.py:798`).
- У `replace_templates_for_day` три вызова: `webapp.py:970` (schedule-editor, шлёт весь
  день целиком — полная замена там корректна), `trainer_handlers.py:3527` и
  `trainer_quick_setup_use_cases.py:431` (онбординг).
- Модель это уже поддерживает: `trainer_schedule_templates` — строка
  `(day_of_week, start_time, duration_minutes, capacity, service_id, arena_id)`;
  `replace_templates_for_day` принимает `minute_to_arena_id` и `minute_to_duration`
  (`trainer_schedule_use_cases.py:122-143`) и проверяет пересечения по всему дню (`:165-171`).

### Implications

- Достаточно перевести контракт с «часов» на «слоты» — доменный слой менять не нужно.
- Клиентская сетка остаётся часовой: она рисует и красит только те слоты, что попадают
  на её сетку. Остальные обязана показать, иначе счётчик «N окон в неделю» врёт и тренер
  может создать пересечение, которое сервер отклонит без внятной причины.
- Ограничивать удаление по `capacity` лучше явным параметром вызова, а не глобально:
  schedule-editor обязан сохранить право стирать групповые строки.

## Acceptance Criteria

### AC-001
Слот с нецелой минутой старта (13:25) переживает цикл «открыть онбординг → нажать
«Сохранить», ничего не меняя»: `start_time` в шаблоне не изменился.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: tests/application/test_quick_setup_roundtrip.py::test_minutes_survive_a_save_that_changed_nothing; сквозной HTTP — tests/api/test_webapp_trainer_quick_setup.py::test_reopening_and_saving_changes_nothing; живой прогон в браузере на trainer_id=34 (слот 13:25 цел после реального «Сохранить»)
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-002
Групповая строка шаблона (`capacity > 1`) переживает тот же цикл: строка на месте,
`capacity`, `service_id` и `arena_id` не изменились.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: tests/application/test_quick_setup_roundtrip.py::test_group_rows_survive_a_save и ::test_group_row_survives_a_day_the_trainer_cleared
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-003
День, в котором в шаблоне лежат строки с двумя разными `arena_id`, переживает тот же
цикл без изменения ни одной строки.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: tests/application/test_quick_setup_roundtrip.py::test_two_arenas_in_one_day_survive_a_save; живой прогон: ВТ 19:00 на второй арене цел
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-004
Снятие отметки с клетки в онбординге удаляет ровно одну строку шаблона — ту, что стояла
на этом старте и этой арене; остальные строки того же дня не тронуты.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: tests/application/test_quick_setup_roundtrip.py::test_unchecking_one_cell_removes_exactly_that_row
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-005
Счётчик «N окон в неделю» на экране равен фактическому числу индивидуальных строк
шаблона, включая слоты вне нарисованной часовой сетки.
Requirement: CONFIRMED
Verification method: e2e
Capability: playwright
Result: VERIFIED
Evidence: живой прогон в браузере: счётчик «24 окна в неделю» = 22 клетки сетки + 2 перенесённых слота; совпадает с 24 строками capacity=1 в trainer_schedule_templates
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-006
Слот вне часовой сетки экрана отображается с реальным временем и подписью, что правится
он в «Расписании»; нажатие на него ничего не меняет.
Requirement: INFERRED
Verification method: e2e
Capability: playwright
Result: VERIFIED
Evidence: живой прогон: блок #obCarried показывает «ВТ 13:25 · Манеж, 19:00 · ТЦ Замок» и подпись «Менять их — в разделе «Расписание»»; блок нередактируем (не содержит кнопок)
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-007
Вызов `replace_templates_for_day` из schedule-editor по-прежнему полностью заменяет день,
включая групповые строки.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: only_capacity_one по умолчанию False — schedule-editor (webapp.py:970) заменяет день целиком как раньше; 233 теста по маске schedule/template/slot/arena без новых падений
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

### AC-008
Полный прогон pytest не хуже базовой линии на момент старта задачи.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: полный прогон 1198 passed / 11 failed против базовой 1184 / 8; все 11 воспроизводятся на чистом дереве через git stash
Verified at: 2026-09-02, ветка onboarding-lossless-roundtrip (не закоммичено)

## Edge Cases

### EDGE-001
Тренер снимает в онбординге отметку с дня, в котором есть только групповые строки.
День для онбординга пустой, но удалять его строки нельзя.
Severity: HIGH
Status: RESOLVED
Resolution: `only_capacity_one=True` ограничивает DELETE строками `capacity = 1`.
Verification: `test_group_row_survives_a_day_the_trainer_cleared`

### EDGE-002
Слот вне часовой сетки пересекается по времени с клеткой, которую тренер пытается
закрасить (13:25–14:25 против 14:00). Сервер отклонит день целиком
(`trainer_schedule_use_cases.py:170`) — нужна внятная ошибка на экране, а не «не получилось сохранить».
Severity: MEDIUM
Status: RESOLVED
Resolution: проверка пересечений расширена на выжившие групповые строки; `ValueError`
маппится в 400 с текстом, а экран показывает `body.detail` через `note()`. Текст
(«Интервалы слотов в шаблоне пересекаются») называет проблему, но не слот — доработка
сообщения переехала в TASK-023 AC-004, где мультиарена делает такие конфликты частыми.
Verification: `test_new_individual_slot_cannot_be_laid_over_a_group_class`

### EDGE-003
`minute_offset` арены поменялся между двумя открытиями экрана. Сохранённые слоты стоят
на старом смещении, сетка рисует новое. Решить: переносить (и сказать об этом) или
показывать как вне-сеточные.
Severity: MEDIUM
Status: RESOLVED
Resolution: показываются как вне-сеточные — `slotFitsGrid` отбрасывает слот, чья минута
не совпадает со смещением площадки, и он уезжает в перенесённые. Ничего не теряется и
ничего не двигается молча. Осознанный перенос таких слотов — вопрос Q-001 в TASK-024,
где меняется сам пресет.
Verification: `slotFitsGrid` (static/webapp/trainer-onboarding-main.js); живой прогон

## Decisions

### DEC-001
Decision: Контракт `week` переводится с массива часов на массив слотов
(`day_of_week`, `start_minute`, `duration_minutes`, `arena_id`) в обе стороны.
Reason: Потеря минут и потеря арены — не два бага, а одно следствие того, что формат
запроса беднее модели. Латать GET, не меняя POST, оставит вторую половину потери.
Alternatives: отдавать минуты только на чтение и запрещать сохранение при их наличии —
превращает знакомый экран в тупик и не решает проблему групповых строк.

### DEC-002
Decision: Онбординг никогда не трогает строки `capacity > 1`. Ограничение передаётся
явным аргументом `replace_templates_for_day`, а не меняется по умолчанию.
Reason: Schedule-editor присылает день целиком и обязан сохранить право полной замены.
Молчаливое изменение поведения общей функции сломает его без единого падающего теста.

### DEC-003
Decision: Слоты вне нарисованной часовой сетки показываются read-only, а не прячутся
и не выкидывают тренера в «Расписание».
Reason: Спрятанный слот означает врущий счётчик и пересечения, причину которых тренер
не видит. Показанный, но не редактируемый — честная граница возможностей экрана.
Alternatives: рисовать сетку с шагом 5 минут — превращает первый экран в 200+ клеток.

## Decisions (продолжение)

### DEC-004
Decision: Перенесённые слоты живут в отдельном `state.carried`, а не в редактируемой модели сетки.
Reason: Переключение режима площадок (`setArenaMode`, `toggleMultiArena`) чистит `state.week`
целиком. Держать неотображаемые слоты там значило бы терять их при каждом переключении —
то есть чинить потерю на сохранении и заводить её на переключении.
Alternatives: помечать слоты флагом внутри `state.week` — отклонено: каждая из четырёх функций,
меняющих неделю, должна была бы помнить про флаг.

## Найдено по дороге

**Гард парсера отвечал 400 на нормальный запрос.** Первая версия
`parse_quick_setup_days` считала ошибкой клиента день, пришедший и в `hours`, и в `slots`.
Но экран именно так и шлёт: нарисованную часть дня — часами, перенесённую — минутами.
Вернувшийся тренер вообще не мог сохраниться. Поймано живым прогоном в браузере, не тестами:
все юнит-тесты слали день одной формой. Починено (`resolved_slots` мержит обе формы,
явный слот выигрывает при совпадении минуты), регрессия закрыта тестом
`test_hour_grid_and_carried_slots_arrive_together_for_one_day`.

## Next Action

Задача закрыта. Осталось закоммитить вместе с TASK-022 (общая ветка).
Дальше — TASK-023, чей backend-срез S1 после этой правки почти целиком уже на месте.

## Execution History

- **COMPLETED** — 2026-09-02. Контракт `week` переведён на слоты (минута старта, длительность,
  площадка) в обе стороны, с сохранением легаси-формы `hours` на один релиз. Онбординг больше
  не удаляет строки `capacity > 1`, а они участвуют в проверке пересечений. Экран показывает
  и возвращает нетронутыми слоты, которые не умеет нарисовать. 10 новых тестов
  (`tests/application/test_quick_setup_roundtrip.py`, 2 сквозных в
  `tests/api/test_webapp_trainer_quick_setup.py`) плюс живой прогон в браузере.
- **TASK_CREATED** — заведена 2026-09-02 по исследованию `.ai/RESEARCH-onboarding-multi-arena.md`, §5 пункты 1–3.
