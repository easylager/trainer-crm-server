# Ops: сдвиг trial-часов для одного тренера (TASK-221)

После деплоя миграции `0226_trial_clock_started_at` существующие тикающие trial получают
`trial_clock_started_at = started_at` (часы уже идут). На проде нужно **точечно** перевести
одного тренера в pending (часы ещё не начаты), если у него ещё не было real `completed`.

Подставьте `:trainer_id` (Q-002).

## 1) Проверка

```sql
SELECT ts.id, ts.trainer_id, ts.status, ts.started_at, ts.expires_at,
       ts.trial_clock_started_at, sp.is_trial
FROM trainer_subscriptions ts
JOIN subscription_plans sp ON sp.id = ts.plan_id
WHERE ts.trainer_id = :trainer_id
ORDER BY ts.id;

SELECT COUNT(*) AS real_completed
FROM bookings
WHERE trainer_id = :trainer_id
  AND status = 'completed'
  AND NOT COALESCE(is_sandbox, false);
```

## 2a) Ещё не было real completed → pending (полный доступ, часы не тикают)

```sql
UPDATE trainer_subscriptions AS ts
SET trial_clock_started_at = NULL,
    started_at = NOW(),
    expires_at = TIMESTAMPTZ '2099-01-01 00:00:00+00',
    status = 'trial'
FROM subscription_plans sp
WHERE ts.trainer_id = :trainer_id
  AND ts.plan_id = sp.id
  AND sp.is_trial = true
  AND ts.status IN ('trial', 'active', 'past_due');
```

Часы стартуют сами на первой real `completed` (код `maybe_start_trial_clock_on_completed_booking`).

## 2b) Real completed уже была → запустить N дней от сейчас

N берите из `resolve_trial_period_days` / `platform_settings.welcome_trial_period_days` (обычно 14):

```sql
UPDATE trainer_subscriptions AS ts
SET trial_clock_started_at = NOW(),
    started_at = NOW(),
    expires_at = NOW() + (:n_days || ' days')::interval,
    status = 'trial'
FROM subscription_plans sp
WHERE ts.trainer_id = :trainer_id
  AND ts.plan_id = sp.id
  AND sp.is_trial = true;
```

## 3) Платящих не трогать

Если есть active paid-строка — этот ops не применять.
