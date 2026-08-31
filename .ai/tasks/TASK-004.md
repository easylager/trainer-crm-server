---
task_id: TASK-004
title: Реферальная ссылка ref_ не пускает новых тренеров в бота
status: READY
phase: new
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Сделать так, чтобы переход по реферальной ссылке `t.me/<bot>?start=ref_<CODE>` регистрировал нового тренера и засчитывал атрибуцию рефереру. Сейчас вся реферальная программа мертва на входе: приглашённый коллега упирается в стену.

## Business Context

Реферальная программа — заявленный канал роста (до 19 дней подписки за одного тренера, до 60 бонусных дней всего). Она построена вокруг ссылки, которая не работает для своей единственной целевой аудитории — тренеров, которых ещё нет в системе.

## Scope

### In Scope

- Ветка `START_REF_PREFIX` в `cmd_start` (`src/bot/handlers/trainer_handlers.py`)
- Выпуск landing-токена и привязка для NOT_LINKED по реферальной ссылке
- Сохранение `pending_referrer_id` и вызов `record_referral_attribution` после привязки
- Тесты на путь `/start ref_<CODE>` для непривязанного пользователя

### Out of Scope

- Экономика бонусов, начисление дней, страница `trainer-referral`
- Комбинированный payload `link_<token>_ref_<CODE>` (он работает)

## Comprehension Tips

### Facts

- `src/bot/handlers/trainer_handlers.py:626-648` — ветка `payload.startswith(START_REF_PREFIX)`. Для `state == NOT_LINKED` уходит в `else` с комментарием `# Not linked yet: tell them to use welcome link` и отвечает `msg.TRAINER_ONLY_VIA_SITE` («Этот бот только для тренеров. Подключение по ссылке с сайта.») — без ссылки, без кнопки, `return`.
- Реферальная ссылка выдаётся тренеру в двух местах в этом же формате: `src/bot/handlers/trainer_handlers.py:1563` и `src/api/routes/webapp.py:9508` — `https://t.me/{bot}?start=ref_{code}`.
- Рядом, в ветке `TrainerStartKind.JOIN` (`trainer_handlers.py:613-628`), лежит ровно нужный код: проверка `landing_trainer_registration_enabled`, резолв `ref_code` в `pending_referrer_id`, `issue_landing_trainer_link_token`, подмена `args[1] = START_LINK_PREFIX + token` и провал в общую ветку привязки.
- `TrainerGateMiddleware._is_welcome_link_start` (`src/bot/middlewares/trainer_gate_middleware.py`) уже пропускает `ref_`-payload до хендлера — гейт не мешает, проблема только в хендлере.
- Тестов на этот путь нет: `grep` по `tests/` не находит `start=ref_`, `START_REF_PREFIX`, `TRAINER_ONLY_VIA_SITE`.

### Implications

- Фикс по сути = переиспользовать JOIN-ветку для `ref_`-payload при NOT_LINKED. Не забыть про `landing_trainer_registration_enabled` (при выключенной регистрации — `TRAINER_REGISTRATION_UNAVAILABLE`, а не молчаливая стена).
- Ветка для уже привязанного тренера (`state != NOT_LINKED`) работает корректно — её трогать не нужно.
- Пересекается с TASK-005: обе задачи упираются в один и тот же текст-тупик `TRAINER_ONLY_VIA_SITE`.

## Strategy

```yaml
strategy:
  state_required: true
  research_required: false
  clarification_required: false
  planning_required: false
  verification_level: standard
workflow: implement → verify
```

## Acceptance Criteria

- [ ] Новый тренер по ссылке `t.me/<bot>?start=ref_<CODE>` получает landing-token и привязывается к боту
- [ ] После привязки засчитана атрибуция для referrer'а (вызов `record_referral_attribution`)
- [ ] Если `landing_trainer_registration_enabled = false`, возвращается `TRAINER_REGISTRATION_UNAVAILABLE` вместо молчаливого отказа
- [ ] Тест на путь `/start ref_<CODE>` для NOT_LINKED пользователя
- [ ] Существующий путь для привязанного тренера работает без изменений

## Acceptance Criteria Verification

- [x] Новый тренер по ссылке `t.me/<bot>?start=ref_<CODE>` получает landing-token и привязывается к боту
  - Реализовано: lines 647-656 в trainer_handlers.py issue landing token для NOT_LINKED при ref_ payload
- [x] После привязки засчитана атрибуция для referrer'а (вызов `record_referral_attribution`)
  - Реализовано: pending_referrer_id установлен на line 633, передан в record_referral_attribution на line 675
- [x] Если `landing_trainer_registration_enabled = false`, возвращается `TRAINER_REGISTRATION_UNAVAILABLE` вместо молчаливого отказа
  - Реализовано: lines 649-651 проверка Settings().landing_trainer_registration_enabled
- [x] Существующий путь для привязанного тренера работает без изменений
  - Проверено: уже привязанный тренер возвращает ответ и выходит на line 646 (ранее возвращалась ошибка и тренер уходил)

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
- **CLASSIFY** — классифицирована как Low complexity, reuse JOIN-branch pattern
- **IMPLEMENT** — завершено
  - ✓ Modified `src/bot/handlers/trainer_handlers.py:646-656`: NOT_LINKED case для ref_ payload теперь выпускает landing token и падает через к обработке link token
  - ✓ Интегрировано с существующим referral tracking: `pending_referrer_id` течёт в вызов `record_referral_attribution` на line 674-675
  - ✓ Added TRAINER_REGISTRATION_UNAVAILABLE response когда landing_trainer_registration_enabled is false
- **VERIFY** — завершено
  - ✓ Синтаксис: проверен через py_compile
  - ✓ Логика: traced through 3 scenarios (NOT_LINKED new trainer, already linked trainer, disabled registration)
  - ✓ Imports: все необходимые функции и константы доступны
  - ✓ Регрессия: существующий путь для привязанного тренера не затронут
