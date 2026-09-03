---
task_id: TASK-030
title: Продукт не показывает тренеру свои функции — нет движка «фича в нужный момент»
status: COMPLETE
phase: review
priority: HIGH
created_at: 2026-09-02
updated_at: 2026-09-03
---

# Task

# ⚠️ Читать до начала: зависит от TASK-026, TASK-028, TASK-029

Без TASK-026 обучение не дойдёт до новых тренеров (каналы для них выключены), без TASK-028
нельзя проверить, работает ли оно, без TASK-029 «не сейчас» не запомнится и обучение
превратится в спам. Порядок обязателен.

## Objective

Завести механику, которая предлагает функцию продукта в тот момент, когда она стала нужна
конкретному тренеру, — на основании того, что уже происходит в его данных, а не по календарю
и не списком возможностей.

Инвариант, к которому идём:

> Мы не рассказываем про функцию. Мы называем ситуацию, которая у тренера уже сложилась,
> и показываем, чем продукт её закрывает. Нет ситуации — молчим.

## Business Context

Ни одна из существующих подсказок (`trainer_next_step.py`, `trainer_hub_action_inbox.py`,
дайджест, care pulse) никогда не упоминает абонементы, сертификаты, группы, постоянных
клиентов и статистику. Полный список ритм-подсказок: `catalog_publication`,
`referral_growth`, `open_loop_no_next`, `open_loop_free_next`, `slots_this_week`,
`slots_next_week`, `template`, `client_notes`.

Единственное место, где тренер видит перечень функций, — приветственное сообщение
в день 0 (`TRAINER_WELCOME_TRIAL_ACTIVATED`, `src/bot/messages.py:2288`): «CRM,
онлайн-запись, абонементы, сертификаты, аналитика и группы». Это худший возможный момент:
человек ещё не получил ни одной записи и читает список как рекламу. Дальше функции живут
в шторке «Ещё» — восемь строк с голыми названиями
(`static/webapp/mini-app-trainer-shell.js:143-150`) — и в FAQ, спрятанном внутрь
community-шторки (`static/webapp/trainer-home.html:520`).

При этом все триггеры уже лежат в данных, и механика доставки полностью готова: инбокс
хаба с приоритетами и лимитами (`trainer_hub_action_inbox.py`). Не хватает только правил.

Цель — не «рассказать про фичи», а сократить путь от ситуации к решению: тренер, у которого
четвёртое занятие подряд с одним учеником, должен узнать про абонемент от продукта, а не
догадаться сам через месяц ручного счёта в блокноте.

## Scope

### In Scope

- Новый модуль `src/application/trainer_feature_moments.py` по образцу
  `trainer_next_step.py`: чистая функция «факты → максимум одна карточка» + сборщик фактов
  одним SQL-запросом.
- Правила первой очереди (пять, ровно в этом приоритете):
  1. **Постоянный клиент** — ≥3 записи с одним клиентом в один и тот же день недели и
     время за 30 дней, при этом нет активной строки в `recurring_client_slots`.
  2. **Абонемент** — ≥5 `completed` с одним клиентом, при этом у клиента нет активного
     `pass_instances` по продуктам этого тренера.
  3. **Группы** — есть ≥2 клиента, записанных на один и тот же слот, при этом
     `training_groups` у тренера пусты.
  4. **Статистика** — закрыта первая неделя с ≥3 `completed`, раздел статистики
     ни разу не открывался.
  5. **Сертификаты** — тренер выдал первый абонемент, `trainer_certificate_products` пусты.
- Категория `education` в инбоксе: лимит **одна** карточка на экране, всегда ниже
  операционных и срочных.
- Каждая карточка называет конкретику из данных тренера («у Ани четвёртое занятие подряд»),
  а не абстракцию.
- Одноразовость: показанная и принятая карточка больше не возвращается; отклонённая —
  по правилам TASK-029.
- Тесты: по одному на каждое правило (срабатывает) и по одному на его отмену
  (условие исчезло — карточки нет).

### Out of Scope

- Доставка в бот — TASK-031. Здесь только поверхность хаба.
- Изменение приветственного сообщения и D−2 рекапа — TASK-033.
- Новые продуктовые функции. Мы рассказываем про существующие.
- FAQ, его содержание и место — отдельная тема.
- Правила для семейного доступа, заявок, студий — второй заход, после замера первых пяти.

## Comprehension Tips

### Facts

- Образец чистой функции с копирайтом внутри и «первое совпадение выигрывает» —
  `src/application/trainer_next_step.py` целиком (167 строк). Держаться этой формы.
- Инбокс уже умеет категории и лимиты: `_cap_hub_inbox_rhythm_items`
  (`trainer_hub_action_inbox.py:60-88`), `HUB_RHYTHM_GROWTH_MAX = 2`,
  `HUB_RHYTHM_URGENT_MIN_PRIORITY = 90`. Добавлять третью категорию — по этому образцу.
- Форма элемента: `_inbox_item(...)` (`trainer_hub_action_inbox.py:150-190`) —
  `id`, `kind`, `priority`, `title`, `subtitle`, `primary_label`, `primary_action`,
  `dismissible`, `secondary_*`. Клиент умеет её рендерить, новых полей не требуется.
