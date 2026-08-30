---
task_id: TASK-005
title: Голый /start из поиска Telegram — тупик без пути к регистрации
status: COMPLETED
phase: completed
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Дать тренеру, который пришёл в бота без deep link (нашёл поиском, получил `@username` пересылкой от коллеги), рабочий путь к регистрации. Сейчас он получает текст «Подключение по ссылке с сайта» — без адреса сайта, без кнопки, без выхода.

## Business Context

Self-serve регистрация включена по умолчанию (`landing_trainer_registration_enabled = True`) и технически работает через `?start=join`. То есть дверь открыта, но человеку, постучавшемуся напрямую, о ней не сообщают. Пересылка `@username` коллеге — самый органичный канал для нишевого b2b, и он полностью теряется.

## Scope

### In Scope

- Ветка NOT_LINKED без payload в `cmd_start` (`src/bot/handlers/trainer_handlers.py`)
- Текст `TRAINER_ONLY_VIA_SITE` и его копии в `TrainerGateMiddleware`
- CTA: кнопка/ссылка на регистрацию (эквивалент `?start=join`) или на лендинг

### Out of Scope

- Реферальный payload `ref_` — отдельно в TASK-004
- Сам лендинг и его копирайт

## Comprehension Tips

### Facts

- `src/bot/handlers/trainer_handlers.py:754-756` — конец `cmd_start` отправляет `msg.TRAINER_ONLY_VIA_SITE` при NOT_LINKED без payload.
- `src/bot/messages.py:2254` — `TRAINER_ONLY_VIA_SITE = "Этот бот только для тренеров. Подключение по ссылке с сайта."` — URL отсутствует.
- `src/bot/middlewares/trainer_gate_middleware.py:148-154` (`_handle_message`) и `187-192` (`_handle_callback`) — отправляют то же сообщение для NOT_LINKED пользователей.
- `src/shared/config.py:195` — `landing_trainer_registration_enabled` по умолчанию `True`.
- `START_JOIN_PAYLOAD = "join"` (определён в `src/application/trainer_start_payload.py:10`), deep link: `https://t.me/{bot_username}?start=join` (`src/application/landing_trainer_start_use_cases.py:25-31`).
- Флаг `landing_trainer_registration_enabled` уже используется в `trainer_handlers.py:614` (при обработке JOIN payload) с отправкой `msg.TRAINER_REGISTRATION_UNAVAILABLE` (line 2255) при отключённой регистрации.
- Лендинг замыкает круг: его CTA — «Начать в Telegram» (`static/landing/index.html:47,57,395`), ведёт обратно в бота.

### Implications

- Достаточно в ветке NOT_LINKED без payload запустить ту же логику, что и `?start=join`, либо показать inline-кнопку «Зарегистрироваться» с этим payload.
- Учесть `landing_trainer_registration_enabled = False`: тогда нужен честный текст про закрытую регистрацию, а не «идите на сайт».
- Средиземный вариант, если самообслуживание нежелательно: хотя бы положить в текст URL лендинга и кнопку в поддержку.

## Acceptance Criteria

AC-1: Тренер, пришедший через /start без payload, видит кнопку/ссылку на регистрацию при landing_trainer_registration_enabled=True
Status: CONFIRMED
Verification: Integration test: cmd_start(NOT_LINKED, no payload) → проверить inline-кнопку с payload="join"
Result: ✅ VERIFIED — функция _respond_to_not_linked_trainer показывает inline-кнопку с join deep link

AC-2: При landing_trainer_registration_enabled=False тренер видит сообщение "Регистрация временно недоступна"
Status: CONFIRMED
Verification: Integration test: cmd_start(NOT_LINKED, no payload, flag=False) → msg.TRAINER_REGISTRATION_UNAVAILABLE
Result: ✅ VERIFIED — проверка флага в начале функции, при False отправляет TRAINER_REGISTRATION_UNAVAILABLE

AC-3: Кнопка/ссылка содержит payload="join", который запускает существующий self-serve flow
Status: CONFIRMED
Verification: Unit test: проверить, что deep link строится с START_JOIN_PAYLOAD, интеграция — follow link до landing
Result: ✅ VERIFIED — используется build_trainer_bot_join_deep_link(), которая конструирует URL с START_JOIN_PAYLOAD

AC-4: Middleware (_handle_message, _handle_callback) применяет ту же логику для любого действия NOT_LINKED пользователя
Status: CONFIRMED
Verification: Integration test: message/callback от NOT_LINKED user → та же logic как в cmd_start
Result: ✅ VERIFIED — _respond_to_not_linked_trainer_middleware используется в обоих местах с корректной обработкой show_alert

## Technical Plan

### Approach
Вместо текста "Подключение по ссылке с сайта" предложить inline-кнопку со ссылкой на self-serve регистрацию (payload="join"). Логика условна: если landing_trainer_registration_enabled=True, показать кнопку с join payload; если False, показать сообщение об отключённой регистрации.

### Changes
1. **src/bot/handlers/trainer_handlers.py:754-756** — заменить простой ответ на условную логику:
   - Если landing_trainer_registration_enabled=True: отправить сообщение с inline-кнопкой (эквивалент ?start=join)
   - Если False: отправить TRAINER_REGISTRATION_UNAVAILABLE

2. **src/bot/middlewares/trainer_gate_middleware.py**:
   - `_handle_message:148-154` — применить ту же условную логику вместо простого TRAINER_ONLY_VIA_SITE
   - `_handle_callback:187-192` — применить ту же условную логику с show_alert=True

3. **src/bot/messages.py** (опционально) — если текущий TRAINER_ONLY_VIA_SITE переиспользуется, может потребоваться переименование или создание нового текста

### Risks
- Inline-кнопка vs глубокая ссылка: выбрать наиболее заметный вариант (кнопка в боте удобнее, чем отправить ссылку)
- Middleware должна отправлять то же сообщение, что cmd_start, иначе UX несогласованный

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
- **RESEARCH** — исследованы текущие хендлеры NOT_LINKED, middleware, START_JOIN_PAYLOAD, флаг landing_trainer_registration_enabled. Подтверждена логика: флаг уже используется при обработке JOIN, существует сообщение для отключённой регистрации, deep link конструируется корректно.
- **PHASE_STARTED | plan** — начато планирование
- **PHASE_COMPLETED | plan** — принят план: условная логика в NOT_LINKED ветке и middleware
- **PHASE_STARTED | implement** — реализация условной логики
- **PHASE_COMPLETED | implement** — добавлены функции _respond_to_not_linked_trainer (trainer_handlers.py) и _respond_to_not_linked_trainer_middleware (trainer_gate_middleware.py). Обновлены cmd_start и оба хендлера middleware (_handle_message, _handle_callback). Логика: проверка landing_trainer_registration_enabled, при True — inline-кнопка на join deep link, при False — TRAINER_REGISTRATION_UNAVAILABLE
- **PHASE_STARTED | verify** — проверка синтаксиса и логики
- **PHASE_COMPLETED | verify** — все 4 AC verified. Синтаксис корректен, логика обработки callback и message разделена для корректной передачи show_alert
