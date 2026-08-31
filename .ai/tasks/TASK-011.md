---
task_id: TASK-011
title: Ноль реактивации для тренеров, бросивших онбординг
status: READY
phase: review
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Завести касания для тренеров, которые привязали Telegram и не дошли до конца анкеты. Сейчас этот сегмент не получает ни одного сообщения, пока у него молча не сгорит триал.

## Business Context

Отвал на первом шаге — всегда самая крупная часть воронки. Все существующие циклы уведомлений адресованы активным тренерам, поэтому именно самый жирный сегмент не обрабатывается вообще. Это самая большая дыра воронки и одна из самых дешёвых в починке.

## Scope

### In Scope

- Новый цикл(ы) реактивации для `pending_profile` / `BLOCKED_PROFILE` / `BOOKING_READY`
- Сегментация по тому, где именно тренер застрял (пустая анкета / нет фото / анкета не отправлена / нет записи)
- Частота, тихие часы, стоп-условия и защита от повторов
- Учёт оставшихся дней триала как повода для касания

### Out of Scope

- Care Pulse для активных тренеров — работает, не трогаем
- Клиентские напоминания

## Comprehension Tips

### Facts

- `src/application/care_pulse_use_cases.py:407` — `WHERE t.status = 'active'`. Care Pulse не видит онбордящихся тренеров.
- Дайджесты тоже про активных: `run_daily_morning_digest_loop` / `run_weekly_sunday_digest_loop` (`src/bot/notification_loops.py:2554,2661`), кандидаты через `_list_digest_candidates_for_kind`.
- `run_lead_mode_recovery_loop` (`notification_loops.py:2321`) адресован потере подписки, его запрос требует `t.is_catalog_visible = TRUE` (`src/application/lead_mode_recovery_use_cases.py:114`) — то есть уже активных.
- `run_subscription_expire_and_reminder_loop` (`notification_loops.py:2077`) шлёт про окончание срока, но это уведомление о биллинге, а не про незавершённый онбординг; `subscription_reminder_trial_days_ahead = 1` (`src/shared/config.py:177`) — предупреждение приходит за сутки.
- `run_inactive_client_loop` (`notification_loops.py:1799`) — про клиентов, не про тренеров.
- Полный список циклов — `grep "^async def run_" src/bot/notification_loops.py`; ни одного про незавершённый профиль тренера.
- Данные для сегментации уже готовы: `get_trainer_onboarding_checklist` (`src/application/trainer_onboarding_checklist.py:67`) отдаёт `tt_minimal_complete`, `profile_complete`, `full_profile_complete`, `has_any_booking`, `schedule_unlocked`, `trainer_status`; `moderation_readiness_dict` — конкретные незакрытые поля с русскими лейблами (`missing_labels_ru`).

### Implications

- Инфраструктура готова полностью: есть паттерн цикла, есть чеклист с точной диагностикой застревания, есть тихие часы (`src/shared/notification_hours.py`). Нужен сам цикл и копирайт.
- Сообщение должно быть конкретным («осталось: фотография профиля»), а не общим «вернитесь» — данные для этого уже есть в `missing_labels_ru`.
- Пересекается с TASK-009: если тренер не знает даты окончания триала, напоминание за 1 день — единственный сигнал, и он приходит слишком поздно.

## Acceptance Criteria

### AC-001
Кандидаты цикла: тренеры с `telegram_id IS NOT NULL`, которые ещё не прошли онбординг —
(a) `status IN (pending_profile)`, либо (b) `status = active AND has_any_booking = FALSE`
(активирован, но так и не получил ни одной записи — сегмент BOOKING_READY, Care Pulse его не покрывает).
Включение `pending_contract` / `pending_payment` в сегмент не подтверждено.
Status: INFERRED
Verification: unit-тест на функцию выборки кандидатов с фикстурами тренеров в каждой комбинации статус/чеклист
Result: VERIFIED
Evidence: tests/integration/test_onboarding_reactivation.py — test_fresh_pending_profile_is_candidate_with_empty_form_stage, test_active_with_zero_bookings_is_candidate_with_no_booking_stage, test_active_with_a_booking_is_not_a_candidate, test_no_telegram_id_excluded, test_deactivated_status_excluded — 5/5 PASSED

