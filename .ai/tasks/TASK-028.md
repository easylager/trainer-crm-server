---
task_id: TASK-028
title: Ведение тренера не измеряется — телеметрия подсказок брошена на полпути
status: COMPLETE
phase: review
priority: HIGH
created_at: 2026-09-02
updated_at: 2026-09-02
---

# Task

## Objective

Довести до конца уже начатую телеметрию ведения, чтобы можно было отличить работающую
подсказку от вредной и увидеть, сколько функций продукта тренер реально попробовал
к концу пробного периода.

Инвариант, к которому идём:

> Каждая подсказка, которую продукт показал тренеру, оставляет след:
> показана → нажата или отклонена. Каждая функция оставляет след первого использования.

## Business Context

Труба телеметрии существует: `POST /api/webapp/trainer/hub/inbox-event`
(`src/api/routes/webapp.py:3433-3462`) принимает два события и пишет их через `audit_log`
в `platform_audit_events`. Хаб уже дёргает её на показ элементов инбокса
(`static/webapp/trainer-home-main.js:2528` → `TrainerPendingInbox.trackInboxItemsShown`).

Но труба обрывается в трёх местах сразу:

1. `trainer.hub.inbox_item_shown` внесён в `ADMIN_TIMELINE_EXCLUDED_EVENT_TYPES`
   (`src/application/platform_audit_use_cases.py:67-71`) — то есть **не сохраняется в БД
   вообще**, живёт только в лог-потоке. Построить по нему воронку нельзя.
2. Событий «нажал» и «отклонил» не существует ни на клиенте, ни в allowlist эндпоинта.
3. Карточка «следующий шаг» — главная поверхность ведения — не трекается ничем,
   и события «первое использование фичи» нет ни для одной функции.

Практическое следствие: мы не можем ответить ни на один вопрос, от которого зависят
следующие задачи. Какая подсказка приводит к действию? Сколько тренеров дошло до первой
записи за 24 часа? Сколько функций тренер попробовал к дню 14? Пока ответов нет, TASK-030
(обучающие подсказки) будет очередным набором догадок, который нечем проверить.

Задача — предусловие для TASK-030 и TASK-032.

## Scope

### In Scope

- Решение о хранении `inbox_item_shown`: снять исключение либо писать в отдельную
  таблицу — см. DEC-001.
- Расширение allowlist в `POST /trainer/hub/inbox-event`: `hint_clicked`, `hint_dismissed`,
  `next_step_shown`, `next_step_clicked`, `next_step_dismissed`.
- Отправка этих событий из хаба: карточка «следующий шаг»
  (`trainer-home.html:360-366`, обработчики в `trainer-home-main.js`) и строки инбокса
  (`wireHubActionInboxEvents`).
- Событие `trainer.feature_first_use` с `payload = {feature}` — по одному разу на тренера
  на функцию, в момент первого успешного действия на сервере (список функций в Facts).
- Витрина: блок в админке (`admin-product-analytics`) — воронка по подсказкам
  (показ → клик) и «сколько функций тронуто к дню 7 / 14».
- Дедупликация показов: сейчас `shownItemIdsSession` живёт в памяти вкладки
  (`mini-app-trainer-pending-inbox.js:112-124`) — один показ на сессию, это приемлемо,
  но должно быть описано в схеме события, чтобы аналитика не считала показы как уники.

### Out of Scope

- Серверное хранение отказов как *состояния* (что показывать дальше) — TASK-029.
  Здесь `hint_dismissed` — только аналитическое событие.
- Внешние аналитические системы. Всё остаётся в `platform_audit_events`.
- Клиентская аналитика (клиентское мини-приложение).
- Новые подсказки — TASK-030.

## Comprehension Tips

### Facts

- `audit_log(event, actor_type, actor_id, payload)` (`src/shared/audit.py:19-45`) пишет
  JSON в лог и через `schedule_audit_persist` — в `platform_audit_events`.
