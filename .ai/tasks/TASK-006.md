---
task_id: TASK-006
title: Демо-запись сжигает одноразовые флаги — тренер никогда не получает ссылку для клиентов
status: READY
phase: new
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Перестать безвозвратно тратить одноразовые флаги `share_catalog_tip_sent_at` и `first_booking_milestone_at` на песочную (демо) запись и на отправку, которая не состоялась. Сейчас тренер, прошедший онбординг через «Попробовать на примере», **никогда** не получает свою персональную ссылку для клиентов и никогда не увидит празднование настоящей первой записи.

## Business Context

Персональная ссылка на запись — главный оффер продукта («Отправьте ссылку — дальше ученик сам» на лендинге). Сообщение с этой ссылкой не доезжает вообще ни до кого из новых тренеров, при этом система считает, что доставила его.

## Scope

### In Scope

- `src/application/trainer_first_booking_milestone.py` — условия проставления обоих флагов
- `src/bot/share_catalog_tip.py` — ранний `return` для не-active тренера
- Разделение «флаг проставлен» и «сообщение фактически отправлено»
- Решение: считать ли sandbox-запись основанием для milestone

### Out of Scope

- Содержание самого milestone-сообщения (TASK-011 про смысл вау)
- Момент, когда ссылку показывать в онбординге (TASK-011)

## Comprehension Tips

### Facts

