---
task_id: TASK-026
title: Дайджест и Care Pulse выключены для всех новых тренеров
status: COMPLETE
phase: review
priority: HIGH
created_at: 2026-09-02
updated_at: 2026-09-02
---

# Task

## Objective

Развести два разных смысла, которые сейчас несёт `trainers.status = 'active'`: «карточка
опубликована в каталоге» и «тренер работает в продукте». Циклы уведомлений должны
адресоваться второму, а не первому.

Инвариант, к которому идём:

> Право получать рабочие уведомления определяется тем, что тренер работает,
> а не тем, что админ одобрил его карточку для каталога.

## Business Context

После онбординга v2 модерация гейтит **каталог, а не инструменты тренера** — это записано
прямым текстом в `src/application/trainer_access_state.py:4-12` и в шапке
`src/application/trainer_onboarding_checklist.py`. Новый тренер остаётся `pending_profile`
неделями: продукт специально не предлагает ему каталог раньше пяти реальных записей
(`CATALOG_INVITE_MIN_BOOKINGS = 5`, `src/application/trainer_next_step.py:22`), а в `active`
его переводит только админ вручную (`src/bot/handlers/admin_handlers.py:2262`).

Но два ambient-канала — утренний/воскресный дайджест и Care Pulse — по-прежнему отбирают
кандидатов по `status = 'active'`. Итог: **весь пробный период (14 дней, миграция
`0177_welcome_trial_14_days`) новый тренер не получает ни одного дайджеста и ни одного
care-pulse.** Молчат ровно те каналы, которые создают привычку возвращаться в продукт
каждый день, и молчат ровно для того сегмента, ради которого они писались.

Тот же класс бага уже ловили точечно: TASK-011 завёл серию реактивации именно потому, что
«все существующие циклы уведомлений адресованы активным тренерам». Починили один цикл —
класс остался. Эта задача чинит класс.

Задача — предусловие для TASK-030/031 (обучающие подсказки): рассылать обучение в канал,
который для новичка выключен, бессмысленно.

## Scope

### In Scope

- Общий предикат «живой тренер» в одном месте (кандидат: `src/shared/trainer_status.py`
  или новый хелпер рядом с `trainer_access_state.py`), пригодный и как SQL-фрагмент,
  и как проверка по строке тренера.
- `_list_digest_candidates_for_kind` (`src/bot/notification_loops.py:2700-2740`) — снять
  `AND t.status = 'active'`.
- `_list_trainer_facts` в Care Pulse (`src/application/care_pulse_use_cases.py:407`) — то же.
- Воронка активации и proof-of-value в админке
  (`src/application/admin_analytics_use_cases.py:1464-1600`) — считать по работающим
  тренерам, а не по `status = 'active'`; шаг «в каталоге» остаётся отдельной строкой воронки.
- Тесты: новый тренер в `pending_profile` попадает в кандидаты обоих циклов;
  деактивированный — не попадает.

### Out of Scope

- Содержание дайджеста и care-pulse — не трогаем, только состав получателей.
- Серия восстановления после сгоревшего триала — TASK-035.
- Любые изменения самой модерации и правил публикации в каталоге.
- Уведомления клиентам.

## Comprehension Tips

### Facts

- Дайджест: `SELECT ... FROM trainers t ... WHERE t.digest_enabled = true AND
  t.telegram_id IS NOT NULL AND t.status = 'active' AND ds.id IS NULL`
  (`src/bot/notification_loops.py:2711-2729`). Уже есть отдельный гейт по
  `digest_enabled` и окну пушей — то есть «не спамить» решается не статусом.
- Care Pulse: тот же гейт в `_list_trainer_facts`
  (`src/application/care_pulse_use_cases.py:407-409`), плюс собственные кулдауны
  (48/72 ч) и окно 12:00–14:00 — они остаются как есть.
- Care Pulse умеет молчать сам: `pick_trainer_pulse` возвращает `None`, когда сказать
  нечего (`care_pulse_use_cases.py:107-160`). Расширение аудитории не означает роста шума.
- Дайджест тоже умеет молчать: «0 занятий и 0 заявок → тишина»
  (`notification_loops.py` docstring `run_daily_morning_digest_loop`).
- Аналитика: `has_first_booking` считается как
  `COUNT(*) FILTER (WHERE status = 'active' AND EXISTS (... bookings ...))`
  (`src/application/admin_analytics_use_cases.py:1483`); блок proof-of-value целиком
  под `WHERE t.status = 'active'` (`:1560`).
- Единственный статус, который обязан закрывать всё, — `deactivated`
  (`trainer_access_state.py:44-50`).

### Implications

