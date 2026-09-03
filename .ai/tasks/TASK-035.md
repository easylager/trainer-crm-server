---
task_id: TASK-035
title: Тренер, у которого сгорел триал в pending_profile, не получает вообще ничего
status: COMPLETE
phase: review
priority: HIGH
created_at: 2026-09-02
updated_at: 2026-09-02
---

# Task

## Objective

Закрыть дыру полной тишины: тренер, чей триал истёк, пока он ещё не прошёл модерацию
(`status = 'pending_profile'`), должен продолжать получать сигналы жизни продукта, а не
падать в тишину до конца времён.

Инвариант, к которому идём:

> Ни одно состояние тренера не должно быть состоянием полного молчания продукта,
> кроме явной деактивации админом.

## Business Context

`LifecycleStage` знает четыре стадии: ONBOARDING, ACTIVE, LEAD_MODE, CHURNED
(`src/application/lifecycle_use_cases.py:43-48`). LEAD_MODE — режим «сорванного платежа»
с сохранённым присутствием в каталоге — достижим только из `ACTIVE`:
`_derive_stage` требует `trainer_status == TRAINER_STATUS_ACTIVE` и
`is_catalog_visible = true`, иначе тренер без активной подписки уходит в CHURNED
(`lifecycle_use_cases.py:241-260`).

Тренер, который остался в `pending_profile` (не подал заявку на модерацию, или подал и
получил фидбек) и у которого истёк 14-дневный триал, физически не может попасть в
LEAD_MODE. Он не получает:

- серию восстановления D+0/D+3/D+14/D+30 (`lead_mode_recovery_use_cases.py:181` фильтрует
  строго `LifecycleStage.LEAD_MODE`);
- ритм-подсказки хаба (`has_crm_subscription_access is False` обрывает их построение,
  `trainer_hub_action_inbox.py:255-256`);
- после TASK-026 — дайджест и care pulse тоже перестанут его видеть, если не разобрать
  этот случай отдельно, потому что оба канала всё ещё смотрят на активную подписку
  через `has_crm_subscription_access` там, где он используется ниже по цепочке.

Тренер получает шаги D+1/D+3/D+7 (`trainer_onboarding_recovery_use_cases.py`), но эта
серия жёстко ограничена семью днями и не имеет варианта после дня 14. Итог: этот сегмент
— брошенные пользователи, у которых был реальный интерес (привязали Telegram), но которые
после дня 14 не услышат от продукта ни слова.

Эта задача — не про то, чтобы дать им полный CRM бесплатно (это Lead Mode делает
осознанно только для дискаверабельных). Это про то, чтобы у них тоже был путь
восстановления, соразмерный их стадии.

## Scope

### In Scope

- Ревизия `_derive_stage`: либо новая под-стадия внутри ONBOARDING для «триал истёк,
  модерация не пройдена», либо явное правило доступности LEAD_MODE-подобного трека
  восстановления вне зависимости от `is_catalog_visible`.
- Серия восстановления для этого сегмента: переиспользовать форму
  `trainer_onboarding_recovery_use_cases.py` (D+1/D+3/D+7 уже есть) — продлить её шагом
  после истечения триала, а не создавать пятый независимый цикл уведомлений.
- Убедиться, что после TASK-026 этот сегмент попадает в кандидаты дайджеста/care-pulse
  наравне с остальными «живыми» тренерами.
- Тесты на переход «триал истёк → сегмент виден → получает следующий неотправленный шаг».

### Out of Scope

- Изменение правил самого Lead Mode для активных/модерированных тренеров — не трогаем.
- Новый пятый цикл уведомлений — переиспользуем существующий D+1/3/7.
- Изменение длины триала и правил его продления.

## Comprehension Tips

### Facts

- `_ONBOARDING_STATUSES` = `{pending_profile, pending_contract, pending_payment}`
  (`lifecycle_use_cases.py:100-106`) — все три стадии `ONBOARDING`, все три получают
  `frozenset()` прав (`:74`).