### AC-002
Сегментация внутри выборки на стадии застревания (пустая анкета / не хватает конкретного поля,
включая фото / анкета готова, но не отправлена на модерацию / профиль активен, но нет записи) —
вычисляется из уже существующих `get_trainer_onboarding_checklist` + `missing_labels_ru`, без новой SQL-логики
диагностики. У каждой стадии — своя русскоязычная копия с конкретным следующим действием.
Status: INFERRED
Verification: unit-тест, сопоставляющий фикстуры чеклиста с ожидаемым id стадии
Result: VERIFIED
Evidence: tests/application/test_onboarding_reactivation_pure.py::TestDetermineOnboardingStage — 8/8 PASSED (все 5 стадий + None-кейсы); подтверждено end-to-end в integration-тестах (empty_form, no_booking)

### AC-003
Частота касаний: фиксированные офсеты от `trainers.created_at` (≈ момент привязки Telegram — см. Risks) —
D+1 / D+3 / D+7. На каждом тике цикла тренеру уходит максимум один шаг; выбирается наибольший
просроченный неотправленный шаг (паттерн `_pick_due_step` из `lead_mode_recovery_use_cases.py`).
Идемпотентность — таблица-лог с UNIQUE(trainer_id, step), шаг никогда не повторяется.
Status: INFERRED
Verification: табличный unit-тест чистой функции выбора шага (аналог `test_lead_mode_recovery_pure.py`)
Result: VERIFIED
Evidence: tests/application/test_onboarding_reactivation_pure.py::TestPickDueStep — 6/6 PASSED; tests/integration/test_onboarding_reactivation.py — test_due_nudge_fires_d1_after_one_day, test_due_nudge_not_yet_at_day_zero, test_after_d1_sent_d3_due_at_3_days, test_mark_nudge_sent_is_idempotent, test_mark_nudge_sent_rejects_unknown_step, test_trainer_progressing_out_of_segment_stops_further_nudges — 6/6 PASSED

### AC-004
Оставшиеся дни триала учитываются в копии: когда `trainer_subscriptions.expires_at` (trial) ближе
порога — сообщение усиливает срочность, не дублируя существующее биллинговое напоминание
(`run_subscription_expire_and_reminder_loop`, `subscription_reminder_trial_days_ahead`).
Status: INFERRED
Verification: unit-тест текста сообщения с фикстурой expires_at внутри/вне порога
Result: VERIFIED
Evidence: test_onboarding_reactivation_pure.py::TestRenderOnboardingNudgeText — 10/10 PASSED (в т.ч.
test_no_trial_suffix_when_above_urgency_threshold, test_trial_suffix_with_days_left_at_threshold,
test_trial_suffix_last_day); порог TRIAL_URGENCY_THRESHOLD_DAYS=3, отдельно от subscription_reminder_trial_days_ahead

### AC-005
Тихие часы (`is_trainer_push_allowed_now`) соблюдаются; тренер перестаёт быть кандидатом сразу,
как только уходит из сегмента (отправил анкету / получил первую запись) — без явной отмены,
по аналогии с Lead Mode recovery.
Status: CONFIRMED
Verification: интеграционный тест — тренер, закрывший нужный шаг, отсутствует в кандидатах следующего тика
Result: VERIFIED
Evidence: стоп-условие — test_trainer_progressing_out_of_segment_stops_further_nudges PASSED (тренер с первой
записью исчезает из compute_due_onboarding_nudges). Тихие часы — is_trainer_push_allowed_now вызывается в
run_onboarding_reactivation_loop на том же месте, что и в уже протестированном run_lead_mode_recovery_loop
(сам хелпер покрыт своими тестами); по конвенции кодовой базы сам while-True цикл (send/mark) отдельным
e2e-тестом не покрывается — совпадает с run_lead_mode_recovery_loop/run_care_pulse_loop (тоже без такого теста)

### AC-006
Новый цикл зарегистрирован в `notification_service.py` рядом с существующими (`run_lead_mode_recovery_loop`,
`run_care_pulse_loop`), с собственным интервалом из конфига; Care Pulse и Lead Mode recovery не изменяются.
Status: CONFIRMED
Verification: цикл добавлен в `asyncio.create_task(...)` в `notification_service.py`; существующие тесты
`test_lead_mode_recovery*` проходят без изменений
Result: VERIFIED
Evidence: notification_service.py:106 — asyncio.create_task(run_onboarding_reactivation_loop(trainer_bot), name="onboarding_reactivation")
рядом с lead_mode_recovery/care_pulse; notification_service.py импортируется без ошибок; test_lead_mode_recovery*
(19 тестов) и test_care_pulse* (24 теста) проходят без изменений; полный сбор тестов (1107 тестов) без ошибок импорта

