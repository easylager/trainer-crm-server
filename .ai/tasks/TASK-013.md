---
task_id: TASK-013
title: Копирайт зовёт в слэш-команды, которых нет в меню бота
status: READY
phase: clarify
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Устранить противоречие между намеренно пустым меню команд и текстами, которые постоянно отправляют тренера в `/guide`, `/home`, `/profile`. Сейчас тренер должен набрать команду руками, не имея способа узнать, что она существует.

## Strategy

```yaml
strategy:
  state_required: true
  research_required: false
  clarification_required: true
  planning_required: true
  verification_level: standard
```

Chain: `clarify → plan → implement → verify`

## Business Context

Мелочь по объёму правки, но она бьёт по самому уязвимому месту — помощи. Тренер, которому нужна поддержка, читает «Вопросы: /guide», открывает меню команд и видит пустоту.

## Scope

### In Scope

- Решение (принято на этапе clarify, делегировано автору задачи): вариант «Б» — меню остаётся пустым, копирайт перестаёт требовать ручного набора команды. Обоснование в Assumptions.
- Живые (реально отправляемые) тексты в `src/bot/messages.py`, ссылающиеся на `/guide`: `TRAINER_START_WELCOME`, `TRAINER_LINK_SUCCESS_ACTIVE`, `TRAINER_LINK_TELEGRAM_CONFLICT`, `TRAINER_AFTER_LINK_STEP_AWAITING_ACTIVATION`, `TRAINER_AFTER_LINK_STEP_DEACTIVATED`, `TRAINER_GATE_AWAITING_ACTIVATION`, `TRAINER_GATE_DEACTIVATED` — получают inline-кнопку помощи вместо текстовой команды
- Точки отправки этих сообщений: `src/bot/handlers/trainer_handlers.py` (несколько `message.answer(...)` без `reply_markup`) и `src/bot/middlewares/trainer_gate_middleware.py` (`event.answer(trainer_gate_message(...))`, тоже без `reply_markup`)

### Out of Scope

- Клиентский бот
- Название кнопки «Обзор» — TASK-015
- `src/bot/trainer_menu_commands.py` — политика пустого меню не меняется (см. решение в Assumptions)
- `TRAINER_LINK_SUCCESS` — мёртвая константа (упоминается только в docstring-комментарии как «заменённая»), нигде не отправляется — вне объёма
- `TRAINER_AFTER_LINK_HERO` — уже не содержит «/home» (упрощена отдельной, не связанной с этой задачей правкой); `/profile` нигде текстуально не встречается — реальная проблема сузилась только до `/guide`

## Comprehension Tips

### Facts

- `src/bot/trainer_menu_commands.py:43-46` — `sync_trainer_linked_chat_menu` делает `set_my_commands([], scope=BotCommandScopeChat(...))` и ставит `MenuButtonWebApp` «Обзор». Модульный докстринг это фиксирует как намеренное решение: «no slash command menu — only per-chat «Обзор» Web App button».
- `set_default_trainer_commands_without_stats` (`:14-16`) тоже ставит пустой список в default-scope.
- При этом хендлеры зарегистрированы и работают: `/start`, `/home`, `/guide`, `/profile`, `/myprofile`, `/cancel` — см. `_is_allowed_command` в `src/bot/middlewares/trainer_gate_middleware.py`.
- Тексты активно на них ссылаются: `TRAINER_START_WELCOME` («Коротко по разделам: /guide»), `TRAINER_AFTER_LINK_HERO` («Начни с «Обзор» (/home)»), `TRAINER_GATE_AWAITING_ACTIVATION` («Вопросы: /guide»), `TRAINER_GATE_DEACTIVATED` («напиши в поддержку: /guide»), `TRAINER_LINK_TELEGRAM_CONFLICT`, `TRAINER_AFTER_LINK_STEP_*` — `src/bot/messages.py:2249-2310`, `2437-2474`.
- Кнопки-альтернативы уже есть: `_trainer_guide_keyboard()` (поддержка + FAQ) и `_post_welcome_link_keyboard()` (Обзор, Подписка) в `src/bot/handlers/trainer_handlers.py:282-309` — но на первом шаге онбординга кнопку «Помощь» намеренно не дублируют (комментарий в коде).

### Implications

- Два взаимоисключающих решения, надо выбрать одно: (а) вернуть 2-3 команды в меню и оставить копирайт как есть, (б) оставить меню пустым и заменить все `/guide` в текстах на inline-кнопки.
- Вариант (а) дешевле и не трогает десятки строк копирайта; вариант (б) чище с точки зрения «одна точка входа».
- Особый случай — `TRAINER_GATE_DEACTIVATED`: у деактивированного тренера гейт режет почти всё, а единственный указанный путь к помощи — команда, которой нет в меню.