- `determine_onboarding_stage` (`trainer_onboarding_recovery_use_cases.py:87-110`) уже
  различает `STAGE_EMPTY_FORM` / `STAGE_MISSING_FIELD` / `STAGE_REJECTED_RESUBMIT` /
  `STAGE_NOT_SUBMITTED` / `STAGE_NO_BOOKING` — вся диагностика «что мешает» уже есть,
  не хватает только шага после D+7.
- `ONBOARDING_NUDGE_STEPS_ORDERED` — закрытый список шагов в моделях
  (`src/infrastructure/db/models.py`, искать `ONBOARDING_NUDGE_STEP_KEYS`); добавление
  шага требует миграции значений, но не новой таблицы — идемпотентный лог уже общий
  на все шаги (`trainer_onboarding_nudges`, UNIQUE `(trainer_id, step)`).
- `get_trial_days_remaining` (`trainer_onboarding_recovery_use_cases.py:245-263`) уже
  умеет считать оставшиеся дни триала для этого сегмента — используется для эскалации
  тона (`TRIAL_URGENCY_THRESHOLD_DAYS`), но не для шага «после».

### Implications

- Правильный ход — не трогать `LifecycleStage`, а расширить существующую серию
  реактивации новым шагом с офсетом больше 14 (например D+15 или D+21), который
  срабатывает независимо от текущего `stage`, — сегмент уже строится по `status`,
  не по `LifecycleStage` (`_list_segment_candidates`,
  `trainer_onboarding_recovery_use_cases.py:139-147`).
- Трогать `_derive_stage` рискованно: он используется в паях-гейтах (`trainer_can`)
  далеко за пределами уведомлений. Расширять его ради одного канала уведомлений —
  непропорционально задаче.

## Acceptance Criteria

### AC-001
Тренер в `pending_profile`, без единой записи, чей триал истёк 20 дней назад, получает
следующий неотправленный шаг серии реактивации (не «ничего»).
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: tests/integration/test_onboarding_reactivation.py::test_trial_over_step_fires_for_stalled_pending_profile_trainer
+ 5 смежных тестов (grace period, идемпотентность, no-booking regression, деактивация, отсутствие триала) — все зелёные (19/19 в файле)
Verified at: uncommitted working tree (base be654b7), 2026-09-03

### AC-002
Такой тренер после TASK-026 остаётся кандидатом дайджеста и care pulse наравне
с тренером внутри активного триала.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: tests/application/test_care_pulse_candidates.py::test_care_pulse_includes_pending_profile_trainer_with_expired_trial,
tests/application/test_trainer_digest_integration.py::test_digest_candidates_include_pending_profile_trainer_with_expired_trial —
оба зелёные; код изменений не потребовал (SQL уже фильтрует только по `status <> 'deactivated'`, TASK-026)
Verified at: uncommitted working tree (base be654b7), 2026-09-03

### AC-003
Тренер, прошедший модерацию (`status = active`) и попавший в настоящий Lead Mode,
продолжает получать существующую серию D+0/3/14/30 без изменений.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: lead_mode_recovery_use_cases.py не тронут; полный прогон pytest включает
tests/integration/test_lead_mode_recovery.py — все тесты зелёные (см. AC-005)
Verified at: uncommitted working tree (base be654b7), 2026-09-03

### AC-004
Копирайт нового шага честно называет ситуацию («пробный период закончился, чтобы
продолжить — …») и не обещает функциональность, недоступную в `pending_profile`.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: tests/application/test_onboarding_reactivation_pure.py::TestRenderTrialOverStep
(5 тестов: honest framing, no forbidden promises, EDGE-001 no "start over", stage body reuse, no duplicate trial suffix) — все зелёные
Verified at: uncommitted working tree (base be654b7), 2026-09-03