## Technical Plan

### Approach
Завести отдельный цикл реактивации онбординга по образцу уже работающего Lead Mode recovery
(`lead_mode_recovery_use_cases.py` + `run_lead_mode_recovery_loop`): своя таблица-лог идемпотентности,
чистая функция выбора шага, дневной цикл в `notification_loops.py`. Сегментация стадии застревания
берётся из уже готового `get_trainer_onboarding_checklist` — новой диагностической SQL-логики не нужно.

### Changes
- `src/infrastructure/db/models.py` — таблица `TrainerOnboardingNudge` (зеркало `TrainerRecoveryNudge`),
  константы `ONBOARDING_NUDGE_STEPS_ORDERED` / `_KEYS`.
- Новая Alembic-миграция: `trainer_onboarding_nudges(id, trainer_id FK CASCADE, step, sent_at, created_at_anchor)`,
  UNIQUE(trainer_id, step).
- `src/application/trainer_onboarding_recovery_use_cases.py` (новый) — выборка кандидатов (AC-001),
  определение стадии (AC-002), `_pick_due_step`-аналог (AC-003), `compute_due_onboarding_nudges`,
  `mark_onboarding_nudge_sent` — структура зеркалит `lead_mode_recovery_use_cases.py`.
- `src/bot/notification_loops.py` — `run_onboarding_reactivation_loop(trainer_bot)`, зеркалит
  `run_lead_mode_recovery_loop`; рендер сообщения по стадии.
- `src/bot/messages.py` — русские шаблоны по стадиям + вариант с оставшимися днями триала (AC-004).
- `src/shared/config.py` — `notification_onboarding_reactivation_interval_sec` (аналог
  `notification_lead_mode_recovery_interval_sec`).
- `src/bot/notification_service.py:103` — добавить `asyncio.create_task(run_onboarding_reactivation_loop(trainer_bot), name="onboarding_reactivation")`
  рядом с существующими задачами.

### Data/API
Новая таблица `trainer_onboarding_nudges` — только лог идемпотентности, без новых API-эндпоинтов
(фоновый цикл, как и Lead Mode recovery). Кандидаты собираются через `get_trainer_onboarding_checklist`
по каждому тренеру-кандидату (см. Risks — не bulk-SQL, как у lead_mode_recovery).

### Tests
- `tests/application/test_onboarding_reactivation_pure.py` — табличные тесты выбора шага (AC-003).
- Интеграционный тест выборки кандидатов на фикстурах БД по каждой комбинации статус/чеклист (AC-001, AC-002).
- Интеграционный тест цикла: due → отправлено → залогировано → повторно не due (AC-003, AC-005).
- Тесты рендера сообщений по стадиям + ветка с оставшимися днями триала (AC-002, AC-004).

### Risks
- Отдельный `get_trainer_onboarding_checklist` на кандидата (не bulk-SQL, как у `lead_mode_recovery`) —
  нормально при текущем объёме тренеров, но не масштабируется, если сегмент вырастет на порядки.
- Офсеты D+1/D+3/D+7, границы стадий и порог «дней до конца триала» — не подтверждены владельцем копирайта/продукта,
  вероятно потребуют правки после первого просмотра данных.
- Включение `pending_contract`/`pending_payment` в сегмент не решено — Comprehension Tips описывают только
  анкетный поток; контрактно-платёжные стадии могут требовать отдельной копии или быть вне скоупа.
- Отдельной колонки «момент привязки Telegram» в БД нет; `trainers.created_at` используется как якорь,
  потому что легаси-путь создания тренера без Telegram (`POST /api/trainers`) закрыт флагом
  `legacy_trainers_api_enabled` (выключен в проде) — на практике все тренеры создаются через
  `consume_link_token`, где `created_at` и есть момент привязки. Если легаси-путь снова включат, якорь перестанет быть точным.

## Slices

Текущий срез: 4/4 (все срезы реализованы и verified)

