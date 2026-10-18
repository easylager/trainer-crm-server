# Выкат «Собрать компанию» (ice company)

Чеклист для человека после merge в `master`. Агент не деплоит и не меняет env.

Пайплайн и «когда клиент узнаёт»: [`docs/plans/2026-10-18-release-18-10-26-pipeline.md`](../plans/2026-10-18-release-18-10-26-pipeline.md).

## До merge

1. На ветке поезда зелёный CI, `alembic heads` — один head, ревизия `0237_ice_companies` в истории.
2. Юрист: черновик [`2026-10-16-ice-company-pdn-draft.md`](../plans/2026-10-16-ice-company-pdn-draft.md) — статус зафиксирован (ок / правки / блок рассылки).
3. Список `city_id` для пилота снят с **прод**-таблицы `cities`, не с локального сида.

## Сразу после деплоя кода (фича может быть выключена)

4. `WEBAPP_BASE_URL` — публичный `https://` без хвоста `/`. От него `page_url`, `og.png`, `event.ics` на `/k/{code}`.
5. `CLIENT_BOT_USERNAME`, Main Mini App на тот же домен — иначе `startapp=company_{session_id}` не откроет мини-апп (см. [`catalog-share-launch.md`](catalog-share-launch.md) §15).
6. Миграция на проде: `alembic upgrade head` → есть таблицы `ice_companies`, `ice_company_events`, `ice_company_responses`, `ice_company_messages`, `ice_company_reminders`.
7. Проверка CHECK аналитики (новые kind):
   ```sql
   SELECT pg_get_constraintdef(oid)
   FROM pg_constraint
   WHERE conname LIKE '%catalog_consumer%kind%'
      OR conname LIKE '%ck_catalog_consumer_events_kind%';
   ```
   В списке kind должны быть `company_created`, `card_shared`, `company_response`, … (см. миграцию `0237`).
8. Сервис **`notification_service`** запущен с тем же `DATABASE_URL`, что API; в процессе есть задача `ice_company` (`run_ice_company_loop`). Без него карточки в чатах не обновляются.
9. Клиентский **бот** задеплоен с роутером `ice_company_handlers` (inline `k:{code}`, callback `ic:`).

## Включение города

10. На **API** и **`notification_service`** задать одинаково, например:
    ```text
    ICE_COMPANY_CITY_IDS=1
    ```
    (значения — через запятую, без пробелов; пусто = фича выключена для создания).
11. Опционально: `ICE_COMPANY_RETENTION_DAYS` (default 30), лимиты исходящих в Telegram — см. `.env.example`.
12. Redeploy / restart обоих сервисов после смены Variables.

## ~20 минут руками (пилотный город)

13. **Мини-апп:** каток в включённом городе → карточка арены → сеанс в расписании → кнопка **«Собрать компанию»** (не только «Позвать»).
14. Создать компанию (имя, порог людей) → ответ `201`, ссылка `/k/{code}`.
15. **Шаринг в Telegram:** из шита отправить компанию в тестовый чат → фото-карточка, кнопки «Иду / Не могу / На лёд».
16. Второй аккаунт жмёт «Иду» в чате → карточка **редактируется**, новое сообщение не плодится.
17. **Веб:** открыть `/k/{code}` без Telegram → форма ответа, согласие; honeypot `website` не ломает UX.
18. `GET /k/{code}/og.png` — 1200×630, не 500.
19. Город **не** в флаге: `POST /api/public/ice-companies` → `404`; кнопки на карточке нет.
20. Аналитика после шагов 14–16:
    ```sql
    SELECT kind, count(*)
    FROM catalog_consumer_events
    WHERE kind LIKE 'company_%' OR kind IN ('card_shared', 'reminder_sent', 'outbound_429')
      AND occurred_at > now() - interval '1 hour'
    GROUP BY 1
    ORDER BY 1;
    ```
    Ожидаем минимум `company_created`, `card_shared`, `company_response`.

## Release comms

21. Рассылка **не обязательна** для пилота одного города. Если шлём всем клиентам — по [`release-comms/README.md`](../release-comms/README.md): draft → preview → dry-run → send → deploy/включение флага в согласованном порядке.
22. Журнал отправки: `var/release-comms/<release_id>.clients.json` (не в git).

## Откат

23. **Мягкий:** убрать `city_id` из `ICE_COMPANY_CITY_IDS` — создание и кнопка пропадают, ссылки `/k/` остаются.
24. **Жёсткий (редко):** `MAINTENANCE_MODE` + откат деплоя API/бота; данные в `ice_*` таблицах останутся до purge по retention.
