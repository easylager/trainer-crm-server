---
task_id: TASK-027
title: Тестовая или отменённая запись гасит всё ведение к первому клиенту
status: COMPLETE
phase: review
priority: HIGH
created_at: 2026-09-02
updated_at: 2026-09-02
---

# Task

## Objective

Привести флаг «первая запись состоялась» к одному определению во всех местах, где он
управляет ведением тренера. Сейчас `has_any_booking` считает любую строку в `bookings` —
включая песочницу и мгновенно отменённые записи, — и одна такая строка выключает всю
цепочку подсказок, ведущих к первому настоящему клиенту.

Инвариант, к которому идём:

> «Первая запись» для онбординга — это запись живого клиента, не песочница
> и не строка, отменённая до занятия.

## Business Context

Флаг `has_any_booking` управляет тремя вещами сразу:

1. карточка «Отправьте ссылку одному ученику» исчезает (`trainer_next_step.py:120-134`);
2. включается реферальная подсказка «пригласите коллег»
   (`trainer_hub_action_inbox.py:232-252`);
3. **полностью останавливается серия реактивации D+1/D+3/D+7** —
   `determine_onboarding_stage` возвращает `None` при `has_any_booking`
   (`trainer_onboarding_recovery_use_cases.py:107-110`), а сегмент кандидатов вообще
   отсекает тренеров любым `EXISTS`-ом по `bookings` (`:145`).

То есть тренер, который завёл тестовую запись «посмотреть, как выглядит», или чья
единственная запись сорвалась и была отменена, молча выпадает из всей системы ведения
к первому реальному клиенту — в тот самый момент, когда ведение ему нужнее всего.

Рядом, в этом же файле, `real_bookings_count` считается честно
(`status IN ('confirmed','completed') AND NOT is_sandbox`,
`trainer_onboarding_checklist.py:370-376`), и milestone тоже исключает песочницу
(`trainer_first_booking_milestone.py:4-7`). Правила разъехались внутри одного модуля.

Задача маленькая и не зависит ни от чего — её можно брать первой.

## Scope

### In Scope

- `has_any_booking` в `src/application/trainer_onboarding_checklist.py:308-320`.
- Сегмент кандидатов реактивации `NOT EXISTS (SELECT 1 FROM bookings ...)` в
  `src/application/trainer_onboarding_recovery_use_cases.py:139-147`.
- Ревизия остальных потребителей `has_any_booking` и `_onboarding_booking_step_done`
  (`trainer_hub_action_inbox.py:96-101`) — убедиться, что новое определение им подходит.
- Тесты на все три следствия флага.

### Out of Scope

- Удаление песочницы как механики — TASK-036. Здесь только перестаём считать её
  за настоящую запись.
- `has_upcoming_booking`, `has_confirmed_booking`, `has_completed_booking` — они уже
  определены корректно, не трогаем.
- Изменение самих текстов подсказок.

## Comprehension Tips

### Facts

- Текущий запрос: `SELECT EXISTS(SELECT 1 FROM bookings WHERE trainer_id = :tid)` —
  без единого фильтра (`trainer_onboarding_checklist.py:308-320`). Докстринг файла
  (строка 6) прямо признаёт, что `cancelled`/`declined` включены осознанно: «чтобы
  онбординг не откатывался после отмены».
- Это обоснование верно **только для отмены после того, как запись состоялась в глазах
  тренера**, и неверно для строки, отменённой сразу, и для песочницы.
- `is_sandbox` в UI-хабе мёртв: `hubQuickBookIsSandbox` нигде не присваивается `true`
  (все 20+ упоминаний в `trainer-home-main.js` — чтения и сбросы). Но эндпоинт
  `POST /trainer/clients` с `is_sandbox` жив (`src/api/routes/webapp.py:7283-7295`),
  и у старых тренеров такие строки в БД есть.
- Milestone-логика уже делает правильно: `NOT b.is_sandbox` и
  `status IN ('confirmed','completed')` (`trainer_first_booking_milestone.py:26-40`).

### Implications

⚠️ **Скорректировано в DEC-004 после того, как реализация нашла существующий tested
контракт `activation parity` — читать DEC-004 перед тем, как полагаться на пункты ниже.**