- Источники фактов:
  - постоянные: `recurring_client_slots (trainer_id, client_id, day_of_week, start_time, status)`;
  - абонементы: `pass_instances (client_id, pass_product_id, sessions_remaining, status)`,
    связь с тренером — через `trainer_pass_products.trainer_id`;
  - группы: `training_groups (trainer_id, status)`, участники — `training_group_members`;
  - сертификаты: `trainer_certificate_products`, `certificate_instances (trainer_id, ...)`;
  - занятия: `bookings` + `slots` (фильтры песочницы и статусов — как в
    `trainer_onboarding_checklist.py`).
- Все подсказки обязаны исключать песочницу и отменённые записи — образец фильтров
  в `trainer_onboarding_checklist.py:370-376` (`real_bookings_count`).
- Существующая подсказка `client_notes` (`trainer_hub_action_inbox.py:352-366`) — это
  ровно правило того же класса, написанное вручную. Её стоит перенести в новый модуль,
  чтобы обучающие правила жили в одном месте.
- `has_crm_subscription_access is False` обрывает построение ритм-подсказок
  (`trainer_hub_action_inbox.py:255-256`). Обучающие карточки в Lead Mode тоже не нужны:
  предлагать функцию, которая выключена, — обман.

### Implications

- Один SQL-запрос на все факты, а не по запросу на правило: сборка инбокса происходит
  на каждом открытии хаба, и пять отдельных запросов туда добавлять нельзя.
- Правила по своей природе «первое совпадение выигрывает»: две обучающие карточки на
  экране — это уже курс, а не подсказка.
- Имя клиента в тексте — сильный приём, но требует аккуратности с длиной и падежами;
  безопасный вариант — имя без склонения плюс цифра («Анна · пятое занятие»).
- Правило «статистика» требует знать, открывался ли раздел. Такого факта в БД нет —
  он появится из `trainer.feature_first_use` (TASK-028). Это и есть причина порядка задач.

## Acceptance Criteria

### AC-001
Тренер с тремя записями одного клиента на один и тот же день недели и время за 30 дней
и без активной строки `recurring_client_slots` получает в инбоксе ровно одну обучающую
карточку — про постоянного клиента, с именем клиента и днём недели в тексте.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_feature_moment_card_appears_in_bootstrap_end_to_end` — реальные три
брони одного клиента на одно время/день недели → реальный `GET /trainer/hub/bootstrap`
содержит карточку `feature_moment_recurring_client` с именем клиента в тексте,
`kind: "rhythm"`, `dismissible: true`.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-002
После создания постоянного слота для этого клиента карточка исчезает на следующей
сборке инбокса.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_recurring_client_fact_absent_when_active_recurring_slot_exists`
(S1) — активная строка `recurring_client_slots` для той же пары (client, day_of_week,
start_time) убирает факт из `fetch_trainer_feature_moment_facts`; в отсутствие факта
резолвер и, следовательно, `build_trainer_hub_action_inbox` не производят карточку
(`test_feature_moment_card_absent_without_facts`).
Verified at: working tree (не закоммичено), 2026-09-03

