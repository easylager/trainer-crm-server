# Lead Mode: post-trial revenue retention layer

**Статус:** дизайн зафиксирован, готов к разбивке на фазы.
**Зафиксировано:** 2026-04-26.
**Parent:** [subscription-model-reverse-trial.md](./subscription-model-reverse-trial.md) (детализирует, что значит `free` состояние).
**Связано с:** [telegram-paywall-daily-digest-monetization.md](./telegram-paywall-daily-digest-monetization.md).

Этот документ описывает **операционную и продуктовую архитектуру post-trial состояния**. В терминах parent-документа — это слой `free` state, превращённый из «re-engagement канала» в полноценный **Catalog-only fallback** с Graceful Degradation.

---

## 1. Суть в одном абзаце

После окончания trial тренер не выпадает из системы — он переходит в **Lead Mode**: профиль остаётся в каталоге, существующие обязательства (записи, абонементы, уведомления клиентам) корректно дорабатывают свой жизненный цикл, новые операционные действия закрыты. Тренер видит read-only operational view + recap демонстрационных сигналов («за 14 дней: 23 просмотра, 6 переходов в Telegram, 2 клиента хотели записаться»). Публичная карточка остаётся discoverable, но CTA «Записаться» меняется на «Написать в Telegram». Серия recovery-нуждов (D+0/+3/+7/+14/+30) построена на loss framing, а не на billing CTA.

> **Ключевой инсайт:** unpaid trainer = supply asset. Lead Mode = reactivation engine, а не урезанный тариф.

---

## 2. Продуктовые принципы (зафиксированы)

| Принцип | Что значит |
|---|---|
| **Existing commitments honored** | Записи, абонементы, уведомления клиентам — продолжают жить до естественного завершения. |
| **New operations restricted** | Новые записи / новые продажи абонементов / редактирование расписания / online booking — закрыты. |
| **Operational read-only view** | Тренер видит ближайшие записи, активных клиентов, остатки абонементов — но не может создавать новое. |
| **Catalog stays public** | Профиль discoverable. CTA «Записаться» → «Написать в Telegram». |
| **Proof of demand visible** | Анонимные счётчики (просмотры карточки, переходы в Telegram, заявки) — must-have для retention. |
| **Loss framing, not billing CTA** | «Вернуть онлайн-запись», а не «Купить подписку». |
| **Reverse Freemium** | Free = presence, Paid = control. |

> «Пользователь должен чувствовать не "меня отключили", а "новые инструменты остановлены, но текущая работа не сломана".»

---

## 3. Lifecycle states (mapping на текущий код)

`LifecycleStage` — derived value object. Никаких новых колонок в БД, состояние вычисляется из существующих полей `Trainer` + `trainer_subscriptions`.

| Stage | trainer.status | active subscription | trainer.is_catalog_visible | UX режим |
|---|---|---|---|---|
| `ONBOARDING` | `pending` | none | irrelevant | мастер заполнения |
| `ACTIVE` | `active` | trial / active | true | Pro UI (как сейчас) |
| **`LEAD_MODE`** | `active` | none / past_due | true | Lead UI (этот документ) |
| `CHURNED` | `inactive` / `banned` | irrelevant | false | системные сообщения |

**Где живёт derivation:** `src/application/lifecycle_use_cases.py` → `resolve_lifecycle_stage(session, trainer_id) -> LifecycleStage`.

**Все существующие gates** (`trainer_has_crm_access`, `trainer_allows_online_booking`, `trainer_has_analytics_access`, `trainer_has_groups_access`) переезжают на `stage.allows(Capability.X)`. Старые функции остаются как тонкие обёртки — обратной совместимости ради.

---

## 4. Capability matrix (Lead Mode vs Pro)

Решение зафиксировано: **в Lead Mode теряются ВСЕ модули единым пакетом**, гранулярных подписок после истечения нет.