- ~~Определение: `has_any_booking` = существует строка с `NOT is_sandbox` и
  `status NOT IN ('cancelled','declined')`.~~ Неверно: `has_any_booking` остаётся как
  было (nameренно включает sandbox — activation parity, `test_sandbox_isolation.py`).
  Строгое определение получило **новое** имя — `has_real_booking`.
  `trainer_removed` исключается вместе с `cancelled`/`declined` (DEC-003) — это
  удаление клиента тренером, а не состоявшаяся работа.
- «Не откатываться после отмены» сохраняется для нормального случая: запись,
  доведённая до `completed`, останется учтённой в `has_real_booking`, даже если позже
  что-то отменят (через `trainer_profiles.first_booking_milestone_at`, EDGE-001 RESOLVED).
- В сегменте реактивации фильтр обязан совпадать с определением в чеклисте **везде**,
  где оно читается — не только в SQL `_list_segment_candidates`, но и в
  `determine_onboarding_stage`, который читает уже вычисленный флаг отдельным
  параметром. Это расхождение не было предсказано на этапе `/plan` и стоило
  дополнительного цикла отладки на S2 (см. DEC-004).

## Acceptance Criteria

### AC-001
Тренер, у которого единственная запись — песочница (`is_sandbox = true`), имеет
`has_real_booking = false` (см. DEC-004 — не `has_any_booking`, которая осталась
намеренно `true` для песочницы).
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_has_real_booking_false_for_sandbox_only` — зелёный (и явно проверяет,
что `has_any_booking` при этом остаётся `true` — activation parity не сломана)
Verified at: working tree (не закоммичено), 2026-09-02

### AC-002
Тренер, у которого единственная запись отменена (`cancelled` / `declined`), имеет
`has_real_booking = false`.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_has_real_booking_false_for_cancelled_only` +
`test_has_real_booking_false_for_declined_only` — оба зелёные
Verified at: working tree (не закоммичено), 2026-09-02

### AC-003
Такой тренер получает карточку `share_link` в `resolve_trainer_next_step`.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: `test_share_link_card_still_shown_with_only_sandbox_or_cancelled_booking` —
сквозной тест через реальный чеклист, зелёный
Verified at: working tree (не закоммичено), 2026-09-02

### AC-004
Такой тренер остаётся кандидатом серии реактивации и получает следующий неотправленный
шаг D+1/D+3/D+7.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_active_with_only_sandbox_booking_stays_a_candidate` +
`test_active_with_only_cancelled_booking_stays_a_candidate` — оба зелёные (стадия
`STAGE_NO_BOOKING`). Потребовало второй правки сверх плана: `determine_onboarding_stage`
принимал `has_any_booking` отдельным параметром и гасил серию по тому же старому
критерию, что и до задачи — переименован в `has_real_booking`, вызывающая сторона
в `list_onboarding_candidates` тоже (см. DEC-004).
Verified at: working tree (не закоммичено), 2026-09-02

### AC-005
Тренер с одной записью в статусе `confirmed`, которую затем отменили, сохраняет
`has_real_booking = true` — регресса «онбординг вернулся» нет.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_has_real_booking_survives_cancel_after_milestone_claimed` — зелёный
Verified at: working tree (не закоммичено), 2026-09-02

### AC-006
Реферальная подсказка не показывается тренеру, у которого только песочница
или только отменённая запись.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: `test_referral_growth_not_nudged_for_sandbox_only_booking` — сквозной тест
через реальный чеклист, зелёный. `_onboarding_booking_step_done` переведена с
`has_any_booking OR has_confirmed_booking OR has_upcoming_booking` на одно поле
`has_real_booking` (см. DEC-004) — иначе `has_confirmed_booking`/`has_upcoming_booking`
(тоже намеренно не фильтрующие sandbox, той же activation-parity природы) держали
бы подсказку видимой независимо от фикса `has_any_booking`.
Verified at: working tree (не закоммичено), 2026-09-02

### AC-007
Полный прогон pytest не хуже базовой линии на момент старта задачи.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: baseline из TASK-026 (чистый HEAD `eec29cd`, весь working tree застэшен) —
11 failed/1181 passed/5 skipped. С изменениями TASK-027 — 9 failed/1210 passed/6 skipped:
все 9 падений — подмножество тех же 11 базовых (2 из 11 пропали, похоже на флейки по
времени в сортировке «идёт сейчас», к этой задаче не относятся). Ноль новых падений.
Verified at: working tree (не закоммичено), 2026-09-02

## Edge Cases