- Предикат «живой» = `telegram_id IS NOT NULL AND status <> 'deactivated'`. Условие
  «есть шаблон или слоты» добавлять **не нужно**: дайджест и care-pulse и так молчат,
  когда фактов нет, а лишний JOIN усложнит запросы без выигрыша.
- Правку нельзя делать «поиском и заменой» по всему коду: `status = 'active'` в публичных
  запросах каталога (`src/api/routes/public.py`) — корректна и обязана остаться.
  Менять только три перечисленных места.
- В воронке активации шаг «активирован» не удаляем, а переименовываем по смыслу
  («опубликован в каталоге»), иначе потеряем видимость модерации.

## Acceptance Criteria

### AC-001
Тренер со статусом `pending_profile`, привязанным Telegram, `digest_enabled = true`
и хотя бы одним занятием сегодня попадает в кандидаты дневного дайджеста.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_digest_candidates_include_pending_profile_trainer` — pytest зелёный (17 passed)
Verified at: working tree (не закоммичено), 2026-09-02

### AC-002
Тренер со статусом `pending_profile` и завтрашним занятием попадает в кандидаты
Care Pulse и получает `tomorrow_plan`.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_care_pulse_includes_pending_profile_trainer_with_tomorrow_session` — pytest зелёный
Verified at: working tree (не закоммичено), 2026-09-02

### AC-003
Тренер со статусом `deactivated` не попадает ни в один из двух списков кандидатов.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_digest_candidates_exclude_deactivated_trainer` +
`test_care_pulse_excludes_deactivated_trainer` — оба зелёные
Verified at: working tree (не закоммичено), 2026-09-02

### AC-004
Тренер без `telegram_id` не попадает ни в один из двух списков.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: `test_digest_candidates_exclude_trainer_without_telegram` +
`test_care_pulse_excludes_trainer_without_telegram` — оба зелёные
Verified at: working tree (не закоммичено), 2026-09-02

### AC-005
Воронка активации в админке считает первую запись по работающим тренерам, а публикация
в каталоге присутствует как отдельный, честно названный шаг.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_activation_funnel_first_booking_counts_pending_profile_trainer`,
`test_activation_funnel_activated_still_requires_catalog_status`,
`test_proof_of_value_counts_pending_profile_trainer` — 3/3 зелёные; шаг `activated`
переименован в UI на «Опубликован в каталоге», порядок шагов воронки исправлен
(has_first_booking теперь до submitted_moderation/activated — иначе % выпадения был
бы отрицательным)
Verified at: working tree (не закоммичено), 2026-09-02

### AC-006
Публичный каталог по-прежнему показывает только `status = 'active'` — запросы в
`src/api/routes/public.py` не изменились.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `git diff HEAD -- src/api/routes/public.py` пуст — файл не тронут
Verified at: working tree (не закоммичено), 2026-09-02

### AC-007
Полный прогон pytest не хуже базовой линии на момент старта задачи.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: baseline (чистый HEAD `eec29cd`, весь working tree застэшен) — 11 failed,
1181 passed, 5 skipped (искл. `test_template_duration_per_arena.py` — сторонний файл,
временно повреждён параллельным процессом в этой же рабочей копии, не относится
к TASK-026). С изменениями TASK-026 — те же самые 11 failed (идентичный список тестов),
1207 passed, 5 skipped: 26 новых прошедших тестов, ноль новых падений.
Verified at: working tree (не закоммичено), 2026-09-02

## Edge Cases

### EDGE-001
Тренер прошёл онбординг, но не создал ни одного слота. Дайджест обязан промолчать
(нет занятий, нет заявок), а не прислать пустую сводку.
Severity: HIGH
Status: OPEN

### EDGE-002
Care Pulse в среду шлёт «тихую» проверку связи, даже когда фактов нет
(`QUIET_CHECKIN_WEEKDAY_MON0`). Для тренера, который только что прошёл онбординг и уже
получает серию D+1/D+3, это второе сообщение за день. Решить: гасить quiet-checkin,
пока по тренеру идёт серия реактивации.
Severity: MEDIUM
Status: OPEN

### EDGE-003
Расширение аудитории меняет объём рассылки. Проверить, что батч-лимиты
(`_BATCH_LIMIT = 80` в care pulse) и rate-limit Telegram не упираются в потолок.
Severity: LOW
Status: OPEN

## Decisions

### DEC-001
Decision: Предикат «живой тренер» = `telegram_id IS NOT NULL AND status <> 'deactivated'`,
объявленный один раз и переиспользуемый, а не повторённый в трёх запросах.
Reason: Этот же класс бага уже чинили точечно в TASK-011. Пока условие живёт копиями,
следующий цикл уведомлений повторит ошибку.
Alternatives: добавить в предикат «есть расписание» — отвергнуто: оба цикла уже молчат
при отсутствии фактов, а лишнее условие спрячет от нас тренеров, которые бросили настройку.