- `src/application/trainer_first_booking_milestone.py:22-38` — `try_claim_first_booking_milestones`: первый UPDATE ставит `first_booking_milestone_at` через `WHERE first_booking_milestone_at IS NULL AND (SELECT COUNT(*) FROM bookings WHERE trainer_id=:tid AND status IN ('confirmed','completed'))=1` — без фильтра `is_sandbox`. Второй UPDATE (:42-53) ставит `share_catalog_tip_sent_at` **безусловно**, если он сейчас NULL и первый claim прошёл (`claimed_congrats`) — без проверки статуса тренера и без проверки, что сообщение реально будет отправлено.
- **Важно — это может не быть багом (а) в исходной формулировке**: `booking_use_cases.py:559-560` явно документирует, что sandbox-запись *намеренно* учитывается для одноразового «celebration»-события: «onboarding demo booking — excluded from stats/revenue, but still counts for the one-time first-booking celebration... so TTV step 2 matches a real booking UX». Комментарий говорит про celebration (congrats-карточку), не про `share_catalog_tip_sent_at` явно — открытый вопрос, распространяется ли это намерение и на неё.
- Во всём остальном коде `is_sandbox` исключается из «настоящих» счётчиков последовательно: `booking_use_cases.py:1483,1535,5029,5079`, `admin_analytics_use_cases.py:546` («Real time-to-first-booking; demo doesn't count»), `trainer_onboarding_checklist.py:225,235,342,353`, `stats_use_cases.py`, `client_stats_use_cases.py`, `care_pulse_use_cases.py`. `trainer_first_booking_milestone.py` — единственное место, где фильтра нет; но с учётом докстринга выше это может быть осознанным решением, а не упущением.
- Транзакции не атомарны между собой: INSERT записи коммитится на `booking_use_cases.py:745`, claim флагов — отдельным commit на `:751` (только если `ms or tip`). Между этими двумя коммитами возможен краш, оставляющий настоящую запись без claimed milestone — отдельный мелкий баг, не в скоупе задачи, но затронет тот же код при фиксе.
- Claim флагов выполняется только при `created_by_trainer` (`:748`). Sandbox-демо создаётся тренером через `create_trainer_quick_booking` (`is_sandbox=True`), вызывается с «Попробовать на примере» (`trainer-home-main.js:4420`, `trainer-home.html:391`) — идёт через тот же путь claim'а. Второй call site — `booking_use_cases.py:4508` внутри `confirm_booking` (клиентская запись, подтверждённая тренером) — тот же безусловный паттерн claim'а.
- `src/bot/share_catalog_tip.py:60-64` — `if not in_public_catalog: if st != TRAINER_STATUS_ACTIVE: return` — выходит молча, ничего не отправив. Timing: флаги проставляются в БД *до* попытки отправки в Telegram. Цепочка вызовов: `trainer_handlers.py` (строки 1881, 2327, 3149) → `_send_first_booking_milestone_followups` (`:862-896`) → `send_trainer_share_catalog_tip_to_chat` (`share_catalog_tip.py:21`), вызывается только если `share_tip` истинно (т.е. DB claim уже прошёл). Значит на момент early return `share_catalog_tip_sent_at` уже закоммичен как non-NULL — баг (б) подтверждён и не зависит от решения по багу (а).
- `TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML` уже существует (`messages.py:3241-3245`) — только `{deep_link}`, без упоминания каталога. Уже используется в других ветках `share_catalog_tip.py:71,81`, но **не используется** в early-return ветке (:60-64) — естественный кандидат для замены early return.
- Новый тренер с лендинга всегда `pending_profile` (не `active`), значит ветка с `return` — это дефолтный путь, а не редкий край.
- Sandbox представлен как `bookings.is_sandbox` (`models.py:724`) и `clients.is_sandbox` (`models.py:439`). На `trainer_profiles`/`trainers` отдельного флага «прошёл демо» не существует — только сами `first_booking_milestone_at`/`share_catalog_tip_sent_at` (`models.py:208-212`).
- Личная ссылка для `pending_profile` тренера **уже работает**: `build_trainer_invite_links` (`trainer_invite_links.py:92-116`) не проверяет статус тренера вообще — только `client_bot_username`, `city_id`, `trainer_id`. Статус гейтит только видимость в публичном каталоге (`share_catalog_tip.py:56-58`), не генерацию deep-link'а. Значит отправка `TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML` для `pending_profile` механически валидна (при условии, что `city_id` уже проставлен — должен быть, раз тренер успел сделать sandbox-запись).

### Паттерны

- Оба флага claim'ятся вместе под одним `claimed_congrats` boolean (`:41`) — не claim'ятся независимо. Развязка «sandbox считается для celebration, но не для tip» потребует либо двух отдельных WHERE-условий, либо отдельного precondition для tip-claim'а вместо простого piggyback на `claimed_congrats`.
- `send_trainer_share_catalog_tip_to_chat` уже умеет ветвиться на `TRAINER_SHARE_CATALOG_TIP_BOTH_HTML` / `..._DEEP_ONLY_HTML` / `..._ACTIVE_HIDDEN_FROM_CATALOG_HTML` — `DEEP_ONLY` естественно подходит и для сейчас-early-return ветки.

### Implications

- Минимальный фикс (б): либо перенести claim `share_catalog_tip_sent_at` внутрь `share_catalog_tip.py` (claim-then-send вместо fire-and-forget), либо вообще убрать early return и всегда отправлять `TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML` не-active тренеру (переиспользует готовый constant, не требует переноса DB claim — проще).
- Для (а): решение неочевидно из кода — докстринг в `booking_use_cases.py:559-560` говорит, что sandbox *должен* давать celebration. Нужно clarify, распространяется ли это на `share_catalog_tip_sent_at`, или там нужен раздельный claim.

## Открытые вопросы

- Q-001: Должен ли sandbox по-прежнему давать celebration-карточку (congrats), как явно задокументировано в `booking_use_cases.py:559-560`, или задача трактует это намерение как устаревшее/неверное и требует исключить sandbox из обоих флагов? — Affects: scope decision (a)
- Q-002: Если celebration для sandbox остаётся, нужно ли отвязать показ congrats-UI от claim'а `first_booking_milestone_at`/`share_catalog_tip_sent_at` в БД (показывать один раз за демо, но не тратить флаги, зарезервированные для настоящей первой записи)? Текущий код не поддерживает такое разделение — `_send_first_booking_milestone_followups` управляется исключительно булевыми `(milestone, share_tip)` из DB claim'а, без сигнала «это был sandbox». — Affects: scope decision (a), возможен новый flag на trainer_profiles
- Q-003: Фикс бага (б) — вариант (i) перенести claim `share_catalog_tip_sent_at` в `share_catalog_tip.py` (claim-then-send) или вариант (ii) никогда не делать early return, всегда слать `TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML` не-active тренеру? Кодовая база не даёт сигнала, что предпочтительнее — вариант (ii) проще (готовый constant, не требует переноса DB claim). — Affects: scope decision (b)

## Решения по открытым вопросам (без остановки на clarify — по явному запросу пользователя «на твоё усмотрение»)

- **Q-001/Q-002 (sandbox vs milestone)**: sandbox исключён из COUNT в claim-запросе — оба флага (`first_booking_milestone_at`, `share_catalog_tip_sent_at`) теперь резервируются строго за настоящей первой записью. Специальную «демо-celebration» UX для sandbox не строил — это explicitly scope TASK-011. Новый флаг на trainer_profiles не заводил — не понадобился при этом решении. Побочный эффект: `maybe_grant_referral_first_booking_bonus` тоже больше не срабатывает на sandbox — это корректнее по сути (реферальный бонус за настоящего клиента, не демо), тестов на это нет, не ломается.
- **Q-003 (early return)**: выбран вариант (ii) — early return в `share_catalog_tip.py` убран, всегда отправляется уже существующий `TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML`. Не переносил DB claim (вариант i) — более инвазивно, задело бы второй call site (`confirm_booking`).

## Acceptance Criteria

- [x] Sandbox-запись (демо) не претендует на `first_booking_milestone_at`/`share_catalog_tip_sent_at` — флаги остаются NULL до настоящей первой записи
  - `src/application/trainer_first_booking_milestone.py:29-33` — добавлен `AND NOT b.is_sandbox` в COUNT
- [x] Настоящая первая запись (после любого числа sandbox) claim'ит оба флага корректно
  - Покрыто тестом `test_sandbox_booking_does_not_claim_milestone_but_real_first_booking_does`
- [x] Тренер в `pending_profile`/не-active получает личную ссылку вместо молчаливого пропуска
  - `src/bot/share_catalog_tip.py:60-67` — early return заменён на отправку `TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML`
- [x] Тесты на оба пути
  - `tests/integration/test_trainer_first_booking_milestone.py` — обновлён sandbox-тест
  - `tests/bot/test_share_catalog_tip.py` — новый тест на deep-link для pending-тренера

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
- **RESEARCH** — исследованы transaction flow claim'а флагов, условия early-return в share_catalog_tip.py, представление is_sandbox и работоспособность личной ссылки для pending_profile. Найден конфликт: докстринг в booking_use_cases.py:559-560 документирует sandbox как намеренно учитываемый для celebration — это усложняет исходную формулировку бага (а). Баг (б) подтверждён независимо от решения по (а). Добавлено 3 открытых вопроса (Q-001..Q-003) для clarify.
- **IMPLEMENT** — по запросу пользователя открытые вопросы решены напрямую (см. раздел «Решения по открытым вопросам»), без отдельного прохода /clarify
  - ✓ `trainer_first_booking_milestone.py`: COUNT в claim-запросе исключает `is_sandbox`; синхронизирован diagnostic-хелпер `count_confirmed_or_completed_bookings`
  - ✓ `share_catalog_tip.py`: early return для не-active тренера заменён на отправку `TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML` (докстринг функции уже описывал это как intended-поведение — реализация ему не соответствовала)
  - ✓ Найден и обновлён существующий regression-тест, явно проверявший старое поведение (`test_sandbox_first_trainer_booking_claims_milestone_once` → `test_sandbox_booking_does_not_claim_milestone_but_real_first_booking_does`)
  - ✓ Добавлен новый тест `tests/bot/test_share_catalog_tip.py` на путь pending-тренера
- **VERIFY** — поднят Docker Postgres (`docker compose up -d postgres`), применены миграции на `trainer_crm_test`, тесты реально прогнаны
  - ✓ `tests/integration/test_trainer_first_booking_milestone.py` (3) + `tests/bot/test_share_catalog_tip.py` (1) — все 4 PASSED
  - ✓ Широкий regression: `tests/integration/ tests/application/ tests/bot/` — 674 passed, 46 skipped, 0 failed
  - ✓ Найден и исправлен баг в самом тесте (не в production-коде): `share_catalog_tip.py` делает `from src.infrastructure.db import async_session_factory` — локальная привязка, которую module-wide патч в conftest не покрывает (та же ловушка, о которой предупреждает докстринг `_apply_test_session_factory`); тест явно перепатчивает `src.bot.share_catalog_tip.async_session_factory`
  - ✓ Full suite `tests/` — 15 failures, все в `test_webapp_client_miniapp_integration.py` ("основная площадка не настроена"); подтверждено git stash'ем, что это pre-existing failures, воспроизводятся и на немодифицированном коде — не связаны с TASK-006