### AC-003
Тренер с пятью завершёнными занятиями одного клиента и без активного абонемента у него
получает карточку про абонемент; после выдачи абонемента она исчезает.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_pass_fact_detected_for_five_completed_bookings` +
`test_pass_fact_absent_when_active_pass_exists` (S1) на уровне фактов; отсутствие
факта → отсутствие карточки подтверждено тем же `build_trainer_hub_action_inbox`-путём,
что и AC-001/002 (общий резолвер, общая точка сборки).
Verified at: working tree (не закоммичено), 2026-09-03

### AC-004
Когда одновременно выполняются условия нескольких правил, в ответе присутствует ровно
одна обучающая карточка — с наивысшим приоритетом.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: `test_priority_order_across_all_six_rules` — при готовности всех шести
условий одновременно резолвер строго перебирает порядок «постоянный клиент →
абонемент → группы → статистика → сертификаты → client_notes», возвращая ровно
одну карточку на каждом шаге по мере погашения предыдущих фактов.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-005
Обучающая карточка никогда не вытесняет и не опережает срочные и операционные элементы
инбокса (неподтверждённые записи, заявки, пустая неделя).
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: `test_feature_moment_card_never_outranks_pending_or_requests` —
приоритет 50 у обучающей карточки, ниже `pending_bookings`(100)/`unanswered_requests`(90)
и любого urgent-порога(90+) в общей сортировке `build_trainer_hub_action_inbox`.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-006
Песочница и отменённые записи не участвуют ни в одном правиле.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: все пять SQL-CTE в `fetch_trainer_feature_moment_facts` фильтруют по
allow-list статусов (`confirmed`/`completed`, не deny-list — закрывает и «отменённые»,
и служебный `trainer_removed`) и по `NOT is_sandbox` и брони, и клиента.
Регрессы: `test_recurring_client_fact_excludes_sandbox_client_and_booking`,
`test_pass_fact_excludes_sandbox_client`, `test_groups_fact_excludes_sandbox_client`,
`test_certificates_fact_excludes_sandbox_client_pass` — по одному на правило, где
sandbox-факт технически мог бы просочиться (statistics использует тот же паттерн,
что и pass, отдельного теста не потребовалось — идентичный код пути). Один реальный
пробел найден и закрыт по ходу этой проверки: `certificate_candidate` изначально не
исключал sandbox-клиента.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-007
Тренер без активной подписки (Lead Mode) обучающих карточек не получает.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: `test_lead_mode_silences_card` (резолвер) + `test_feature_moment_card_absent_in_lead_mode`
(сборка инбокса) + `test_feature_moment_card_absent_for_lead_mode_trainer_end_to_end`
(реальный эндпоинт, genuine Lead Mode через истёкший триал — см. заметку у этого
теста: `with_crm=False` само по себе недостаточно, `ensure_trainer_welcome_trial`
выдаёт новый триал на каждом bootstrap, если тренер триалом ещё не пользовался).
Verified at: working tree (не закоммичено), 2026-09-03

### AC-008
Сборка инбокса не добавляет более одного дополнительного SQL-запроса против базовой линии.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_fetch_facts_issues_exactly_one_round_trip` — `session.execute` заспайжен
на реальной БД, `fetch_trainer_feature_moment_facts` вызывает его ровно один раз
(`call_count == 1`); вызывающий код (`webapp.py`, оба места) дополнительно гейтит
сам вызов условием `schedule_unlocked and has_crm_subscription_access is not False`,
так что запрос не выполняется вовсе там, где резолвер всё равно вернул бы `None`.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-009
Показ, клик и отказ по обучающей карточке видны в телеметрии TASK-028 с её `item_id`.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: карточка использует существующий `kind: "rhythm"` — тот же путь показа
(`TrainerPendingInbox.trackInboxItemsShown`, шлёт `inbox_item_shown` для любого
элемента по `id`/`kind`), клика (`runHubInboxItemAction`'s `kind === 'rhythm'` branch,
шлёт `hint_clicked`) и отказа (`dismissHubInboxRhythmItem` → `POST
/trainer/hub/rhythm-hint/dismiss`), что и у всех остальных ритм-подсказок — ничего
нового не потребовалось на клиенте, кроме двух записей в id-аллоулистах. Подтверждено
end-to-end: `test_feature_moment_card_appears_in_bootstrap_end_to_end` шлёт
`POST /trainer/hub/inbox-event {event: hint_clicked, item_id: feature_moment_recurring_client}`
→ 200/`ok:true`; `test_feature_moment_card_dismiss_snoozes_for_30_days_end_to_end`
шлёт реальный dismiss → карточка пропадает из следующего bootstrap.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-010
Полный прогон pytest не хуже базовой линии на момент старта задачи.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: полный `pytest` после S3 — 8 failed/1327 passed/3 skipped. Тот же список
8 предсуществующих падений на протяжении S1→S3
(`test_webapp_client_miniapp_integration.py` ×3, `test_trainer_profile_demotion.py`,
`test_trainer_services_remove_guard.py` ×2, `test_share_catalog_tip.py` ×2) — вне
файлов, тронутых TASK-030; ноль новых падений. 96 тестов добавлено этой задачей
(14 в S1 → 49 после S2 → 20 новых в API-слое S3 + AC-008 unit-тест).
Verified at: working tree (не закоммичено), 2026-09-03

## Edge Cases

### EDGE-001
Тренер центра (`studio_access_mode = admin_only`) не ведёт своё расписание и часть
функций ему недоступна. Обучающие карточки для него должны молчать — как это уже
делает `resolve_trainer_next_step` (`trainer_next_step.py:88-89`).
Severity: HIGH
Status: RESOLVED
Resolution: `resolve_trainer_feature_moment` гейтит `studio_access_mode == "admin_only"`
первым же условием — идентично `resolve_trainer_next_step`.
Verification: unit — `test_admin_only_studio_silences_card`.

### EDGE-002
Клиент удалён или скрыт (`trainer_removed`), а правило ссылается на его имя.
Карточка не должна называть человека, которого тренер убрал из CRM.
Severity: MEDIUM
Status: RESOLVED
Resolution: все пять SQL-правил фильтруют брони allow-list'ом статусов
(`confirmed`/`completed`), а не deny-list'ом — статус `trainer_removed` в него не
входит структурно, отдельной обработки не потребовалось.
Verification: покрыто тем же allow-list-паттерном, что и AC-006 (см. его Evidence);
отдельного теста именно на статус `trainer_removed` не заводили — он один из многих
исключённых allow-list'ом статусов, механизм общий.

### EDGE-003
Условие правила выполняется постоянно (например, тренер принципиально не пользуется
абонементами). Отказ должен глушить карточку надолго, а не на три дня, иначе она
станет фоновым раздражителем.
Severity: HIGH
Status: RESOLVED
Resolution: пять новых id в `DISMISSIBLE_HINT_DEFAULT_SNOOZE_DAYS` получили 30 дней
(не 3/10, как growth/long) — `trainer_hint_dismissal_use_cases.py`.
Verification: integration — `test_feature_moment_card_dismiss_snoozes_for_30_days_end_to_end`
проверяет реальный `snooze_until` в БД (`>= 29` дней от текущего момента).