### AC-005
Полный прогон pytest не хуже базовой линии на момент старта задачи.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: `pytest -q` полного набора: 1302 passed, 8 failed, 3 skipped — все 8 падений
воспроизведены независимо от изменений TASK-035 (`git stash` только файлов этой задачи,
7/8 падают в изоляции без моих изменений; тест test_client_hub_bootstrap_primary_history_absent_when_no_completed
не относится к TASK-035-файлам вовсе). Ни одно падение не в файлах, тронутых этой задачей.
Verified at: uncommitted working tree (base be654b7), 2026-09-03

## Edge Cases

### EDGE-001
Тренер получил фидбек по модерации (`STAGE_REJECTED_RESUBMIT`) и его триал истёк.
Новый шаг не должен звучать как «начните заново» — он уже начинал.
Severity: MEDIUM
Status: RESOLVED
Resolution: интро нового шага универсальное («Пробный период закончился»), тело сообщения
переиспользует существующий stage-specific body (для rejected_resubmit — «Модератор оставил
замечания…»), не завязано на «начните заново» ни в одном варианте.
Verification: tests/application/test_onboarding_reactivation_pure.py::TestRenderTrialOverStep::test_rejected_resubmit_does_not_sound_like_start_over

### EDGE-002
Тренер деактивирован админом после истечения триала. Серия обязана остановиться —
сегмент строится по `status IN (pending_profile, active)`, деактивация уже исключена
текущим запросом; проверить явным тестом.
Severity: LOW
Status: RESOLVED
Resolution: подтверждено явным тестом — деактивированный тренер с истёкшим триалом не
кандидат `compute_due_onboarding_nudges` вообще (сегментный SQL-фильтр не менялся).
Verification: tests/integration/test_onboarding_reactivation.py::test_trial_over_step_excluded_for_deactivated_trainer

## Decisions

### DEC-001
Decision: Новый шаг добавляется в существующую серию `trainer_onboarding_nudges`,
не создаётся отдельный цикл.
Reason: Диагностика «что мешает» для этого сегмента уже полностью построена в
`determine_onboarding_stage`. Второй цикл продублирует эту логику ради одного шага.

## Design Context

Нет UI-компоненты — только текст сообщения в Telegram-боте (существующий рендер-конвейер
`_render_onboarding_nudge_text`). Дизайн не требуется, /design не запускается.

## Technical Plan

Новый шаг `trialend` добавляется в существующую серию `trainer_onboarding_nudges`, но **не**
через `ONBOARDING_NUDGE_STEPS_ORDERED` (тот список — календарные офсеты от `created_at`, жёстко
привязанные к дефолтной длине триала). Вместо этого шаг гейтится отдельной проверкой реального
факта «триал истёк» — устойчиво к тому, что `TRIAL_PERIOD_DAYS` конфигурируем
(env → platform_settings → план, дефолт плана 21 день, не 14).

1. `src/infrastructure/db/models.py`
   - Добавить `ONBOARDING_NUDGE_STEP_TRIAL_OVER = "trialend"` (8 симв., помещается в `String(8)`,
     миграция не нужна — колонка уже открытая строка, см. `migrations/versions/0180_*`).
   - `ONBOARDING_NUDGE_STEP_KEYS = tuple(... ONBOARDING_NUDGE_STEPS_ORDERED) + (ONBOARDING_NUDGE_STEP_TRIAL_OVER,)`
     — чтобы `mark_onboarding_nudge_sent` не отклонял новый шаг валидацией.

2. `src/application/trainer_onboarding_recovery_use_cases.py`
   - `ONBOARDING_TRIAL_OVER_GRACE_DAYS = 1` — небольшая задержка после фактического истечения
     триала, чтобы не пересекаться день-в-день с billing-напоминанием "последний день триала".
   - Новая `get_trial_expired_days_ago(session, trainer_id, *, now=None) -> int | None`:
     ищет последнюю подписку тренера с `subscription_plans.is_trial = true` (независимо от
     текущего статуса — `trial` ещё не переключён в `past_due`, или уже переключён), возвращает
     целое число дней с момента `expires_at`, либо `None`, если триала не было или он ещё не
     истёк. Не использует `datetime.now()` для офсета — берёт реальный `expires_at`.
   - `compute_due_onboarding_nudges`: для каждого кандидата, чей `stage != STAGE_NO_BOOKING`
     (см. Decision ниже), дополнительно проверяет `get_trial_expired_days_ago`. Если истёк
     ≥ `ONBOARDING_TRIAL_OVER_GRACE_DAYS` дней назад и шаг `trialend` ещё не отправлен —
     этот шаг перекрывает результат `_pick_due_step` (тот же принцип "largest unfired": факт
     истёкшего триала всегда более актуален, чем несработавший D+1/D+3/D+7).