| Capability | Lead Mode | Pro | Тип gate |
|---|:---:|:---:|---|
| **Видимость и demand layer** ||||
| Профиль в каталоге | ✅ | ✅ | derived |
| Получать `client_requests` (broadcast) | ✅ | ✅ | none |
| Видеть recap спроса (просмотры/переходы за период) | ✅ basic | ✅ extended | derived |
| Loss banner («N клиентов хотели записаться, но не смогли») | ✅ | — | derived |
| **Existing operations (read-only)** ||||
| Видеть ближайшие записи | ✅ read-only | ✅ | derived |
| Видеть активных клиентов | ✅ read-only | ✅ | derived |
| Видеть остатки абонементов | ✅ read-only | ✅ | derived |
| Уведомления уже-записанным клиентам | ✅ | ✅ | none |
| Завершение wrap-up по уже-проведённой тренировке | ✅ minimal | ✅ full | derived |
| **Control layer (закрыто)** ||||
| Создать новую запись | — | ✅ | hard |
| Редактировать расписание / шаблон недели | — | ✅ | hard |
| Online-запись клиентов в карточке | — | ✅ | hard |
| Полный CRM (заметки, история, продажи абонементов) | — | ✅ | hard |
| Аналитика выручки | — | ✅ | hard |
| Группы | — | ✅ | hard |
| Кастомизация уведомлений | — | ✅ | hard |
| Сертификаты / подарочные занятия | — | ✅ | hard |

---

## 5. Demand signals: какие и как

**Минимум для MVP:**

| Сигнал | Источник | Тип | Где собираем |
|---|---|---|---|
| `profile_view` | `GET /public/trainer/{slug}` | append-only event | `src/api/routes/public.py` middleware |
| `contact_click` | redirect `/r/tg/{trainer_id}?ref=catalog` | append-only event | новый endpoint в public.py |
| `booking_attempt_blocked` | публичный slot endpoint при `online_booking_available=false` | append-only event | `src/api/routes/webapp.py:943-954` |
| `client_request_received` | уже хранится в `client_requests` | существующее | используем агрегаты |

### Privacy: анонимные счётчики

- **Никакого user-level tracking.** Не привязываем к `client_id` / `tg_id` посетителя.
- **Дедуп в окне 24ч** через `dedup_hash` = `sha256(ip || user_agent || trainer_id || day)` — это не PII (необратимо, узкое окно). Цель: не считать F5 как 50 просмотров.
- IP/UA сами **не сохраняются**, только хеш.

### Хранение: append-only events + materialized aggregates

Одна таблица `trainer_demand_events`:

```sql
CREATE TABLE trainer_demand_events (
  id           BIGSERIAL PRIMARY KEY,
  trainer_id   BIGINT NOT NULL REFERENCES trainers(id) ON DELETE CASCADE,
  kind         VARCHAR(40) NOT NULL,  -- profile_view | contact_click | booking_attempt_blocked
  occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  source       VARCHAR(40),           -- catalog | direct_link | search | bot
  dedup_hash   CHAR(64),              -- sha256, для дедупа в окне
  payload      JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX ix_demand_events_trainer_time ON trainer_demand_events(trainer_id, occurred_at DESC);
CREATE INDEX ix_demand_events_kind_time ON trainer_demand_events(kind, occurred_at DESC);
CREATE UNIQUE INDEX ux_demand_events_dedup ON trainer_demand_events(trainer_id, kind, dedup_hash) WHERE dedup_hash IS NOT NULL;
```

**Агрегаты** (last 7d / 14d / 30d) считаются on-demand с TTL-кешированием в памяти процесса (диапазон чисел маленький, без Redis).

**Антипаттерн (избегаем):** UPDATE `trainers SET view_count = view_count + 1` — lock contention при параллельных просмотрах одного популярного тренера.

---

## 6. Telegram-redirect tracking

Текущее состояние: каталог отдаёт прямой `https://t.me/...` → клик не отслеживается.

**Решение (зафиксировано):** redirect через наш домен.

```
Каталог:  <a href="/r/tg/{trainer_id}?ref=catalog">Написать в Telegram</a>
                  ↓
Endpoint: GET /r/tg/{trainer_id}?ref={ref}
            ↓
            1. record_demand_event(kind='contact_click', source=ref)
            2. 302 → https://t.me/{username} (или deep link)
```

**Не делаем:**
- JS-tracking перед открытием — ломается на iOS Safari, теряет события.
- Track в onbeforeunload — ненадёжно.

**Защита от ботов / CSRF:** rate-limit per IP (10 redirects/min), валидация `ref` против whitelist.

---

## 7. Recovery series (post-trial nudges)

Решение: **реже, но сильнее.** Лестница D+0 / D+3 / D+7 / D+14 / D+30. После — silence (раз в месяц recap, без push-spam).