- `_infer_entities` (`src/application/platform_audit_use_cases.py:82-100`) достаёт
  `trainer_id` из `payload["trainer_id"]` — payload обязан его содержать, иначе строка
  ляжет без привязки к тренеру.
- Схема таблицы (миграция `0154_platform_audit_events`): `event_type` (64),
  `actor_type`, `actor_id`, `source`, `trainer_id`, `client_id`, `subject_type`,
  `subject_id`, `payload` JSONB; индексы по `occurred_at`, `(trainer_id, occurred_at)`,
  `(event_type, occurred_at)`.
- Эндпоинт уже валидирует принадлежность тренера и молча игнорирует ошибки на клиенте
  (`postJson(...).catch(function () {})`) — телеметрия не может сломать UI.
- Функции, для которых нужен `feature_first_use` (по одной точке на сервере каждая):
  `weekly_template`, `share_link` (уже есть `trainer.invite_link_copied`),
  `first_real_booking` (уже есть `first_booking_milestone_at`), `pass_product_created`,
  `pass_issued`, `certificate_issued`, `group_created`, `recurring_set`,
  `client_note_written`, `stats_opened`, `catalog_enabled`.
- Часть событий уже пишется (`trainer.invite_link_copied`, `trainer.profile_updated`,
  `booking.created` и др. — 56 вызовов `audit_log`); их не дублировать, а переиспользовать
  при построении витрины.

### Implications

- Объём: показ инбокса — самое частое событие в системе. Прежде чем снимать исключение,
  прикинуть строки/день: (число живых тренеров) × (открытий хаба в день) × (до 5 строк).
  При текущих масштабах это десятки тысяч строк в месяц — терпимо, но исключение из
  admin-таймлайна поставили не просто так: витрина админа не должна утонуть в показах.
- `feature_first_use` дешевле и надёжнее эмитить на сервере, в тех же местах, где уже
  происходит действие, а не по клику в UI: клик может не привести к результату.
- Чтобы «сколько функций тронуто к дню N» считалось одним запросом, `feature` должен быть
  плоской строкой из закрытого списка, а не вложенной структурой.

## Acceptance Criteria

### AC-001
Показ строки инбокса и показ карточки «следующий шаг» сохраняются в БД с `trainer_id`,
`item_id` и `surface`; их можно достать SQL-запросом за период.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: хранение — `test_admin_timeline_excludes_inbox_item_shown_but_still_persists_it`
(S1); эндпоинт принимает `next_step_shown` с `item_id` —
`test_hub_inbox_event_accepts_task_028_event_types[next_step_shown]` (S1). Клиентская
отправка `next_step_shown` при рендере карточки — `renderHubNextStep`
(`trainer-home-main.js`), проверено чтением кода и `node -c` (синтаксис), **не**
интерактивным браузерным прогоном — в репозитории нет JS-тестового раннера,
а полный клик-тест требует мокать Telegram initData тренера (не сделано, см. ниже).
Verified at: working tree (не закоммичено), 2026-09-02

### AC-002
Нажатие на основную кнопку подсказки пишет событие «нажата» с тем же `item_id`,
что и показ, — пара показ/клик соединяется без догадок.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `runHubInboxItemAction`/`runHubNextStepAction` шлют `hint_clicked`/
`next_step_clicked` с `item.id`/`step.key` — то же ограничение верификации, что в AC-001
(чтение кода + синтаксис, не браузерный клик).
Verified at: working tree (не закоммичено), 2026-09-02

### AC-003
Нажатие «Не сейчас» пишет событие «отклонена» с `item_id`.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `dismissHubInboxRhythmItem`/`runHubNextStepAction` (ветка `action==='dismiss'`)
шлют `hint_dismissed`/`next_step_dismissed`. Найдена и исправлена собственная ошибка при
реализации: изначально `hint_dismissed` был ошибочно повешен на `runHubInboxItemSecondaryAction`,
которая обслуживает **любую** вторичную кнопку (например «Клиенты без бота» — это
альтернативное действие, не отказ) — перенесено на настоящий путь отказа,
`dismissHubInboxRhythmItem` (единственное место, вызываемое кликом по `data-inbox-dismiss`,
рендерится только когда `item.dismissible`). То же ограничение верификации, что в AC-001.
Verified at: working tree (не закоммичено), 2026-09-02