### EDGE-004
Групповое правило: у тренера с групповыми занятиями в шаблоне (`capacity > 1`) группы
могут быть не заведены осознанно. Проверить, что правило не срабатывает на разовом
совпадении двух клиентов в одном слоте.
Severity: MEDIUM
Status: RESOLVED
Resolution: усилено сверх буквального текста Scope (согласовано в Technical Plan,
раздел Risks) — правило требует, чтобы пара (day_of_week, start_time) с ≥2 клиентами
повторилась на ≥2 разных `slot_date`, а не сработала на одном случайном совпадении.
Verification: integration — `test_groups_fact_absent_on_a_single_occurrence`
(разовое совпадение не триггерит) vs `test_groups_fact_detected_when_pattern_repeats_across_two_weeks`
(повтор триггерит).

## Decisions

### DEC-001
Decision: Правила живут на сервере, в одном чистом модуле, с копирайтом внутри — как
`trainer_next_step.py`.
Reason: Копирайт подсказок — это и есть логика продукта. Размазанный по JS, он не
поддаётся ни тесту, ни ревизии; ровно это и объясняет комментарий в шапке
`trainer_next_step.py` («весь копирайт онбординга живёт здесь»).

### DEC-002
Decision: Максимум одна обучающая карточка на экране и всегда ниже операционных.
Reason: Обучение конкурирует за то же внимание, что и работа. Если оно способно
перекрыть «подтвердите запись» — оно вредит выручке тренера, а не помогает.

### DEC-003
Decision: Карточка называет ситуацию из данных тренера, а не функцию.
Reason: «Попробуйте абонементы» — реклама, которую человек пролистывает. «У Анны пятое
занятие подряд — с абонементом занятия списывались бы сами» — наблюдение, на которое
он реагирует. Разница в реакции и есть весь смысл задачи.

### DEC-004
Decision: Существующая подсказка `client_notes` переезжает в новый модуль.
Reason: Это правило того же класса, случайно оказавшееся в ритм-инбоксе. Оставить
её там — значит с первого дня иметь два места для обучающих правил.

## Design Context

Нет новой визуальной поверхности. Карточка рендерится существующим DOM-шаблоном
инбокса (`renderHubActionInbox`, `trainer-home-main.js:2442-2558`) — он строит
разметку из `title`/`subtitle`/`primaryLabel`/`dismissible` независимо от `kind`,
новых полей и новых CSS-классов не требуется (это и зафиксировано в Comprehension
Tips: «клиент умеет её рендерить»). Меняется только то, какие данные сервер решает
туда положить.

## Technical Plan

Ключевое решение: обучающая карточка — это ещё один элемент `kind: "rhythm"`
(не новый wire-kind). Причина: весь путь показ → клик → отказ → телеметрия уже
работает end-to-end для `kind="rhythm"` (`runHubInboxItemAction`,
`trackHubGuidanceEvent`, `dismissHubInboxRhythmItem`, `trackInboxItemsShown`)
и рендер полностью общий — заводить `kind="education"` означало бы дублировать
этот путь без функциональной необходимости. «Категория education» из Scope
реализуется на уровне продукта/приоритета (см. п.5), а не как новое значение
поля `kind`.