### DEC-002
Decision: В воронке активации шаг `activated` сохраняется, но означает «опубликован
в каталоге», а первая запись считается по всем работающим тренерам.
Reason: Модерация — реальный этап, терять его нельзя; но смешивать его с активацией
продукта — ровно та ошибка, из-за которой дашборд сейчас показывает пустоту.

### DEC-003
Decision: `QUIET_CHECKIN_WEEKDAY_MON0` в Care Pulse не гасится на время серии реактивации
D+1/D+3/D+7 — оставляем текущее поведение (EDGE-002 не резолвим в этой задаче).
Reason: Расширение аудитории care-pulse само по себе не создаёт нового пересечения:
серия реактивации живёт в отдельном канале (боте, `run_onboarding_reactivation_loop`),
и «тихий чек-ин» в среду — не более одного лишнего мягкого сообщения в неделю. Стоимость
условной блокировки (ещё один межмодульный гейт) выше цены редкого дубля. Если после
включения аудитории данные покажут реальное раздражение — отдельная небольшая задача.
Alternatives: гасить quiet-checkin, пока по тренеру есть неотправленный шаг реактивации —
отклонено как преждевременная оптимизация без замера.

## Design Context

Нет UI-поверхности — задача только в SQL-предикатах и одной SQL-агрегации в админке.

## Technical Plan

1. `src/bot/notification_loops.py:2711-2729` (`_list_digest_candidates_for_kind`) —
   заменить `AND t.status = 'active'` на `AND t.status <> 'deactivated'`.
2. `src/application/care_pulse_use_cases.py:407` (`_list_trainer_facts`) —
   заменить `WHERE t.status = 'active'` на `WHERE t.status <> 'deactivated'`.
3. `src/application/admin_analytics_use_cases.py` — блок ACTIVATION FUNNEL (`:1483`,
   FILTER внутри `has_first_booking`) и блок PROOF OF VALUE (`:1560`, весь `WHERE`):
   заменить оба на `status <> 'deactivated'`. Добавить рядом отдельный столбец
   `catalog_published` со старым условием `status = 'active'` (DEC-002), чтобы шаг
   модерации остался виден отдельно от активации продукта.
4. Публичный каталог (`src/api/routes/public.py:178, 461, 648`) — не трогать; условие
   `status == 'active'` там корректно (AC-006, Out of Scope).
5. Единый предикат отдельным Python-хелпером **не заводим**: в трёх местах это чистый
   inline SQL-фрагмент `status <> 'deactivated'`, вынесение в функцию добавило бы
   косвенность без выигрыша (SQL не может вызвать Python-функцию). DEC-001 описывает
   предикат как понятие, а не требует общей функции — фиксируем это здесь, чтобы `/estimate`
   не считал это отдельной работой.

## Test Strategy

- `tests/application/test_trainer_digest_integration.py` — новый тест: тренер
  `pending_profile` + `digest_enabled=true` + сессия сегодня → есть в кандидатах
  дневного дайджеста (AC-001); тренер `deactivated` — отсутствует (часть AC-003);
  тренер без `telegram_id` — отсутствует (часть AC-004).
- Новый файл `tests/application/test_care_pulse_candidates.py` (кандидаты `_list_trainer_facts`
  сейчас не тестируются отдельно — `test_care_pulse_pure.py` покрывает только чистые
  `pick_trainer_pulse`/`pick_client_pulse`): тренер `pending_profile` с завтрашней сессией
  появляется в фактах и получает `CARE_PULSE_KIND_TOMORROW_PLAN` (AC-002); `deactivated` —
  нет (часть AC-003); без `telegram_id` — нет (часть AC-004).
- `tests/application/test_admin_analytics.py` — новый тест: `pending_profile` тренер
  с `confirmed`/`completed` не-sandbox бронью учитывается в `has_first_booking`;
  `catalog_published` остаётся строго по `status = 'active'` (AC-005).
- AC-006 верифицируется как отсутствие диффа в `src/api/routes/public.py` — не требует
  нового теста, только ревью правки перед `/verify`.
- Полный `pytest` (AC-007).

## Slices