### EDGE-001
Запись была `completed`, потом переведена в `cancelled` вручную. По AC-005 флаг обязан
остаться `true`. Это значит, что фильтр по текущему статусу недостаточен и нужен либо
учёт истории, либо опора на `first_booking_milestone_at` в `trainer_profiles`
(проставляется один раз и не сбрасывается — см. `trainer_first_booking_milestone.py`).
Severity: HIGH
Status: RESOLVED
Resolution: `sql_trainer_has_real_booking` = milestone OR текущий фильтр — реализовано
в DEC-001/DEC-002 (S1), проверено `test_has_real_booking_survives_cancel_after_milestone_claimed`.
Verification: integration, зелёный, см. AC-005.

### EDGE-002
У существующих тренеров в БД уже стоят флаги-последствия (например, отправленные шаги
серии реактивации). После правки часть тренеров снова станет кандидатами и получит
шаг, который в их случае не отправлялся. Проверить, что «largest unfired» не выстрелит
серией сообщений за один тик.
Severity: MEDIUM
Status: OPEN

### EDGE-003
Тренер центра (`studio_access_mode = admin_only`) получает `has_any_booking = True`
принудительно (`trainer_onboarding_checklist.py:146`). Эта ветка обязана остаться.
Severity: LOW
Status: RESOLVED
Resolution: ветка сохранена и рядом добавлено `out["has_real_booking"] = True` — иначе
после переезда `trainer_next_step.py`/`_onboarding_booking_step_done` на `has_real_booking`
студийный тренер снова увидел бы карточку «отправьте ссылку», которую этот путь обязан
скрывать (карточку студийного тренера публикует не он сам).
Verification: manual review кода (`trainer_onboarding_checklist.py`, ветка `admin_only`);
отдельного теста нет — низкая severity, поведение тривиально по коду.

## Decisions

### DEC-001
Decision: Опорой для «первая запись состоялась» становится
`trainer_profiles.first_booking_milestone_at`, если она проставлена, и запрос с фильтрами
— в остальных случаях.
Reason: Единственный способ выполнить AC-002 и AC-005 одновременно. Milestone уже
проставляется атомарно, один раз и с правильными фильтрами — это готовый «факт истории»,
которого не хватает запросу по текущим статусам.
Alternatives: смотреть только текущие статусы — ломает AC-005; оставить как есть —
оставляет дыру в ведении.

### DEC-002
Decision: Логика выносится в переиспользуемый SQL-фрагмент
`sql_trainer_has_real_booking(*, trainer_alias="t")` в `src/application/trainer_client_invite_tracking.py`
(рядом с `sql_trainer_shared_client_invite` / `sql_trainer_submitted_for_moderation` —
тот же файл и тот же паттерн), а не дублируется в двух местах.
Reason: Ровно об этом предупреждают Implications — «фильтр обязан совпадать в чеклисте
и в сегменте реактивации, иначе тренер выпадет по одному правилу и останется без первой
записи по другому». Общий фрагмент технически исключает расхождение.
Alternatives: два независимых SQL-запроса с одинаковым текстом — отклонено: именно так
получился текущий баг (`has_any_booking` без фильтра и `real_bookings_count` с фильтром
разъехались внутри одного файла).

### DEC-003
Decision: Исключаемые статусы — `('cancelled', 'declined', 'trainer_removed')`, не только
`('cancelled', 'declined')` из черновика Implications.
Reason: `trainer_removed` — уже установленная в кодовой базе конвенция «эта запись не
считается» (5+ мест: `sql_trainer_shared_client_invite`, `care_pulse_use_cases.py`,
`admin_analytics_use_cases.py` ×4). `pending` / `no_show` / `payment_dispute` остаются
внутри "has_any_booking=true" — это реальное взаимодействие с клиентом, даже если оно
сорвалось после факта, и так же вело себя старое (нефильтрованное) определение.

### DEC-004 — существенная коррекция премисы задачи, найдена во время реализации
Decision: `has_any_booking` **не трогается** и остаётся прежним нефильтрованным
определением (включая sandbox и cancelled/declined). Новое, строгое определение
живёт в **отдельном** поле `has_real_booking` (через `sql_trainer_has_real_booking`).
Все потребители, которым в задаче нужен был строгий смысл, переведены на новое поле:
`trainer_next_step.py` (`has_booking`), `trainer_hub_action_inbox.py`
(`_onboarding_booking_step_done` — переписана на одно поле `has_real_booking` вместо
`has_any_booking OR has_confirmed_booking OR has_upcoming_booking`),
`trainer_onboarding_recovery_use_cases.py` (`determine_onboarding_stage`, параметр
переименован из `has_any_booking` в `has_real_booking`; это исправление сверх исходного
плана — см. ниже).