### S1 — Кандидаты и сегментация
Goal: выборка тренеров-кандидатов и определение стадии застревания на существующих данных чеклиста
Scope: `src/infrastructure/db/models.py` (таблица `TrainerOnboardingNudge` + миграция), новый
`src/application/trainer_onboarding_recovery_use_cases.py` (функции выборки кандидатов + сегментации;
без step-picker'а и отправки — это S2)
Covers: AC-001, AC-002
Verification: unit-тест функции выборки кандидатов на фикстурах статус/чеклист (все комбинации из AC-001);
unit-тест сопоставления фикстур чеклиста → id стадии (AC-002)
Estimate: 5
Risk: определение границ сегмента (pending_contract/pending_payment) не подтверждено — реализация по умолчанию
исключает их, риск ревизии после ревью

### S2 — Выбор шага и идемпотентность
Goal: чистая функция выбора наибольшего просроченного шага + запись в лог идемпотентности
Scope: `trainer_onboarding_recovery_use_cases.py` — `_pick_due_step`-аналог, `compute_due_onboarding_nudges`,
`mark_onboarding_nudge_sent`
Depends on: S1
Covers: AC-003
Verification: табличный unit-тест чистой функции выбора шага (дни-с-якоря × уже-отправленные-шаги →
ожидаемый следующий шаг или None), аналог `test_lead_mode_recovery_pure.py`
Estimate: 3

### S3 — Копирайт по стадиям
Goal: русскоязычные шаблоны сообщений на каждую стадию + ветка с оставшимися днями триала
Scope: `src/bot/messages.py` (новые шаблоны), рендер-функция, использующая `missing_labels_ru` +
`trainer_subscriptions.expires_at`
Depends on: S1
Covers: AC-002 (копия), AC-004
Verification: unit-тест рендера сообщения на каждую стадию; unit-тест ветки «дни до конца триала»
с фикстурой expires_at внутри и вне порога
Estimate: 3
Risk: порог «дней до конца триала» и конкретные формулировки не подтверждены — вероятна правка после ревью копии

### S4 — Цикл, тихие часы, wiring
Goal: собрать S1–S3 в рабочий фоновый цикл, зарегистрировать в notification_service, подтвердить
стоп-условия и уважение тихих часов
Scope: `run_onboarding_reactivation_loop` в `src/bot/notification_loops.py`,
`notification_onboarding_reactivation_interval_sec` в `src/shared/config.py`,
регистрация в `src/bot/notification_service.py:103`
Depends on: S2, S3
Covers: AC-005, AC-006
Verification: интеграционный тест — тренер получает due-нудж, залогирован, не due повторно тем же шагом;
тренер, закрывший сегмент (отправил анкету / получил первую запись), исчезает из кандидатов следующего тика;
тик вне `is_trainer_push_allowed_now` не шлёт; существующие `test_lead_mode_recovery*` и Care Pulse тесты
проходят без изменений
Estimate: 5

### Total
16 (5+3+3+5)
Основная неопределённость — не в объёме кода, а в неподтверждённых деталях (границы сегмента,
офсеты каденса, порог триала); переоценка после первого ревью копии/данных вероятна.

Это первичная карта исполнения, не контракт — `/next` может дробить, объединять, переставлять или
переоценивать срезы по ходу работы.

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
- **PHASE_STARTED** | plan
- **PHASE_COMPLETED** | plan
- **PHASE_STARTED** | estimate
- **PHASE_COMPLETED** | estimate
- 2026-08-31 | S1 реализован (модель TrainerOnboardingNudge, миграция 0180, кандидаты+сегментация в trainer_onboarding_recovery_use_cases.py) | AC-001, AC-002 verified — 13 тестов PASSED
- 2026-08-31 | S2 реализован (_pick_due_step, compute_due_onboarding_nudges, mark_onboarding_nudge_sent) | AC-003 verified — 12 тестов PASSED
- 2026-08-31 | S3 реализован (шаблоны в messages.py, _render_onboarding_nudge_text, get_trial_days_remaining) | AC-004 verified — 10 тестов PASSED
- 2026-08-31 | S4 реализован (run_onboarding_reactivation_loop, конфиг, wiring в notification_service.py) | AC-005, AC-006 verified — регрессия исключена (62 теста + полный сбор 1107 тестов без ошибок)
- 2026-08-31 | все 6 AC verified, все 4 среза завершены | готово к /review
- 2026-08-31 | REVIEW | 1 finding (Medium) — missing_labels_ru вычисляется для STAGE_EMPTY_FORM/STAGE_REJECTED_RESUBMIT, но не используется в рендере (generic-текст вместо конкретных полей)
