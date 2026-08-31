---
task_id: TASK-012
title: Предоплаченный welcome-grant активируется молча — тренер не видит подтверждения
status: READY
phase: new
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Показывать подтверждение активации платной подписки при открытии welcome-ссылки с предоплаченным грантом независимо от статуса тренера. Сейчас оплаченный срок начинает течь с момента открытия ссылки, а тренер не получает ни подтверждения, ни даты окончания, ни состава тарифа.

## Business Context

Тренер, которому админ выдал предоплаченный доступ до прохождения модерации, платит и не видит вообще ничего. Хуже: период считается от момента открытия ссылки, то есть у него уже идёт оплаченное время, о котором ему не сообщили.

## Scope

### In Scope

- Ветвление после `consume_link_token` в `cmd_start` (`src/bot/handlers/trainer_handlers.py`)
- Показ `TRAINER_WELCOME_PAID_GRANT_ACTIVATED` для не-active тренеров
- Совмещение подтверждения оплаты с онбординговым hero (порядок и количество сообщений)

### Out of Scope

- Выпуск грантов админом (`issue_trainer_welcome_link_token`) — работает
- Триальная ветка того же участка — TASK-009

## Comprehension Tips

### Facts

- `src/bot/handlers/trainer_handlers.py` (блок после успешного `consume_link_token`, ~строки 686-745): вызывается `apply_pending_welcome_grant_for_token`, считаются `grant_kind`, `grant_result`, `paid_ok = grant_kind == WELCOME_GRANT_KIND_PAID and not grant_result.get("error")`.
- Дальше `if state == TrainerAccessState.ACTIVE:` — только внутри этой ветки `paid_ok` используется и отправляется `msg.TRAINER_WELCOME_PAID_GRANT_ACTIVATED`. В `else` (все не-active) `grant_result` и `paid_ok` не читаются вообще: уходит только `trainer_first_link_onboarding_html`.
- `src/bot/messages.py:2319-2323` — текст гранта: «💳 Подписка активирована — {label}. Доступ открыт до {expires_date}. **Срок считается с момента открытия этой ссылки.**» То есть биллинговый триггер — именно открытие, и он срабатывает молча.
- Грант выдаётся на существующий `trainer_id` (`issue_trainer_welcome_link_token` проверяет наличие строки в `trainers`), а свежесозданный тренер имеет статус `pending_profile` (`TRAINER_STATUS_PENDING_PROFILE` в `src/application/trainer_link_token_use_cases.py`) — то есть не-active сценарий здесь основной, а не редкий.
- `paid_ok` также подавляет `ensure_trainer_welcome_trial`, так что при пропущенном сообщении тренер не увидит ни платного подтверждения, ни триального.

### Implications

- Правка локальная: вынести показ платного гранта из ветки `ACTIVE`, как и в TASK-009 для триала. Делать эти две задачи имеет смысл вместе — один и тот же блок кода.
- Нужно решить порядок сообщений: подтверждение оплаты должно идти первым, hero онбординга — вторым (или слиться в одно).
- Проверить, есть ли тесты на `apply_pending_welcome_grant_for_token` с не-active тренером.

## Acceptance Criteria

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