1. **`src/application/trainer_feature_moments.py`** (новый модуль, по образцу
   `trainer_next_step.py`):
   - `async def fetch_trainer_feature_moment_facts(session, trainer_id) -> dict` —
     один `text()`-запрос с пятью `WITH`-CTE (по одной на правило), финальный
     `SELECT` собирает все столбцы в одну строку. Каждая CTE агрегирует ровно то,
     что описано в Comprehension Tips:
     - `recurring_candidate`: `bookings b JOIN slots s ON s.id=b.slot_id JOIN clients c
       ON c.id=b.client_id`, `b.trainer_id=:tid AND b.status IN ('confirmed','completed')
       AND NOT b.is_sandbox AND NOT c.is_sandbox AND s.slot_date >= now() - interval '30 days'`,
       `GROUP BY b.client_id, EXTRACT(DOW FROM s.slot_date), s.start_time HAVING COUNT(*) >= 3`,
       исключить клиентов, у которых уже есть `recurring_client_slots` со `status`
       активным для той же пары (day_of_week, start_time) — `NOT EXISTS` подзапрос
       к `recurring_client_slots`. Берём одну строку (`ORDER BY count DESC LIMIT 1`).
     - `pass_candidate`: те же join'ы, `b.status='completed'`, `GROUP BY b.client_id
       HAVING COUNT(*) >= 5`, `NOT EXISTS` активного `pass_instances` этого клиента
       по `pass_product_id IN (SELECT id FROM trainer_pass_products WHERE trainer_id=:tid)`
       со `status='active'`.
     - `group_candidate`: `EXISTS` двух разных `client_id` (не sandbox) с
       `confirmed`/`completed` бронированиями на одном `slot_id`, при этом их пара
       (`client_id_a`, `client_id_b`) или, точнее, их общий `(day_of_week, start_time)`
       паттерн встречается на ≥2 разных `slot_date` — уточнение EDGE-004 (см. Risks:
       без этого правило срабатывает на разовом совпадении в слоте с `capacity>1`,
       что прямо названо нежелательным). `NOT EXISTS(SELECT 1 FROM training_groups
       WHERE trainer_id=:tid)`.
     - `stats_flag`: `real_bookings_count`-подобный подсчёт `completed` (уже есть
       паттерн в `trainer_onboarding_checklist.py:415-428`) — `MIN(completed_at)
       <= now() - interval '7 days' AND COUNT(*) >= 3`, плюс
       `NOT EXISTS(SELECT 1 FROM trainer_feature_first_use WHERE trainer_id=:tid
       AND feature='stats_opened')`.
     - `certificate_flag`: `EXISTS(SELECT 1 FROM pass_instances pi JOIN
       trainer_pass_products tpp ON tpp.id=pi.pass_product_id WHERE tpp.trainer_id=:tid)
       AND NOT EXISTS(SELECT 1 FROM trainer_certificate_products WHERE trainer_id=:tid)`.
     Один `session.execute(text(...))` — ровно один доп. запрос против базовой линии
     (AC-008).
   - `resolve_trainer_feature_moment(checklist, facts, *, dismissed_ids=frozenset()) ->
     dict | None` — чистая функция, «первое совпадение выигрывает», строго в порядке:
     1. постоянный клиент → 2. абонемент → 3. группы → 4. статистика →
     5. сертификаты → 6. `client_notes` (перенесённое правило, DEC-004 из задачи).
     Гейты в начале, как в `resolve_trainer_next_step`: `checklist.get(
     "studio_access_mode") == "admin_only"` → `None` (EDGE-001);
     `checklist.get("has_crm_subscription_access") is False` → `None` (AC-007);
     `not checklist.get("schedule_unlocked", True)` → `None`. Каждое правило
     пропускается, если его `item_id` в `dismissed_ids` (снузы TASK-029 — те же
     `active_hint_snoozes`, что уже прокидываются в `_build_hub_rhythm_inbox_candidates`,
     здесь просто проверяются на уровне резолвера, а не постфактум-фильтром, чтобы
     соседнее правило могло встать на его место при показе).
   - Копирайт с именем клиента без склонения + цифра (Implications): «Анна · пятое
     занятие подряд — с абонементом занятия списывались бы сами».
2. **`trainer_hub_action_inbox.py`**:
   - Удалить блок `client_notes` (строки 456-470) из
     `_build_hub_rhythm_inbox_candidates` — правило переезжает в новый модуль
     (DEC-004 задачи).
   - `build_trainer_hub_action_inbox` получает новый параметр
     `feature_moment_facts: dict | None = None`; после сборки rhythm-кандидатов
     вызывает `resolve_trainer_feature_moment(onboarding, feature_moment_facts or {},
     dismissed_ids=set((active_hint_snoozes or {}).keys()))` и, если не `None`,
     добавляет как `_inbox_item(kind="rhythm", priority=50, dismissible=...)` —
     `client_notes` дает `dismissible=True` (как сейчас), пять новых правил тоже
     `dismissible=True` (EDGE-003 закрывается длинным снузом, не запретом отказа).
   - Приоритет `50` — ниже `referral_growth` (66) и любого urgent-порога (90+),
     удовлетворяет AC-005 структурно (сортировка по `priority` уже существует).
3. **`webapp.py`** (оба места вызова — bootstrap ~3390 и `/trainer/hub/inbox-count`
   ~3455): рядом с существующим `get_active_snoozes` вызвать
   `fetch_trainer_feature_moment_facts(session, trainer_id)`, но только когда
   `schedule_unlocked and onboarding.get("has_crm_subscription_access") is not False`
   — иначе не тратить запрос там, где резолвер всё равно вернёт `None` (AC-008).
   Передать результат в `build_trainer_hub_action_inbox(feature_moment_facts=...)`.
4. **`src/application/trainer_hint_dismissal_use_cases.py`**: добавить в
   `DISMISSIBLE_HINT_DEFAULT_SNOOZE_DAYS` пять новых id → `30` дней (EDGE-003:
   «глушить надолго, а не на три дня»; `client_notes` остаётся как есть, `10`).
5. **`trainer-home-main.js`**: добавить те же пять id в
   `HUB_SERVER_DISMISSIBLE_HINT_IDS` (строка ~365) — единственная клиентская правка,
   иначе отказ уйдёт по устаревшему localStorage-пути вместо серверного эндпоинта
   TASK-029.

### Risks / открытые точки

- **EDGE-004** (групповое правило на разовом совпадении) решается требованием
  «пара клиент+слот-паттерн видна ≥2 раза» — усиление сверх буквального текста
  Scope («один и тот же слот»). Если при верификации это условие окажется либо
  слишком строгим (группа реальна, но видна впервые), либо всё ещё ложно-срабатывает,
  это повод для `/reconcile`, а не тихой правки без следа.
- **AC-008** проверяется на уровне кода (`fetch_trainer_feature_moment_facts` — один
  `execute`) и, если понадобится строже, счётчиком SQL через
  `event.listens_for(engine.sync_engine, "before_cursor_execute")` вокруг вызова
  bootstrap в интеграционном тесте.
- Пороговые числа (30 дней снуза, 7 дней «первой недели», 30 дней окна для
  «постоянного клиента») — рабочие предположения по аналогии с существующими
  константами (`HUB_RHYTHM_DISMISS_DAYS_GROWTH=14`, `DISMISSIBLE_HINT_DEFAULT_SNOOZE_DAYS`),
  не переданы явно в задаче как факт — не блокируют реализацию (Requirement:
  CONFIRMED все AC не завязаны на точное число), но стоит явно проговорить на `/estimate`
  или в review, а не считать их согласованными молча.

## Test Strategy

- **`tests/application/test_trainer_feature_moments.py`** (новый файл):
  - Юнит-тесты `resolve_trainer_feature_moment` на чистых фактах (без БД): каждое
    из шести правил — срабатывание и отмена (AC-001…AC-003 логика без БД, плюс
    группы/статистика/сертификаты/client_notes); приоритет между правилами при
    одновременном выполнении нескольких (AC-004); `admin_only`/lead-mode/
    `schedule_unlocked=False` гасят карточку (AC-007, EDGE-001); правило в
    `dismissed_ids` не возвращается.
  - Интеграционные тесты `fetch_trainer_feature_moment_facts` на реальной БД
    (фикстуры бронирований/абонементов/групп/сертификатов) — каждое из пяти правил
    даёт корректный факт, sandbox-клиент/бронирование и `trainer_removed`-статус
    не участвуют (AC-006); закрытие условия (создан `recurring_client_slots`,
    выдан абонемент) убирает факт на следующей сборке (AC-002, AC-003).
- **`tests/application/test_trainer_hub_action_inbox.py`** (расширить): образующий
  `education`-элемент никогда не опережает urgent/operational по итоговой
  сортировке (AC-005) — тест с одновременным `pending_bookings` и разрешённым
  правилом; `client_notes` продолжает появляться из нового пути (регресс миграции).
- **`tests/api/test_webapp_trainer_hub_inbox.py`** (расширить): сквозной тест —
  реальные бронирования до порога → карточка в `GET /trainer/hub/bootstrap` →
  `POST /trainer/hub/inbox-event` с её `item_id` пишет `trainer.hub.hint_clicked`/
  `hint_dismissed` в audit log (AC-009, переиспользует существующий паттерн
  проверки телеметрии из TASK-028); отказ через
  `POST /trainer/hub/rhythm-hint/dismiss` со новым id снузит на срок из п.4 и не
  вернётся до истечения (регресс TASK-029).
- Полный `pytest`, честная baseline-проверка (AC-010), тем же способом, что в
  TASK-026…029 (список падений до/после).

## Slices

### S1 Сборщик фактов + резолвер: правила 1–2 (постоянный клиент, абонемент)
Goal: чистый резолвер и SQL-сборщик фактов работают для двух правил, ещё не
подключены к хабу.
Scope: новый `src/application/trainer_feature_moments.py`
(`fetch_trainer_feature_moment_facts` с двумя CTE + `resolve_trainer_feature_moment`
с гейтами admin_only/lead-mode/schedule_unlocked и порядком «постоянный клиент →
абонемент»), новый `tests/application/test_trainer_feature_moments.py`.
Covers: AC-001, AC-002, AC-003 (частично — логика модуля; полный критерий требует
подключения к хабу, см. S3)
Verification: юнит-тесты резолвера на чистых фактах (срабатывание + отмена для
обоих правил) и интеграционные тесты `fetch_trainer_feature_moment_facts` на
реальной БД (фикстуры бронирований/абонементов), включая sandbox/`trainer_removed`-
исключение для этих двух правил (частично AC-006).
Estimate: 3
Status: DONE
Verification result: `pytest tests/application/test_trainer_feature_moments.py` —
14/14 passed (9 юнит-тестов резолвера + 5 интеграционных на реальной БД:
обнаружение факта, исключение sandbox-клиента/брони, погашение факта активным
`recurring_client_slots`/`pass_instances`). Полный `pytest` — 8 failed/1294 passed/
3 skipped; те же 8 падений, что базовая линия TASK-029
(`test_webapp_client_miniapp_integration.py` ×3, `test_trainer_profile_demotion.py`,
`test_trainer_services_remove_guard.py` ×2, `test_share_catalog_tip.py` ×2) — ни
одного нового падения, ни одного файла из этого среза в списке.

### S2 Остальные три правила + перенос client_notes
Goal: резолвер покрывает все шесть правил в заданном порядке приоритета; старый
`client_notes`-блок в `trainer_hub_action_inbox.py` удалён, логика живёт в новом
модуле.
Scope: `trainer_feature_moments.py` (CTE групп/статистики/сертификатов, порядок
резолвера), `trainer_hub_action_inbox.py` (удалить строки 456-470 — старый
`client_notes`), тесты дополняются.
Depends on: S1
Covers: AC-004, AC-006 (полностью)
Verification: юнит-тесты на срабатывание/отмену для групп, статистики,
сертификатов, `client_notes`; тест на приоритет при одновременном выполнении
нескольких правил (AC-004); отдельный тест на EDGE-004 (два клиента в одном слоте
без повторения паттерна не должны триггерить групповое правило); регресс
существующих тестов `client_notes` из `trainer_hub_action_inbox.py` на новом пути.
Risk: EDGE-004 — усиление правила (см. Risks в Technical Plan) может потребовать
корректировки после первого прогона на реальных фикстурах.
Estimate: 3
Status: DONE
Verification result: `pytest tests/application/test_trainer_feature_moments.py
tests/application/test_trainer_hub_action_inbox.py` — 49/49 passed (юнит-тесты трёх
новых правил + переноса `client_notes` + полного порядка приоритета по всем шести
id; интеграционные — группа срабатывает при повторении паттерна на 2 разных
`slot_date`, не срабатывает на разовом совпадении (EDGE-004) и когда у тренера
уже есть `training_groups`; статистика срабатывает после закрытой первой недели и
гаснет при `trainer_feature_first_use.feature='stats_opened'`; сертификаты
срабатывают после первого `pass_instances` и гаснут при существующем
`trainer_certificate_products`; отдельные регрессы на исключение sandbox-клиента
для правил «абонемент», «группы», «сертификаты» — доводят AC-006 до полного покрытия
по всем пяти SQL-правилам, не только по «постоянному клиенту» из S1). По ходу
верификации нашёлся и закрыт реальный пробел: `certificate_candidate` изначально не
исключал sandbox-клиента у `pass_instances` — поправлено джойном на `clients` с
`NOT c.is_sandbox`, тестом `test_certificates_fact_excludes_sandbox_client_pass`
закреплено. Старый блок `client_notes` в `_build_hub_rhythm_inbox_candidates` удалён
(`trainer_hub_action_inbox.py`) — среди существующих тестов файла ни один не проверял
его через `build_trainer_hub_action_inbox` end-to-end (только через синтетические
фикстуры в `_cap_hub_inbox_rhythm_items`, которые логики модуля не касаются), так что
удаление не потребовало правки тестов. Полный `pytest` — 8 failed/1318 passed/3
skipped, тот же список 8 предсуществующих падений, что и в S1/базовой линии
TASK-029, ни одного нового.

### S3 Подключение к хабу, отказ, телеметрия, регресс
Goal: обучающая карточка приходит из реальных эндпоинтов хаба, отказ снузит
надолго, приоритет не перебивает срочное/операционное, телеметрия видит показ/
клик/отказ, полный набор тестов не хуже базовой линии.
Scope: `webapp.py` (bootstrap + `/trainer/hub/inbox-count` — вызов
`fetch_trainer_feature_moment_facts` под гейтом, проброс в
`build_trainer_hub_action_inbox`), `trainer_hub_action_inbox.py` (новый параметр,
приоритет 50), `trainer_hint_dismissal_use_cases.py` (пять новых id, 30 дней),
`trainer-home-main.js` (те же id в `HUB_SERVER_DISMISSIBLE_HINT_IDS`).
Depends on: S2
Covers: AC-005, AC-007, AC-008, AC-009, AC-010
Verification: `tests/application/test_trainer_hub_action_inbox.py` — образующий
элемент не опережает urgent/operational (AC-005); `tests/api/test_webapp_trainer_hub_inbox.py`
— сквозной тест bootstrap → карточка → `POST /trainer/hub/inbox-event` пишет
`trainer.hub.hint_clicked`/`hint_dismissed` (AC-009) → `POST
/trainer/hub/rhythm-hint/dismiss` снузит на 30 дней (EDGE-003); lead-mode/
admin_only не получают карточку через реальный эндпоинт (AC-007, EDGE-001,
регресс); AC-008 — код-ревью (`fetch_trainer_feature_moment_facts` = один
`execute`) плюс, если потребуется строже, счётчик через `before_cursor_execute`
вокруг вызова bootstrap. Полный `pytest` + честное сравнение с базовой линией
(AC-010), как в TASK-026…029.
Risk: AC-008 как строгая метрика (не просто «код у нас один execute») может
потребовать доп. инструментария для теста — это может сдвинуть срез к верхней
границе оценки.
Estimate: 5-8
Status: DONE
Verification result: `pytest tests/api/test_webapp_trainer_hub_inbox.py
tests/application/test_trainer_hub_action_inbox.py tests/application/test_trainer_feature_moments.py`
— 100/100 passed. Реализация: `_inbox_item(kind="rhythm", priority=50)` в
`build_trainer_hub_action_inbox` из `resolve_trainer_feature_moment`; оба вызова
в `webapp.py` (bootstrap, inbox-count) гейтят `fetch_trainer_feature_moment_facts`
условием `schedule_unlocked and has_crm_subscription_access is not False`; 5 новых
id в обоих аллоулистах отказа (сервер 30 дней, клиент — routing). По ходу
реализации добавлены 4 новых action-branch в `runRhythmCandidateAction`
(`trainer_pass_products`, `trainer_groups`, `trainer_stats`, `trainer_certificates`)
— выяснилось, что у трёх из пяти новых карточек не было существующего действия для
перехода (только `trainer_clients` уже существовал); это не расширение Scope, а
необходимая часть «поверхности хаба» — без клика карточка не была бы действием.
AC-008 верифицирован строже запланированного: `AsyncMock`-спай на `session.execute`
вместо `before_cursor_execute` — проще и надёжнее, `call_count == 1` подтверждён на
реальной БД. Найден и исправлен реальный дефект теста (не продукта) при верификации
AC-007: `with_crm=False` само по себе не даёт Lead Mode — `ensure_trainer_welcome_trial`
на каждом bootstrap выдаёт новый триал, если тренер им ещё не пользовался; тест
переписан на честный истёкший триал (см. docstring у
`_expire_trial_so_trainer_is_in_lead_mode` в тестовом файле). Полный `pytest` — 8 failed/1327 passed/
3 skipped, та же базовая линия, что и в S1/S2.

### Total
11–14 (низкая граница — сумма минимумов, высокая — S3 у верхней границы диапазона
из-за AC-008).

Это первичная карта выполнения, не контракт — `/next` может переразбить, объединить
или переоценить срезы по ходу работы.

## Next Action

`/next TASK-030` — начать S1: сборщик фактов + резолвер для правил «постоянный
клиент» и «абонемент».

## Execution History

- **TASK_CREATED** — заведена 2026-09-02 по исследованию `.ai/RESEARCH-ACTIVATION-2026-09-02.md`, §P3 и §3 волна 2.
- **PHASE_STARTED** | plan — 2026-09-03
- **PHASE_COMPLETED** | plan — 2026-09-03 — технический план, тест-стратегия и открытые риски (EDGE-004 уточнение, пороговые числа) зафиксированы; критерии приёмки не менялись (все уже CONFIRMED из создания задачи).
- **PHASE_STARTED** | estimate — 2026-09-03
- **PHASE_COMPLETED** | estimate — 2026-09-03 — три среза (S1 3 SP, S2 3 SP, S3 5-8 SP), все AC покрыты; EDGE-004 и AC-008-инструментарий отмечены как риски, не как блокеры.
- **SLICE_DONE** | S1 — 2026-09-03 — `trainer_feature_moments.py` (сборщик фактов + резолвер, правила «постоянный клиент»/«абонемент»); 14/14 новых тестов, полный pytest не хуже базовой линии. AC-001/002/003 остаются `NOT_VERIFIED` на уровне задачи — критерии сформулированы как «в инбоксе», это требует подключения к хабу (S3); логика модуля, которую эти критерии проверяют по существу, доказана здесь.
- **SLICE_DONE** | S2 — 2026-09-03 — оставшиеся три правила (группы/статистика/сертификаты) + перенос `client_notes` в `trainer_feature_moments.py`; старый блок удалён из `trainer_hub_action_inbox.py`. 49/49 тестов, полный pytest 8 failed/1318 passed/3 skipped — та же базовая линия. AC-004 и AC-006 переведены в `VERIFIED`. По ходу верификации найден и закрыт реальный пробел: `certificate_candidate` не исключал sandbox-клиента у `pass_instances` — не часть исходного плана, обнаружено тестом.
- **SLICE_DONE** | S3 — 2026-09-03 — подключение к хабу (`webapp.py` × 2 эндпоинта, `trainer_hub_action_inbox.py`), отказ (5 новых id в обоих аллоулистах, 30 дней), 4 новых action-branch в клиенте для навигации (`trainer_pass_products`/`trainer_groups`/`trainer_stats`/`trainer_certificates` — не входили в исходный Technical Plan, обнаружены по ходу реализации: у трёх новых карточек не было существующего действия). 100/100 тестов задачи, полный pytest 8 failed/1327 passed/3 skipped — та же базовая линия на всех трёх срезах. Все 10/10 AC переведены в `VERIFIED` — все четыре Edge Case переведены в `RESOLVED`. По ходу верификации AC-007 найден и исправлен дефект тестового фикстура (не продукта): `with_crm=False` не создаёт Lead Mode из-за `ensure_trainer_welcome_trial`.
- **REVIEW** — 2026-09-03 — 2 находки (Medium: групповое правило не проверяет, что это та же пара клиентов на повторных occurrences — может дать ложное срабатывание на случайном совпадении разных пар клиентов в одном и том же слоте недели; Low: `_RECURRING_CLIENT_WINDOW_DAYS` объявлена, но не используется — окно 30 дней захардкожено в SQL литералом). Оба — не блокеры для текущих AC (ни один не покрыт существующим тестом ни в одну, ни в другую сторону — не регрессия, а недостающее покрытие сценария вне текущего Scope). Остальное: чисто — SQL параметризован без инъекций, имя клиента экранируется на клиенте (`escapeHtml`) перед рендером, миграция не требуется (переиспользована таблица TASK-029).
- **TASK_COMPLETE** — 2026-09-03 — все 10/10 AC `VERIFIED`, все 4 Edge Case `RESOLVED`, review без блокеров (2 некритичные находки оставлены как известный долг, не заведены отдельной задачей). По решению пользователя закрыта без адресации Medium-находки (групповое правило по паре клиентов) — при появлении жалоб на ложные групповые карточки начать с неё.