| Day | Триггер | Содержание | CTA |
|---|---|---|---|
| **D+0** | `expire_subscriptions_to_past_due` → emit `LeadModeEntered` | «Пробный период закончился. Профиль остаётся в каталоге. За trial вас посмотрели N раз, M человек открыли Telegram. Чтобы снова принимать онлайн-записи —» | `Вернуть онлайн-запись` |
| **D+3** | scheduled, only if `signals_since_d0.profile_views > 0` | «За 3 дня в Lead Mode: 5 просмотров. {if blocked_attempts > 0}: 2 человека пытались записаться, но онлайн-запись отключена.{end}» | `Включить онлайн-запись` |
| **D+7** | scheduled, with loss framing | «Неделя в Lead-режиме. {views} просмотров, {clicks} переходов в Telegram. По вашей средней цене это ≈ {estimated_lost_revenue} BYN упущенной выручки.» | `Восстановить Pro` |
| **D+14** | scheduled, social proof + урок | «Тренеры с онлайн-записью получают на 60% больше записей при том же количестве просмотров.» | `Вернуться к работе` |
| **D+30** | last nudge, dignity | «Месяц в Lead Mode. Ваш профиль за это время посмотрели {views} раз. Если хотите вернуться — мы здесь.» | `Включить Pro` |
| **D+30+** | silence | monthly digest, без CTA в каждом | none |

**Cancel rule:** все будущие nudges отменяются мгновенно, как только тренер платит. Рулится через event `SubscriptionRenewed` → `cancel_pending_lead_mode_nudges(trainer_id)`.

**Where to live:** `src/application/lead_mode_recovery_use_cases.py` + интеграция в `notification_loops.py:run_subscription_expire_and_reminder_loop`.

---

## 8. Public catalog в Lead Mode

Изменения в публичной карточке тренера, когда `lifecycle_stage == LEAD_MODE`:

| Элемент | ACTIVE | LEAD_MODE |
|---|---|---|
| Profile content | как сейчас | как сейчас |
| Кнопка записи | `Записаться онлайн` | `Написать в Telegram` (через `/r/tg/...`) |
| Список услуг | с ценами и кнопкой записи | с ценами, без кнопки записи |
| Слоты `/client/slots` | реальные слоты | пустой массив + `online_booking_available: false` (уже работает) |
| Баннер | — | «Онлайн-запись временно недоступна — напишите тренеру в Telegram» |

**Никогда не пишем «Тренер недоступен», «Профиль приостановлен»** — это ломает supply.

---

## 9. Read-only operational view (trainer-home)

UX тренера в Lead Mode на странице `trainer-home`:

```
┌──────────────────────────────────────────────────┐
│ 🟡 Lead Mode                                      │
│ Пробный период закончился. Профиль работает.      │
└──────────────────────────────────────────────────┘

┌─ Спрос за 14 дней ───────────────────────────────┐
│ 23 просмотра карточки                             │
│  6 переходов в Telegram                           │
│  2 клиента хотели записаться, но не смогли  ←─── loss framing
│                                                   │
│ [ Вернуть онлайн-запись ]                         │
└──────────────────────────────────────────────────┘

┌─ Что происходит сейчас ──────────────────────────┐
│ Ближайшие записи (read-only):                     │
│  • Завтра 18:00 — Максим                          │
│  • Завтра 19:30 — Алина                           │
│ Активных клиентов: 12 (read-only)                 │
│ Активных абонементов: 8                           │
└──────────────────────────────────────────────────┘

[ Все pro-кнопки имеют замок и ведут на recovery CTA ]
```

**Принципы UX:**
- Кнопки не пропадают — они приобретают замок и tooltip «Доступно в Pro».
- Клик по locked-кнопке → один экран с recap и CTA «Включить Pro», без многошаговых wizards.
- Никаких «срочно!», «осталось X часов!». Дайте тренеру дышать.

---

## 10. Архитектура (как это ложится в код)

Без отдельного `domain/` слоя (его в проекте нет) — следуем существующему стилю с use-cases и raw SQL.

### Новые файлы

```
src/application/
├── lifecycle_use_cases.py
│   ├── LifecycleStage (StrEnum)
│   ├── Capability (StrEnum)
│   ├── resolve_lifecycle_stage(session, trainer_id) -> LifecycleStage
│   └── stage_allows(stage, capability) -> bool
│
├── demand_signals_use_cases.py
│   ├── record_profile_view(session, trainer_id, source, dedup_key)
│   ├── record_contact_click(session, trainer_id, source, dedup_key)
│   ├── record_booking_attempt_blocked(session, trainer_id, source)
│   ├── get_signals_recap(session, trainer_id, window_days) -> SignalsRecap
│   └── get_signals_for_recovery_message(session, trainer_id, since)
│
└── lead_mode_recovery_use_cases.py
    ├── build_lead_mode_message_d0(trainer_id, signals)
    ├── schedule_lead_mode_nudges(trainer_id, baseline_at)
    └── cancel_pending_nudges(trainer_id)

src/infrastructure/repositories/
└── demand_signals_repository.py
    ├── insert_event(...)
    └── aggregate_window(trainer_id, kinds, since, until) -> dict

src/api/routes/
├── public.py             [интеграция record_profile_view]
└── tracking.py [новый]   [GET /r/tg/{trainer_id}]

migrations/versions/
└── 0124_demand_events.py
```