Reason: во время реализации S1 упал `tests/integration/test_sandbox_isolation.py`.
Тест — уже существующий, осознанно написанный регрессионный тест с явным комментарием:
«Sandbox bookings still close the first-booking milestone (activation parity with real
flow)». То есть в продукте **уже есть** намеренное решение: sandbox-запись (флоу
«Попробовать на примере») обязана считаться прогрессом онбординга, иначе демо-флоу
выглядит бессмысленно — тренер попробовал, увидел что работает, а продукт продолжает
говорить «нет записей». Это прямо противоречило первоначальной премисе задачи
(«has_any_booking должна быть false для sandbox-only»), которая была принята при
`/clarify` без обнаружения этого теста. Пользователь подтвердил: разделить понятия,
не убирать activation parity.

Дополнительно обнаружено при этой же правке: `has_confirmed_booking` и
`has_upcoming_booking` в чеклисте **тоже** не фильтруют `is_sandbox` — и это тоже
намеренно (та же activation-parity природа), а не забытый баг, как ошибочно
предполагало Out of Scope этой задачи. Без переноса `_onboarding_booking_step_done`
на одно поле `has_real_booking` (вместо OR трёх старых), AC-006 был бы физически
недостижим: реферальная подсказка продолжала бы показываться для sandbox-only
тренера через `has_confirmed_booking`, даже после починки одной только
`has_any_booking`.

Ещё одно скрытое расхождение нашлось на S2: `determine_onboarding_stage` в
`trainer_onboarding_recovery_use_cases.py` принимал `has_any_booking` отдельным
параметром (не через SQL-фрагмент) и гасил кандидата по старому критерию —
из-за этого AC-004 падал даже после того, как `_list_segment_candidates` уже был
поправлен. Параметр переименован в `has_real_booking`, вызывающая сторона обновлена.

Impact on plan: Technical Plan/Test Strategy ниже описывают версию решения, где
`has_any_booking` заменяется на новое значение «на месте» — это верно для **сути**
(SQL-фрагмент, три места чтения), но не для итогового имени поля и для того, что
`has_any_booking` пришлось откатить обратно, а не заменить. Слайсы S1/S3 в реализации
включали больше правок, чем первоначально оценено (docstring чеклиста, ветка
`admin_only`, два тестовых файла-потребителя, `determine_onboarding_stage`) — story
points не пересчитывались задним числом, см. `/estimate` post-work при желании
сравнить оценку с фактом.

Alternatives: убрать activation parity совсем (сделать `has_any_booking` строгим
везде) — отклонено пользователем: это осознанная отмена существующего, тестируемого
продуктового решения, а не починка бага, и не входит в мандат этой задачи.

## Design Context

Нет UI-поверхности — задача в SQL и в переиспользуемом Python-фрагменте.

## Technical Plan

1. `src/application/trainer_client_invite_tracking.py` — добавить
   `sql_trainer_has_real_booking(*, trainer_alias: str = "t") -> str`, возвращающую
   SQL-булево выражение: `EXISTS(trainer_profiles.first_booking_milestone_at IS NOT NULL)
   OR EXISTS(bookings ... NOT is_sandbox AND status NOT IN (...))` — по образцу
   `sql_trainer_shared_client_invite` в этом же файле.
2. `src/application/trainer_onboarding_checklist.py:308-320` (`has_any_booking`) —
   заменить `SELECT EXISTS(SELECT 1 FROM bookings WHERE trainer_id = :tid)` на запрос,
   использующий тот же фрагмент (f-string с `sql_trainer_has_real_booking(trainer_alias="")`
   адаптированной под `trainer_id = :tid` без алиаса таблицы `trainers`, либо явный
   `WITH t AS (SELECT :tid::int AS id)` — выбрать при реализации то, что не ломает
   параметризацию `:tid`). Обновить докстринг модуля (строка 6) под новое определение.
3. `src/application/trainer_onboarding_recovery_use_cases.py:139-147`
   (`_list_segment_candidates`) — заменить `AND NOT EXISTS (SELECT 1 FROM bookings b
   WHERE b.trainer_id = t.id)` на `AND NOT {sql_trainer_has_real_booking(trainer_alias="t")}`
   — здесь алиас `t` для `trainers` уже есть естественно (JOIN на `t.id`).