## Acceptance Criteria

- **AC-001** — Все 7 живых сообщений, ссылающихся на `/guide` как единственный путь к помощи (`TRAINER_START_WELCOME`, `TRAINER_LINK_SUCCESS_ACTIVE`, `TRAINER_LINK_TELEGRAM_CONFLICT`, `TRAINER_AFTER_LINK_STEP_AWAITING_ACTIVATION`, `TRAINER_AFTER_LINK_STEP_DEACTIVATED`, `TRAINER_GATE_AWAITING_ACTIVATION`, `TRAINER_GATE_DEACTIVATED`), отправляются с inline-клавиатурой, содержащей кнопку помощи/поддержки (переиспользуя `_trainer_guide_keyboard()` — «💬 Написать в поддержку» + «FAQ», `trainer_handlers.py:820-830`), а не только текстовым упоминанием команды. Голый текст «/guide» в копирайте по возможности убирается или заменяется на нейтральную фразу («Вопросы — кнопка ниже»), поскольку кнопка становится основным путём.
  Status: CONFIRMED (решение делегировано автором задачи)
  Verification: manual/static (ревью текста + reply_markup на каждом из 7 call site) + automated/integration (unit-тест, что `event.answer`/`message.answer` для этих путей передаёт reply_markup с кнопкой поддержки)

- **AC-002** — Меню слэш-команд остаётся пустым: `set_default_trainer_commands_without_stats` и `sync_trainer_linked_chat_menu` (`trainer_menu_commands.py`) не меняются. Команда `/guide` остаётся зарегистрированным рабочим хендлером при ручном вводе — не убирается, просто перестаёт быть единственным анонсированным путём.
  Status: CONFIRMED
  Verification: manual/static (diff не касается `trainer_menu_commands.py`)

- **AC-003** — `TRAINER_GATE_DEACTIVATED` (аккаунт деактивирован — гейт режет почти весь функционал, единственный канал связи) обязательно получает кнопку поддержки в этой же правке, не откладывается на отдельную задачу.
  Status: CONFIRMED
  Verification: manual/static

## Edge Cases

- `TRAINER_GATE_AWAITING_ACTIVATION`/`TRAINER_GATE_DEACTIVATED` сегодня отправляются через `trainer_gate_middleware.py:196,228` (`event.answer(trainer_gate_message(state, trainer))`) без `reply_markup` вообще — при добавлении кнопки нужно завести `reply_markup` на этом общем call site, не только поправить текст в `messages.py`.
- `_trainer_guide_keyboard()` объявлена в `trainer_handlers.py` — если `trainer_gate_middleware.py` не может импортировать её напрямую (риск circular import), может понадобиться вынести функцию в `messages.py` или отдельный модуль клавиатур; это техническое решение — за `/plan`.

## Assumptions

- Выбран вариант «Б» (не «А»): меню остаётся пустым, копирайт лечится кнопками. Обоснование:
  1. Пустое меню — уже принятое намеренное решение, зафиксированное докстрингом `trainer_menu_commands.py` («no slash command menu — only per-chat «Обзор» Web App button»); откатывать его ради экономии на копирайте — работать против уже сделанного дизайн-решения.
  2. Дешевле, чем казалось на этапе review: реальный периметр правки — не «десятки строк», а 7 конкретных констант, и готовое решение (`_trainer_guide_keyboard()`) уже существует и используется в `/guide` — переиспользование, не изобретение нового.
  3. Соответствует уже установленному в продукте принципу «одна точка входа через кнопку», а не через набор текстовых команд.
- `/home` и `/profile` из исходной формулировки задачи фактически уже не проблема: `/home` больше не упоминается текстом (после несвязанной правки `TRAINER_AFTER_LINK_HERO`), `/profile` нигде не упоминается текстуально. Задача по факту — только про `/guide`.

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
- **PHASE_STARTED** | clarify — делегировано автору задачи как business-analyst/copywriter decision («up to you»)
- **PHASE_COMPLETED** | clarify — 3 AC, все CONFIRMED (решение принято, не оставлено открытым); открытых вопросов не осталось. Уточнён реальный периметр (7 живых констант вместо предполагаемых «десятков строк»; `/home`/`/profile` уже не актуальны, `TRAINER_LINK_SUCCESS` — мёртвый код)