### Обновляемые файлы

| Файл | Что меняется | Когда (фаза) |
|---|---|---|
| `subscription_tier_use_cases.py` | существующие `trainer_has_*_access` остаются как level-2 модульные gates; `lifecycle_use_cases.trainer_can` — новый level-1 композитор | Phase 2 ✅ |
| `application/lifecycle_use_cases.py` | LifecycleStage / Capability / LifecycleSnapshot / resolve_* / stage_allows / trainer_can | Phase 2 ✅ |
| `api/routes/redirects.py` | `GET /r/tg/{trainer_id}` — best-effort `record_contact_click` + 302 на `https://t.me/{username}`. Source resolved из ?src= или Referer. | Phase 4 ✅ |
| `api/routes/public.py` | `GET /api/public/trainers/{id}` пишет `profile_view` и отдаёт `lifecycle_stage`/`is_lead_mode`/`contact_telegram_url` | Phase 4 ✅ |
| `static/webapp/catalog-main.js` | Lead Mode CTA «Написать в Telegram» в trainer detail, fallback на «Оставить заявку» если нет username | Phase 4 ✅ |
| `notification_loops.py` | `JUST_EXPIRED` удалён, добавлен `run_lead_mode_recovery_loop` (D+0/D+3/D+14/D+30) с idempotency и cancel-on-payment; loss framing на реальных числах из `SignalsRecap` | Phase 5 ✅ |
| `application/lead_mode_recovery_use_cases.py` | scheduler: `compute_due_nudges`, `mark_nudge_sent`, pure `_pick_due_step` (largest-unfired semantics) | Phase 5 ✅ |
| `migrations/0125_trainer_recovery_nudges.py` | idempotency log: UNIQUE(trainer_id, step) | Phase 5 ✅ |
| `messages.py` | `TRAINER_LEAD_MODE_RECOVERY_D0_TRIAL/PAID/D3/D14/D30` + signals-line builders | Phase 5 ✅ |
| `trainer-home-main.js` + `trainer-home.html` | Lead Mode banner + signals recap + loss framing + recovery CTA | Phase 3 ✅ |
| `webapp.py` | `GET /api/webapp/trainer/lifecycle` + `lifecycle` в `/trainer/hub/bootstrap` (signals_recap window: 14d active / since_lead_mode in Lead Mode) | Phase 3 ✅ |
| `public.py` | record_profile_view + Lead Mode CTA в трейнерской карточке | Phase 4 |
| `infrastructure/db/models.py` | модель `TrainerDemandEvent` | Phase 1 |

---

## 11. Phased roll-out

| # | Фаза | Что доставляет | Зависит от |
|---|---|---|---|
| **1** ✅ | **Demand Signals foundation** | Миграция `trainer_demand_events`, модель, use-cases, repository, dedup. Без интеграции в UI. | — |
| **2** ✅ | **LifecycleStage + capability gates** | `LifecycleStage` enum, `Capability` enum, `LifecycleSnapshot` dataclass, `resolve_lifecycle_*`, `stage_allows`, композитор `trainer_can`. Без UI изменений и без рефактора существующих gates (мигрируем callsites постепенно). | 1 |
| **3** ✅ | **Lead Mode WebApp UI (trainer-home)** | `GET /api/webapp/trainer/lifecycle` + `lifecycle` field в bootstrap. Trainer-home показывает Lead Mode banner: signals recap (просмотры / Telegram-клики), loss framing (`Эти {N} человек могли записаться онлайн`) и recovery CTA «Вернуть онлайн-запись». | 1, 2 |
| **4** ✅ | **Public catalog Lead Mode + tracking redirect** | `GET /r/tg/{trainer_id}` редирект на `https://t.me/{username}` с записью `contact_click`. `GET /api/public/trainers/{id}` возвращает `lifecycle_stage`/`is_lead_mode`/`contact_telegram_url` и пишет `profile_view` (deduped по IP+UA+day). Frontend `catalog-main.js` показывает CTA «Написать в Telegram» вместо «Записаться» в Lead Mode. | 1, 2 |
| **5** ✅ | **Recovery nudge series engine** | Серия D+0/D+3/D+14/D+30: миграция `trainer_recovery_nudges` (UNIQUE idempotency), `lead_mode_recovery_use_cases` со scheduler-ом «largest-unfired offset», новый `run_lead_mode_recovery_loop` в notification_service. Старый `JUST_EXPIRED` удалён. Cancel-on-payment имплицитный (re-subscribed тренеры выпадают из candidate-list). Loss framing на реальных числах из `SignalsRecap` через `_render_recovery_signals_line` (трёхуровневая правда: views+clicks / только views / нет демона → пустая строка). | 1, 4 |
| **6** | **Read-only ops view (CRM/calendar/clients)** | На страницах calendar/clients — полное скрытие edit-actions для Lead Mode, read-only режим. | 2 |
| **7** | **Reactivation analytics (admin)** | Дашборд: сколько в Lead Mode, reactivation rate, MRR recovered, top-converting nudges. | 1, 5 |