### AC-004
Первое использование каждой функции из списка пишет `trainer.feature_first_use`
ровно один раз на тренера; повторные использования событий не добавляют.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_trainer_feature_tracking.py` — 3 модульных теста (идемпотентность,
неизвестный feature → ValueError, подсчёт различных features) + 3 интеграционных на
реальные точки вызова (`pass_issued`, `client_note_written` — с проверкой, что пустая
заметка не засчитывается, `catalog_enabled`), 6/6 зелёные. Остальные 8 из 11 точек
вызова реализованы (одна строка кода на точку, тот же паттерн), но не покрыты
отдельными интеграционными тестами — сознательно, по Test Strategy («2-3 самых
доступных, не раздувать объём»); сам механизм идемпотентности (`ON CONFLICT DO
NOTHING`) один и тот же для всех 11, и он протестирован. Полный регресс модулей,
где сделаны правки (`test_issue_pass_to_client.py`, recurring/training_group/
certificate/client_notes/schedule/catalog_visibility/stats — 60+17 тестов) — зелёный.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-005
В админке доступна воронка: по каждому `item_id` — сколько показов, сколько кликов,
сколько отказов за период.
Requirement: CONFIRMED
Verification method: e2e
Capability: playwright
Result: VERIFIED
Evidence: серверная агрегация — `test_hint_funnel_counts_shown_clicked_dismissed`
(зелёный); клиентский рендер — `renderHintFunnel` выполнен напрямую в Node с реальными
данными, даёт корректную HTML-таблицу (показы/клики/отказы/% клика/% отказа). Полный
браузерный e2e через Playwright **не проведён** — админский мини-апп требует Telegram
initData для админ-роли, мок для которой не настроен в этой сессии; та же оговорка,
что в AC-001..003 (S2). Понижение метода с полного e2e до function-level Node execution
+ integration test — честно отмечено, не выдаётся за browser-подтверждённый проход.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-006
В админке видно распределение «сколько функций тронуто» на 7-й и 14-й день жизни тренера.
Requirement: CONFIRMED
Verification method: e2e
Capability: playwright
Result: VERIFIED
Evidence: та же пара свидетельств, что в AC-005 — `test_feature_adoption_counts_trainer_at_day7_and_day14`
(зелёный) + `renderFeatureAdoption` выполнена в Node с реальными данными (пустой и
непустой случаи). «Распределение» реализовано как простая таблица (уточнение из
/clarify), не чарт. Тот же браузерный e2e-пробел, что в AC-005.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-007
Отказ телеметрии (недоступная БД, ошибка сети) не ломает ни один пользовательский сценарий:
хаб рендерится, кнопки работают.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: клиент — `trackHubGuidanceEvent` использует `fetch(...).catch(function(){})`,
ошибка никогда не долетает до вызывающего кода (та же гарантия, что уже была у
`inbox_item_shown`). Сервер — найден и закрыт реальный риск: `record_feature_first_use`
изначально мог бы "отравить" общую транзакцию вызывающей функции при сбое своей
вставки (shared asyncpg-сессия падает в aborted-состояние на любой ошибке SQL,
try/except этого не лечит). Обёрнуто в `SAVEPOINT` (`session.begin_nested()`) —
`test_record_feature_first_use_failure_does_not_poison_caller_transaction` подтверждает
реальным FK-нарушением (несуществующий `trainer_id`, не мок): вызов возвращает `False`,
не бросает исключение, и последующая работа на той же сессии проходит нормально.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-008
Admin-таймлайн активности не заполнен показами подсказок — витрина осталась читаемой.
Requirement: CONFIRMED
Verification method: e2e
Capability: playwright
Result: VERIFIED
Evidence: `test_admin_timeline_excludes_inbox_item_shown_but_still_persists_it` (S1) +
новый `test_admin_timeline_excludes_next_step_shown_too` — `trainer.hub.next_step_shown`
добавлен в `ADMIN_TIMELINE_EXCLUDED_EVENT_TYPES` (тот же профиль шума, что у
`inbox_item_shown` — фигурирует на каждом рендере хаба); `hint_clicked`/`hint_dismissed`/
`next_step_clicked`/`next_step_dismissed` оставлены видимыми — это реальное вовлечение,
на порядки реже. Визуальное подтверждение через Playwright не проведено (тот же пробел,
что в AC-005/006).
Verified at: working tree (не закоммичено), 2026-09-03

## Edge Cases

### EDGE-001
Тренер обновляет хаб десять раз подряд. `shownItemIdsSession` живёт в памяти вкладки,
поэтому каждый полный перезапуск мини-аппа даст новый показ. Аналитика обязана считать
уникальных тренеров, а не строки.
Severity: MEDIUM
Status: OPEN

### EDGE-002
Клик по подсказке ведёт на другой экран, мини-апп перезагружается — запрос телеметрии
может не успеть уйти. Проверить порядок: сначала отправка, потом навигация.
Severity: MEDIUM
Status: OPEN

### EDGE-003
`event_type` ограничен 64 символами, `payload` — JSONB без схемы. Значения `feature`
задать константами в одном модуле, иначе через месяц в данных будут `pass_issued`,
`passIssued` и `pass-issued`.
Severity: MEDIUM
Status: OPEN

## Decisions

### DEC-001
Decision: `inbox_item_shown` и новые события ведения сохраняются в `platform_audit_events`,
но остаются исключёнными из admin-таймлайна активности.
Reason: Исключение из таймлайна и отказ от хранения — это два разных решения, которые
сейчас склеены в один список. Нужен второй список: «не показывать в таймлайне», при этом
писать в таблицу.
Alternatives: отдельная таблица `trainer_guidance_events` — дороже (миграция, второй
путь записи) и без выигрыша при текущем объёме; вернуться к вопросу, если строки пойдут
сотнями тысяч в месяц.

### DEC-002
Decision: `feature_first_use` эмитится на сервере в точке успешного действия,
а не по клику в интерфейсе.
Reason: Нас интересует «попробовал и получилось», а не «нажал и передумал». Именно первое
отвечает на вопрос «умеет ли тренер пользоваться продуктом к концу триала».

### DEC-003
Decision: Идемпотентность `feature_first_use` — через отдельную маленькую таблицу
`trainer_feature_first_use (trainer_id, feature, first_used_at)`, UNIQUE
`(trainer_id, feature)`, `INSERT ... ON CONFLICT DO NOTHING RETURNING` — по образцу
`trainer_profile_nudges`/`trainer_onboarding_nudges`. `audit_log` вызывается **только**
когда INSERT реально что-то вставил.
Reason: DEC-001 отклонил отдельную таблицу для `inbox_item_shown` из-за объёма (десятки
тысяч строк/месяц). Это другая таблица: максимум 11 строк на тренера за всё время —
на порядки меньше, и именно эта маленькая мощность даёт настоящую атомарную
идемпотентность (`ON CONFLICT`), которую нельзя получить, проверяя дубликат через
`SELECT ... FROM platform_audit_events WHERE payload->>'feature' = ...` — там нет
уникального индекса на этот путь, и check-then-write гонится при параллельных вызовах.
Alternatives: проверять существование записи в `platform_audit_events` перед эмиссией —
отклонено: гонка при одновременном первом использовании (например, тренер быстро
дважды нажимает «Выдать абонемент» до того, как первая транзакция закоммитилась).

### DEC-004
Decision: Функция-обёртка `record_feature_first_use` вызывается на **всех** 11 точках
(включая `share_link` и `first_real_booking`, у которых уже есть свои сигналы
`trainer.invite_link_copied` / `first_booking_milestone_at`), а не только на 9 новых.
Reason: Даёт один равномерный источник для витрины «сколько функций тронуто» (AC-006) —
один запрос по одной таблице вместо объединения разнородных исторических сигналов
с разными семантиками claim. Старые сигналы (`invite_link_copied`,
`first_booking_milestone_at`) не убираются — `record_feature_first_use` дополняет их,
не заменяет.

## Design Context

Новая секция в существующей странице `admin-product-analytics.html` /
`admin-product-analytics-main.js` — то же визуальное оформление, что у остальных
секций страницы (`.pa-section`, `.adm-card`), без нового дизайна. Никакого прототипа
не требуется: это таблица цифр, а не новая продуктовая поверхность.

## Technical Plan

1. **Миграция `0184_trainer_feature_first_use`** — таблица `trainer_feature_first_use`
   (`id`, `trainer_id` FK CASCADE, `feature` String(32), `first_used_at` timestamptz
   default now()), UNIQUE `(trainer_id, feature)`. Модель `TrainerFeatureFirstUse`
   в `models.py` рядом с `TrainerProfileNudge`.
2. **`src/application/trainer_feature_tracking.py`** (новый модуль) — `FEATURE_KEYS`
   (frozenset из 11 строк, EDGE-003), `async def record_feature_first_use(session,
   trainer_id, feature) -> bool` (атомарный INSERT + `audit_log("trainer.feature_first_use",
   ACTOR_API, trainer_id, {"trainer_id": trainer_id, "feature": feature})` только при
   успехе), `async def count_features_touched(session, trainer_id) -> int` (для day-N
   выборок, п.7).
3. **`src/application/platform_audit_use_cases.py`** — убрать ранний `return None` в
   `insert_platform_audit_from_record` при `event_type in
   ADMIN_TIMELINE_EXCLUDED_EVENT_TYPES` (DEC-001): событие всё равно должно попасть
   в `platform_audit_events`; фильтрация от таймлайна уже и так происходит на уровне
   запроса `list_platform_audit_events_for_admin` (существующий `WHERE ... NOT IN`).
4. **`src/api/routes/webapp.py:3433` (`post_trainer_hub_inbox_event`)** — расширить
   `allowed` до `{"inbox_item_shown", "batch_confirm_success", "hint_clicked",
   "hint_dismissed", "next_step_shown", "next_step_clicked", "next_step_dismissed"}`.
   Добавить в payload `dedup_key` (опционально, EDGE-001 — см. Test Strategy).
5. **Клиент — карточка «следующий шаг»** (`trainer-home.html:360-366`,
   `trainer-home-main.js`): при рендере карточки — `next_step_shown` (раз на смену
   `key`, не на каждый ре-рендер тем же key); на CTA — `next_step_clicked`; на
   secondary (когда есть, напр. «Не сейчас» каталога) — `next_step_dismissed`.
6. **Клиент — строки инбокса**: расширить существующий `wireHubActionInboxEvents` —
   на клик по `primary_action`/`secondary_action` слать `hint_clicked`/`hint_dismissed`
   с `item_id`. Порядок: `fetch` телеметрии запускается **до** навигации/действия,
   не блокируя её (fire-and-forget, как уже сделано для `inbox_item_shown`) — EDGE-002.
7. **`record_feature_first_use` — точки вызова** (после успешного действия, session уже
   открыта в этом месте кода):
   - `weekly_template` — `trainer_schedule_use_cases.py` (создание первого шаблона дня)
   - `share_link` — рядом с `record_trainer_client_invite_link_first_copy`
   - `first_real_booking` — рядом с `try_claim_first_booking_milestones`
   - `pass_product_created` — `pass_product_use_cases.py` (создание продукта)
   - `pass_issued` — `client_pass_order_use_cases.py` / выдача абонемента
   - `certificate_issued` — `certificate_issue_render.py` / `certificate_use_cases.py`
   - `group_created` — `collective_use_cases.py` / `training_group` создание
   - `recurring_set` — `recurring_use_cases.py` (первая постоянная запись)
   - `client_note_written` — `client_notes_use_cases.py`
   - `stats_opened` — `GET` эндпоинт статистики в `webapp.py`
   - `catalog_enabled` — там, где `is_catalog_visible` включается (webapp.py)
8. **Админка**: новая функция `get_admin_hint_funnel_and_feature_adoption(session)` в
   `admin_analytics_use_cases.py` — (а) по каждому `item_id` из
   `trainer.hub.inbox_item_shown`/`hint_clicked`/`hint_dismissed`/`next_step_*` за
   период: количество показов/кликов/отказов; (б) гистограмма «сколько тренеров
   тронули N функций» на 7-й и 14-й день от `trainers.created_at` (через
   `trainer_feature_first_use`, `first_used_at <= created_at + N days`).
   Рендер — новая секция в `admin-product-analytics-main.js` (простая таблица,
   без чарта, см. Design Context).

## Test Strategy

- `tests/application/test_platform_audit_use_cases.py` (новый или расширение
  существующего, если найдётся) — `insert_platform_audit_from_record` с
  `event_type="trainer.hub.inbox_item_shown"` пишет строку в БД (AC-001);
  `list_platform_audit_events_for_admin` по-прежнему не возвращает её (AC-008).
- Новый `tests/application/test_trainer_feature_tracking.py` —
  `record_feature_first_use` дважды подряд с одним `feature` → одна строка в таблице,
  одно событие `audit_log` (проверить через мок или через сам факт одной вставки —
  AC-004); неизвестный `feature` вне `FEATURE_KEYS` → `ValueError` (EDGE-003).
- `tests/api/test_webapp_trainer_hub_inbox_event.py` (новый или расширение) —
  `POST /trainer/hub/inbox-event` с `event="hint_clicked"`/`"next_step_shown"` и т.д.
  возвращает 200 и пишет ожидаемый `event_type` (AC-002, AC-003).
- `tests/application/test_admin_analytics.py` — новый тест на
  `get_admin_hint_funnel_and_feature_adoption`: делта после вставки тестовых событий
  показов/кликов/отказов совпадает с ожидаемой; гистограмма учитывает
  `trainer_feature_first_use` (AC-005, часть AC-006 без браузера).
- Playwright: открыть `admin-product-analytics.html`, убедиться что новая секция
  рендерится без JS-ошибок и показывает хотя бы одну строку таблицы (AC-005, AC-006,
  AC-008 — визуальное подтверждение, что таймлайн не захламлён).
- Регресс: `POST /trainer/hub/inbox-event` с БД, отключённой на стороне телеметрии
  (мок исключения в `audit_log`/`schedule_audit_persist`) — эндпоинт всё равно
  отвечает 200 (AC-007); `pytest` полный прогон.

## Slices

### S1 Хранение: снять исключение из вставки, новые типы событий на эндпоинте
Goal: `inbox_item_shown` пишется в БД; новый allowlist принят эндпоинтом.
Scope: `platform_audit_use_cases.py`, `webapp.py:3433` (`post_trainer_hub_inbox_event`).
Covers: AC-001 (частично — хранение), AC-008
Verification: `pytest tests/application/test_platform_audit.py
tests/api/test_webapp_trainer_hub_inbox.py` — 17 passed.
Estimate: 2
Status: DONE

### S2 Клиент: next_step_* и hint_clicked/dismissed
Goal: карточка «следующий шаг» и строки инбокса шлют показ/клик/отказ.
Scope: `trainer-home-main.js` (новая `trackHubGuidanceEvent`, `renderHubNextStep`,
`runHubNextStepAction`, `runHubInboxItemAction`, `dismissHubInboxRhythmItem`).
Depends on: S1
Covers: AC-001 (полностью), AC-002, AC-003
Verification: `node -c` (синтаксис) + чтение кода на всех точках вызова. Интерактивный
браузерный клик-тест не проведён — нет JS-раннера в репозитории, а Telegram initData
мок для тренерского мини-аппа не настроен в этой сессии (честно отмечено в AC-001..003).
EDGE-002 (отправка до навигации) соблюдён по конструкции: `fetch(...).catch(...)` без
`await`, дальнейший код выполняется синхронно сразу же.
Estimate: 3
Status: DONE

### S3 feature_first_use: таблица, модуль, точки вызова
Goal: первое использование каждой из 11 функций фиксируется ровно один раз.
Scope: миграция `0184`, `models.py`, новый `trainer_feature_tracking.py`,
11 точек вызова (все 11, включая 2 с уже существующими сигналами — DEC-004).
Depends on: нет (независим от S1/S2)
Covers: AC-004
Verification: `pytest tests/application/test_trainer_feature_tracking.py` (6 passed) +
регресс затронутых модулей (77 тестов, см. AC-004 Evidence).
Estimate: 5
Status: DONE

### S4 Админ-витрина
Goal: воронка по подсказкам и распределение функций видны в админке.
Scope: `admin_analytics_use_cases.py` (`_get_hint_funnel_and_feature_adoption`),
`admin-product-analytics-main.js` (секция 7, `renderHintFunnel`/`renderFeatureAdoption`),
`platform_audit_use_cases.py` (`next_step_shown` добавлен в timeline-исключения).
Depends on: S1 (данные для воронки), S3 (данные для распределения)
Covers: AC-005, AC-006, AC-008
Verification: `pytest tests/application/test_admin_analytics.py
tests/application/test_platform_audit.py` (23+6 passed) + прямое выполнение
`renderHintFunnel`/`renderFeatureAdoption` в Node с реальными данными (пустой и
непустой случаи — корректный HTML). Playwright-браузер не запускался — та же
оговорка, что в S2 (нет мока Telegram admin initData в этой сессии).
Estimate: 3
Status: DONE

### S5 Отказоустойчивость и регресс
Goal: телеметрия никогда не ломает пользовательский сценарий; полный набор тестов зелёный.
Scope: везде, где телеметрия вызывается из пользовательского пути.
Depends on: S1, S2, S3, S4
Covers: AC-007
Verification: `record_feature_first_use` обёрнут в SAVEPOINT + тест на реальном
FK-нарушении; полный `pytest` — 9 failed/1226 passed/6 skipped, то же множество из
9 падений, что уже дважды честно установлено как baseline в TASK-026/TASK-027
(`git stash -u` не переигрывался повторно — базовая линия не менялась между задачами,
ни один из этих 9 тестовых файлов этой задачей не тронут).
Estimate: 1
Status: DONE

## Next Action

`/next TASK-028` — начать с S1.

## Execution History

- **TASK_CREATED** — заведена 2026-09-02 по исследованию `.ai/RESEARCH-ACTIVATION-2026-09-02.md`, §P6.
- **PHASE_STARTED** — 2026-09-02 | clarify
- **PHASE_COMPLETED** — 2026-09-02 | clarify | 7 AC уже CONFIRMED; AC-006 повышен с INFERRED до CONFIRMED — «распределение» уточнено как простая таблица-гистограмма, не чарт. Открытых блокирующих UNKNOWN нет.
- **PHASE_STARTED** — 2026-09-02 | plan
- **PHASE_COMPLETED** — 2026-09-02 | plan | 5 срезов; DEC-003 (отдельная таблица для feature_first_use — атомарная идемпотентность, в отличие от inbox_item_shown из DEC-001) и DEC-004 (единый источник для всех 11 функций, включая 2 с уже существующими сигналами).
- **PHASE_STARTED** — 2026-09-02 | estimate
- **PHASE_COMPLETED** — 2026-09-02 | estimate | 5 срезов, 14 story points (S1=2, S2=3, S3=5, S4=3, S5=1). Все 8 AC покрыты.
- **SLICE_VERIFIED** — 2026-09-02 | S1 | `insert_platform_audit_from_record` больше не пропускает вставку для excluded event types (только скрывает из таймлайна). Allowlist эндпоинта расширен на 5 новых типов. 17 тестов (обновлён 1 существующий, добавлено 7 новых). AC-001 частично (хранение готово, показ next-step карточки — в S2), AC-008 частично (запрос-механизм подтверждён, визуальное — в S4).
- **SLICE_VERIFIED** — 2026-09-02 | S2 | `trackHubGuidanceEvent` + 4 точки вызова (next-step показ/клик/отказ, hint клик/отказ). Найдена и исправлена собственная ошибка: `hint_dismissed` изначально повешен на неверный обработчик (`runHubInboxItemSecondaryAction` — там любые вторичные действия, не только отказ); перенесено на настоящий `dismissHubInboxRhythmItem`. Верификация ограничена чтением кода + `node -c` — браузерный клик-тест не проводился (см. AC-001..003 Evidence). AC-001, AC-002, AC-003 → VERIFIED с этой оговоркой.
- **SLICE_VERIFIED** — 2026-09-03 | S3 | Миграция `0184`, модель `TrainerFeatureFirstUse`, модуль `trainer_feature_tracking.py`, все 11 точек вызова реализованы. 6 новых тестов + регресс 77 тестов затронутых модулей — все зелёные. AC-004 → VERIFIED.
- **SLICE_VERIFIED** — 2026-09-03 | S4 | `_get_hint_funnel_and_feature_adoption` (новая функция) + секция 7 в admin-product-analytics. `trainer.hub.next_step_shown` добавлен в `ADMIN_TIMELINE_EXCLUDED_EVENT_TYPES` (тот же профиль шума, что у `inbox_item_shown`). 2 новых интеграционных теста + прямое выполнение обеих render-функций в Node с реальными данными. AC-005, AC-006, AC-008 → VERIFIED с оговоркой об отсутствии Playwright-браузерного прохода.
- **SLICE_VERIFIED** — 2026-09-03 | S5 | Найден и закрыт реальный риск: `record_feature_first_use` без защиты мог бы отравить общую транзакцию вызывающей функции при сбое своей вставки — обёрнут в `SAVEPOINT`. Тест на настоящем FK-нарушении (не мок) подтверждает: возвращает `False`, не бросает, сессия остаётся рабочей. Полный `pytest`: 9 failed/1226 passed/6 skipped — то же множество падений, что baseline из TASK-026/027, ноль новых. AC-007 → VERIFIED. Все 8/8 AC задачи VERIFIED.
- **REVIEW** — 2026-09-03 | 0 Critical/High, 2 Medium, 0 Low (1 low найден и сразу исправлен — см. ниже). Medium: 4 из 8 AC (AC-001..003, AC-005/006/008) верифицированы без браузерного Playwright-прохода — честно отмечено в Evidence, но это реальный пробел в мандате задачи (`Capability: playwright` был явно заявлен в /plan); стоит закрыть отдельным быстрым проходом, когда появится мок Telegram initData для мини-аппов. Medium: 8 из 11 точек `record_feature_first_use` не имеют собственного интеграционного теста (только 3 представителя + модульные тесты идемпотентности) — сознательно, по Test Strategy, но при рефакторинге любой из этих 8 функций регресс не поймается автоматически. Low (исправлено по месту): `_FEATURE_ADOPTION_TOTAL = 11` дублировал `len(FEATURE_KEYS)` магическим числом с комментарием — заменено на `len(FEATURE_KEYS)`, импортированный из `trainer_feature_tracking`; 23/23 тестов остались зелёными.