4. `trainer_hub_action_inbox.py:96-101` (`_onboarding_booking_step_done`) — ревизия без
   изменения кода: функция читает уже вычисленный `has_any_booking`/`has_confirmed_booking`/
   `has_upcoming_booking` из словаря чеклиста, новое определение `has_any_booking`
   автоматически протекает сюда без правок.

## Test Strategy

- Новый файл `tests/application/test_trainer_has_real_booking.py` (или расширение
  `tests/application/test_trainer_onboarding_catalog_step.py`, если там уже есть
  фикстуры чеклиста) — параметризованные кейсы:
  - только sandbox-бронь → `has_any_booking=False` (AC-001)
  - только `cancelled`/`declined` бронь → `has_any_booking=False` (AC-002)
  - `confirmed`→`cancelled` (была одна реальная, потом отменена) →
    `has_any_booking=True` через milestone (AC-005, EDGE-001)
- `tests/application/test_trainer_next_step.py` — тренер только с sandbox/отменённой
  бронью получает `STEP_SHARE_LINK` (AC-003).
- Новый тест в `tests/application/test_onboarding_reactivation_pure.py` или интеграционный
  рядом с `list_onboarding_candidates` — такой тренер остаётся кандидатом и получает
  следующий неотправленный шаг (AC-004).
- `tests/application/test_trainer_hub_action_inbox.py` — реферальная подсказка не
  показывается такому тренеру (AC-006, через `_should_nudge_catalog_in_hub`/
  `_onboarding_booking_step_done` — уточнить при реализации, какая функция реально
  гейтит рефералку, т.к. Business Context ссылается на `trainer_hub_action_inbox.py:232-252`).
- Полный `pytest` (AC-007).

## Slices

### S1 Общий SQL-фрагмент + чеклист
Goal: `has_any_booking` в чеклисте использует новое определение через общий фрагмент.
Scope: `trainer_client_invite_tracking.py` (новая функция `sql_trainer_has_real_booking`),
`trainer_onboarding_checklist.py:308-320`.
Covers: AC-001, AC-002, AC-005
Verification: `pytest tests/application/test_trainer_has_any_booking.py
tests/application/test_trainer_onboarding_catalog_step.py` — 5+2 passed.
Estimate: 3
Status: DONE

### S2 Серия реактивации использует тот же фрагмент
Goal: тренер с sandbox/отменённой бронью остаётся кандидатом реактивации.
Scope: `trainer_onboarding_recovery_use_cases.py:139-147`.
Depends on: S1 (использует функцию, добавленную там)
Covers: AC-004
Verification: `pytest tests/integration/test_onboarding_reactivation.py` — 13/13 passed
(11 существующих без регресса + 2 новых).
Estimate: 2
Status: DONE

### S3 Следствия: next_step и реферальная подсказка
Goal: `has_real_booking` протекает в оба потребителя корректно.
Scope: `trainer_next_step.py` (переключён на `has_real_booking`),
`trainer_hub_action_inbox.py` (`_onboarding_booking_step_done` переписана на одно поле).
Depends on: S1
Covers: AC-003, AC-006
Verification: `pytest tests/application/test_trainer_has_any_booking.py
tests/application/test_trainer_next_step.py tests/application/test_trainer_hub_action_inbox.py`
— 6+17+20 passed. Потребовало правки кода сверх изначального плана (см. DEC-004) —
Technical Plan п.4 ошибочно предполагал «ревизия без изменений».
Estimate: 2
Status: DONE

### S4 Регресс
Goal: ничего не сломано.
Scope: весь репозиторий.
Depends on: S1, S2, S3
Covers: AC-007
Verification: полный `pytest`, сравнение с базовой линией (тот же метод, что в TASK-026 —
честный `git stash` всего working tree при необходимости переустановить baseline).
Estimate: 1
Status: DONE

## Next Action

Все 7 AC verified. Готово к `/review`.

## Execution History