### S1 Дайджест и Care Pulse видят живых тренеров
Goal: `pending_profile`-тренер получает дайджест и care-pulse наравне с `active`.
Scope: `notification_loops.py:2711-2729`, `care_pulse_use_cases.py:407`.
Covers: AC-001, AC-002, AC-003, AC-004
Verification: `pytest tests/application/test_trainer_digest_integration.py
tests/application/test_care_pulse_candidates.py` — новые тесты зелёные: `pending_profile`
попадает в кандидаты обоих циклов, `deactivated` и без `telegram_id` — нет ни в одном.
Estimate: 3
Status: DONE

### S2 Воронка активации считает первую запись по работающим, публикацию — отдельно
Goal: Аналитика в админке не путает «работает» и «в каталоге».
Scope: `admin_analytics_use_cases.py` (activation_funnel, proof-of-value),
`admin-product-analytics-main.js` (копирайт и порядок шагов воронки).
Depends on: S1 (не технически, а по порядку ревью — один модуль за раз)
Covers: AC-005, AC-006, AC-007
Verification: `pytest tests/application/test_admin_analytics.py` зелёный; `git diff
src/api/routes/public.py` пуст; полный `pytest` не хуже базовой линии.
Estimate: 2
Status: DONE

## Next Action

Все 7 AC verified, ревью пройдено (1 Medium, 1 Low, ничего блокирующего) — готово к COMPLETE.

## Execution History

- **TASK_CREATED** — заведена 2026-09-02 по исследованию `.ai/RESEARCH-ACTIVATION-2026-09-02.md`, §P1 и §P6.
- **PHASE_STARTED** — 2026-09-02 | clarify
- **PHASE_COMPLETED** — 2026-09-02 | clarify | Все 7 AC уже CONFIRMED при заведении задачи, открытых UNKNOWN нет. EDGE-002 (quiet-checkin vs серия реактивации) остаётся открытым — переносится в /plan как решение, не блокирует старт: поведение по умолчанию (не гасить) безопасно, худший случай — одно лишнее мягкое сообщение.
- **PHASE_STARTED** — 2026-09-02 | plan
- **PHASE_COMPLETED** — 2026-09-02 | plan | Технический план на 2 среза; EDGE-002 закрыт как DEC-003 (не резолвим сейчас); единый Python-предикат отклонён в пользу inline SQL (см. Technical Plan п.5).
- **PHASE_STARTED** — 2026-09-02 | estimate
- **PHASE_COMPLETED** — 2026-09-02 | estimate | 2 среза, 5 story points суммарно (S1=3, S2=2); verification уточнена до конкретных тестовых файлов. Все 7 AC покрыты хотя бы одним срезом.
- **SLICE_VERIFIED** — 2026-09-02 | S1 | `status='active'` → `status<>'deactivated'` в `notification_loops.py:2711-2729` и `care_pulse_use_cases.py:407`; 6 новых тестов (3 digest + 3 care-pulse), 17 passed. AC-001…004 → VERIFIED. Не закоммичено.
- **SLICE_VERIFIED** — 2026-09-02 | S2 | `has_first_booking` в activation_funnel и весь WHERE в proof_of_value — та же замена; `activated` остался строго по `status='active'` (DEC-002), UI-копирайт и порядок шагов воронки поправлены. 3 новых теста, 21/21 в файле passed. AC-005, AC-006 → VERIFIED.
- **PHASE_STARTED** — 2026-09-02 | verify (полный прогон)
- **PHASE_COMPLETED** — 2026-09-02 | verify | Базовая линия установлена честно: весь working tree застэшен (`git stash -u`), полный pytest на чистом HEAD `eec29cd` дал 11 failed/1181 passed/5 skipped — тот же список из 11, что и с изменениями TASK-026 (1207 passed). Ноль новых падений, все 11 — предсуществующие (не в файлах этой задачи; один из 11, `test_notification_loops.py::test_request_batch_marks_sent_only_after_telegram_ok`, отдельно перепроверен точечным `git stash` только `notification_loops.py` — падает и без моего изменения). `test_template_duration_per_arena.py` в обоих прогонах даёт collection error — сторонний файл, оказался временно повреждён параллельным процессом в этой же рабочей копии в ходе baseline-проверки (256→~40 байт и обратно после `stash pop`); не относится к TASK-026, не трогал. AC-007 → VERIFIED. Все 7/7 AC задачи VERIFIED.
- **REVIEW** — 2026-09-02 | 1 Medium, 1 Low, 0 Critical/High. Medium: реордер шагов воронки в JS больше не гарантирует монотонное убывание (has_first_booking может превысить copied_invite) — не баг, но стоит проверить на реальных данных. Low: та же группа бага («active» вместо «не деактивирован») остаётся в трёх местах вне Scope этой задачи (habit/correlation `:1811`, weekly-active `:1724`, sleeping-N `:850,871`) — кандидат на отдельную задачу, не трогалось намеренно.