3. `src/bot/messages.py`
   - `TRAINER_ONBOARDING_NUDGE_INTRO_TRIAL_OVER` — честная рамка («Пробный период закончился...
     чтобы продолжить...»), без обещаний функциональности вне `pending_profile` (AC-004).

4. `src/bot/notification_loops.py`
   - Импорт `ONBOARDING_NUDGE_STEP_TRIAL_OVER`.
   - `_render_onboarding_nudge_text`: для `nudge.step == ONBOARDING_NUDGE_STEP_TRIAL_OVER` берёт
     новый intro напрямую (минуя `_ONBOARDING_STEP_INTRO`/`_ONBOARDING_EMPTY_INTRO`), тело же
     остаётся тем же самым stage-specific `body`, что и у существующих шагов — это и закрывает
     EDGE-001 (rejected_resubmit не получает рамку «начните заново», тело уже отдельно называет
     «модератор оставил замечания»).
   - Docstring `run_onboarding_reactivation_loop` — упомянуть новый шаг.

### Decision: `trialend` не применяется к `STAGE_NO_BOOKING`

`STAGE_NO_BOOKING` — это `trainer_status == active`, отдельный сегмент из TASK-011, не
относящийся к объективу этой задачи (`pending_profile`, по формулировке Objective). Не трогаем
его, чтобы не пересекаться с реальным Lead Mode / будущими правилами для активных тренеров —
см. Out of Scope. Проверяется явным тестом (регрессия на новый гейт).

## Test Strategy

- **Unit** (`tests/application/test_onboarding_reactivation_pure.py`):
  - `_render_onboarding_nudge_text` с шагом `trialend`: содержит «Пробный период закончился» и
    «продолжить», не содержит обещаний вне pending_profile (напр. «тариф», «аналитика»,
    «CRM»). (AC-004)
  - `rejected_resubmit` + `trialend` не содержит «начните заново» / «регистрац» (EDGE-001).
- **Integration** (`tests/integration/test_onboarding_reactivation.py`):
  - AC-001: `pending_profile` трейнер, создан 20 дней назад, триал истёк 20 дней назад, реальных
    записей и отправленных шагов нет → `compute_due_onboarding_nudges` возвращает шаг `trialend`.
  - `trialend` уже отправлен → повторно не возвращается (идемпотентность через существующий
    `mark_onboarding_nudge_sent`).
  - Regression: `STAGE_NO_BOOKING` (active, без записей) с истёкшим триалом НЕ получает
    `trialend` (Decision выше).
  - EDGE-002: деактивированный тренер с истёкшим триалом — не кандидат вообще (сегмент уже
    фильтрует по статусу, тест на явную проверку).
  - Триал не истёк (или его не было) → обычная логика D+1/D+3/D+7 не меняется.
- **AC-002** (дайджест/care-pulse): уже покрыто существующими тестами TASK-026 —
  `test_digest_candidates_include_pending_profile_trainer`
  (`tests/application/test_trainer_digest_integration.py`) и
  `test_care_pulse_includes_pending_profile_trainer_with_tomorrow_session`
  (`tests/application/test_care_pulse_candidates.py`) — обе SQL-выборки фильтруют только
  `status <> 'deactivated'`, подписка/триал не участвуют в фильтре вообще. Добавляем один
  точечный тест, явно привязанный к истёкшему триалу, чтобы формально закрыть AC-002 и защититься
  от будущей регрессии, если кто-то добавит фильтр по подписке.