**Минимум видимой ценности:** фазы 1 → 3 → 4. Фаза 5 — main retention-движок. Фаза 7 — для оптимизации.

---

## 12. Метрики

### Продуктовые
- **Lead Mode population** — # тренеров в Lead Mode (gauge, daily snapshot)
- **Lead → Pro reactivation rate** — % из Lead Mode, кто оплатил в течение 30/60/90 дней (cohort)
- **Demand visibility per Lead trainer** — median(profile_views per 14d) в Lead Mode
- **Recovery nudge CTR** — отдельно по D+0/+3/+7/+14/+30 (главный сигнал какое framing работает)
- **MRR recovered** — сумма платежей от ре-активированных Lead Mode тренеров

### Инженерные
- `trainer_demand_events` write latency p95 < 50ms (не должно тормозить публичную карточку)
- dedup hit rate > 30% (если меньше — дедуп не работает / окна слишком короткие)
- `/r/tg/*` redirect availability ≥ 99.5%

---

## 13. Open questions (на момент фиксации)

1. **Loss framing с числами.** Формула «estimated_lost_revenue» = `blocked_attempts * avg_session_price`. У всех ли тренеров есть `avg_session_price`? Что показываем тем, у кого нет?
2. **D+0 момент**. Триггер сейчас раз в сутки в `run_subscription_expire_and_reminder_loop`. Это ОК для большинства, но в худшем случае — задержка ~24ч. Достаточно или нужно почасово?
3. **Что с `trainer.status='active' AND no subscription` от рождения** (не было trial вообще, или был и истёк давно)? Они тоже в Lead Mode? — Да, по логике.
4. **Hot reactivation (тот же день).** Если тренер оплачивает в день D+0 до отправки nudge — отменять ли запланированные D+3/+7? — Да (см. cancel rule §7).
5. **«Read-only CRM»** — какой именно scope? Видеть всех клиентов или только активных? Видеть финансовые цифры или скрыть? Финализация в Phase 6.
6. **Анонимность tracking-события** при авторизованном клиенте через webapp — всё равно не привязываем к user_id? — Да, по решению §5 (анонимные счётчики).
7. **Отдельный `lead_mode_entered_at` timestamp** на тренере или вычисляется как `last_subscription.expires_at`? — Вычисляем, не дублируем.

---

## 14. Что специально **не** делаем

- Отдельная сущность `lead_mode_state` в БД — не нужна, всё derived.
- Email/SMS-каналы recovery series — только Telegram (как и в parent-документе).
- A/B на копирайт recovery в Phase 1–5 — только после ≥500 тренеров в Lead Mode.
- Customer self-service для Lead Mode (паузу можно поставить вручную) — не сейчас, добавляем когда появятся жалобы.
- Win-back через email/звонки операторов — отдельная инициатива, не этот документ.

---

## 15. Связи с другими документами

- **[subscription-model-reverse-trial.md](./subscription-model-reverse-trial.md)** — parent: модель тарифов, состояния `trial/pending/pro/starter/free`. Lead Mode = детализация состояния `free`.
- **[telegram-paywall-daily-digest-monetization.md](./telegram-paywall-daily-digest-monetization.md)** — paywall copy и digest-anchor: расширяем своим Lead Mode digest и CTAs.