- **TASK_CREATED** — заведена 2026-09-02 по исследованию `.ai/RESEARCH-ACTIVATION-2026-09-02.md`, §P7.
- **PHASE_STARTED** — 2026-09-02 | clarify
- **PHASE_COMPLETED** — 2026-09-02 | clarify | Все 7 AC уже CONFIRMED, подход зафиксирован в DEC-001 при заведении задачи. Открытых UNKNOWN нет.
- **PHASE_STARTED** — 2026-09-02 | plan
- **PHASE_COMPLETED** — 2026-09-02 | plan | 4 среза; общий SQL-фрагмент `sql_trainer_has_real_booking` (DEC-002) вместо дублирования; исключаемые статусы расширены до `(cancelled, declined, trainer_removed)` по конвенции кодовой базы (DEC-003).
- **PHASE_STARTED** — 2026-09-02 | estimate
- **PHASE_COMPLETED** — 2026-09-02 | estimate | 4 среза, 8 story points (S1=3, S2=2, S3=2, S4=1); все 7 AC покрыты.
- **SLICE_VERIFIED** — 2026-09-02 | S1 (первый проход) | Новая функция `sql_trainer_has_real_booking`; чеклист заменил `has_any_booking` на неё напрямую. 5 новых тестов зелёные. **Позже отменено** — см. следующую запись.
- **REPLAN_REQUIRED → RESOLVED** — 2026-09-02 | Прогон `tests/integration/test_sandbox_isolation.py` (не входил в тесты S1, найден при подготовке S3) упал: тест намеренно проверяет `has_any_booking=true` для sandbox-записи («activation parity»). Премиса задачи («has_any_booking должна стать false для sandbox») конфликтовала с существующим tested-поведением. Вопрос вынесен пользователю через `AskUserQuestion`; выбрано «разделить понятия» — DEC-004.
- **SLICE_VERIFIED (пересмотрено)** — 2026-09-02 | S1 | `has_any_booking` возвращена к исходному нефильтрованному запросу (activation parity сохранена, `test_sandbox_isolation.py` снова зелёный). Новое поле `has_real_booking` добавлено рядом. Docstring модуля и ветка `admin_only` обновлены (EDGE-003 RESOLVED). Тестовый файл переписан под `has_real_booking`. AC-001, AC-002, AC-005 → VERIFIED (уточнённая формулировка, см. DEC-004).
- **SLICE_VERIFIED** — 2026-09-02 | S2 | `_list_segment_candidates` использует `sql_trainer_has_real_booking` вместо нефильтрованного `NOT EXISTS`. При прогоне 2 новых тестов найдено второе расхождение: `determine_onboarding_stage` гасил кандидата по отдельному параметру `has_any_booking` — переименован в `has_real_booking`, вызывающая сторона обновлена (EDGE-001 RESOLVED заодно). 13/13 в файле реактивации, 9/9 в чистой pure-функции. AC-004 → VERIFIED.
- **SLICE_VERIFIED** — 2026-09-02 | S3 | `trainer_next_step.py` и `_onboarding_booking_step_done` переведены на `has_real_booking` (это потребовало правки кода, не только теста — Technical Plan п.4 недооценил объём). 2 новых сквозных теста через реальный чеклист (share_link card, referral hint). Regression-фикс в `_checklist()`-фикстуре (`test_trainer_next_step.py`) и в 4 dict-фикстурах (`test_trainer_hub_action_inbox.py`) — добавлен `has_real_booking` рядом с `has_any_booking` там, где тесты писались до появления этого различия. 43/43 в трёх файлах. AC-003, AC-006 → VERIFIED.
- **SLICE_VERIFIED** — 2026-09-02 | S4 | Baseline честно переустановлен методом TASK-026 (`git stash -u` всего working tree, чистый HEAD `eec29cd`): 11 failed/1181 passed/5 skipped. С изменениями TASK-027: 9 failed/1210 passed/6 skipped — все 9 являются подмножеством исходных 11 (2 пропали, похоже на флейки по времени, не связаны с этой задачей). Ноль новых падений. AC-007 → VERIFIED.
- **REVIEW** — 2026-09-02 | 0 Critical/High, 1 Medium, 1 Low. Medium: JS-зеркало `onboardingBookingStepDone` (`trainer-home-main.js:1268`) не переведено на `has_real_booking` и осталось на старом OR — расхождение с сервером, но безвредное на практике (единственный потребитель дальше гейтится строгим `real_bookings_count>=5`); кандидат для TASK-034 (клиентский движок подсказок целиком под снос). Low: `DEC-002` в плане называет параметр `trainer_alias`, реализация — `trainer_id_expr`; чисто документальная неточность плана, не код.