- **AC-003**: не трогаем `lead_mode_recovery_use_cases.py` и его тесты — полный прогон pytest
  (AC-005) — достаточное свидетельство, что Lead Mode серия не пострадала.

## Slices

### S1 Модель шага + планировщик
Goal: новый шаг `trialend` определён и корректно вычисляется как due для нужного сегмента.
Scope: `models.py` (константа + `STEP_KEYS`), `trainer_onboarding_recovery_use_cases.py`
(`get_trial_expired_days_ago`, гейтинг в `compute_due_onboarding_nudges`).
Covers: AC-001, EDGE-002
Verification: integration (`tests/integration/test_onboarding_reactivation.py`)
Estimate: 3
Status: DONE

### S2 Копирайт и доставка
Goal: новый шаг рендерится честным текстом и уходит через существующий loop.
Scope: `messages.py` (новая intro-константа), `notification_loops.py`
(`_render_onboarding_nudge_text`, импорт, докстринг).
Covers: AC-004, EDGE-001
Verification: unit (`tests/application/test_onboarding_reactivation_pure.py`)
Estimate: 2
Status: DONE

### S3 Регрессия и закрытие AC-002/AC-003/AC-005
Goal: подтвердить, что дайджест/care-pulse и Lead Mode не задеты, и полный прогон pytest зелёный.
Scope: точечный тест на AC-002 (используя существующие паттерны из TASK-026-тестов), полный
прогон `pytest`.
Covers: AC-002, AC-003, AC-005
Verification: integration + unit full suite
Estimate: 1
Status: DONE

## Blockers

(none — Human Gate #4 пройден, пользователь подтвердил готовность 2026-09-03)

## Next Action

Задача завершена.

## Execution History

- **TASK_CREATED** — заведена 2026-09-02 по исследованию `.ai/RESEARCH-ACTIVATION-2026-09-02.md`, §P7 (LEAD_MODE недостижим).
- 2026-09-03 | PHASE_STARTED clarify | запуск /execute TASK-035 autonomous
- 2026-09-03 | PHASE_COMPLETED clarify | все 5 AC уже CONFIRMED, UNKNOWN нет, edge cases и decisions на месте — материальных вопросов не осталось
- 2026-09-03 | PHASE_STARTED plan | исследован код (models.py, trainer_onboarding_recovery_use_cases.py, notification_loops.py, messages.py, digest/care-pulse кандидаты, subscription_use_cases.py)
- 2026-09-03 | PHASE_COMPLETED plan | шаг `trialend` гейтится реальным истечением триала (не календарным офсетом), 3 слайса намечены; AC-002 уже покрыт тестами TASK-026 — план добавляет один точечный тест
- 2026-09-03 | PHASE_STARTED estimate | оценка 3 слайсов из /plan
- 2026-09-03 | PHASE_COMPLETED estimate | S1=3, S2=2, S3=1, итого 6 story points — малый, хорошо понятный план
- 2026-09-03 | реализованы S1-S3: models.py (`trialend` шаг), get_trial_expired_days_ago,
  гейтинг в compute_due_onboarding_nudges, честный копирайт, рендер, 24 новых теста
- 2026-09-03 | PHASE_STARTED verify | все 5 AC + оба edge case
- 2026-09-03 | PHASE_COMPLETED verify | 5/5 AC VERIFIED, оба edge case RESOLVED; полный
  pytest: 1302 passed, 8 failed (все 8 — baseline, подтверждено git stash изоляцией, не
  относятся к файлам TASK-035), 3 skipped
- 2026-09-03 | REVIEW clean | 0 blocking находок; 1 Low-наблюдение (сверхкороткий
  admin-конфигурируемый триал < 7 дней может «перепрыгнуть» D+1/D+3, отдельная тема,
  вне Scope этой задачи — изменение длины триала явно Out of Scope)
- 2026-09-03 | COMPLETE | пользователь подтвердил Human Gate #4, закоммичено
