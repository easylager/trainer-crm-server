# Выкат шаринга каталога

Чеклист для человека после мержа. Агент его не выполняет: ни деплоя, ни импорта в прод, ни смены env.

Единица шеринга — страница на нашем домене (`/c/…`, `/p/…`), не `t.me/?start=`. Превью своё. Цепочка не обрывается на первом получателе. Событие шеринга пишется по нажатию канала, не по открытию превью.

## До выката

1. `WEBAPP_BASE_URL` — публичный `https://` домен, без хвоста `/`. От него собираются `og:image`, `og:url` и ссылка в чате. Пустой или `http://` — Telegram картинку не заберёт.
2. Клиентский бот: `CLIENT_BOT_USERNAME`. Основное мини-приложение включено (`CLIENT_BOT_MAIN_MINI_APP=true`, BotFather → Main Mini App на тот же домен). Иначе «Открыть в Telegram» падает в `t.me/<bot>?start=…`, и бот отвечает одной кнопкой. `CLIENT_MINI_APP_SHORT_NAME` — только если мини-апп заведён отдельным коротким именем.
3. Фото мест: ключи в БД и объекты в бакете (или на диске процесса API) должны совпадать. Локально `GET /api/public/photos/arenas/…` часто 404 — страница дыру убирает (на `/p/` нет пустого 16:9, на `/c/` остаётся иконка типа), но в чате друг видит постер без кадра катка. Перед выкатом открыть 3–4 минских `/p/` и `/c/minsk` и убедиться, что герой и карточки грузятся, а не только иконка.
4. Магазины: `data/catalog/shops-<город>.json` сам на прод не уезжает. Если в шаринге обещаем магазины — отдельный прогон `scripts/load_catalog_shops.py` (сначала без `--apply`, потом `--apply` и явный флаг прода). Без импорта страница `/c/<город>?t=shop` честно пустая.
5. Миграции уже в линейке: `0200` — `client_share_events`, `0208` — kind `place`, `0210` — `selection`, **0212** — `catalog_consumer_events`. На проде после мержа: `alembic upgrade head`, затем проверка ограничения share (это не enum):
   ```sql
   SELECT pg_get_constraintdef(oid)
   FROM pg_constraint
   WHERE conname = 'ck_client_share_events_kind';
   ```
   В тексте должны быть `place` и `selection`. Без `0210` подборка пишется вхолостую: ошибка счётчика глотается, чтобы не ломать отправку.
6. Прогрев превью не обязателен: `og.png` и `story.png` рисуются на запросе и кэшируются 15 минут. Первый человек в чате ждёт рендер.

## Сразу после выката, около 20 минут

7. С телефона без Telegram открыть `/c/<город>?w=weekend`. Светлый фон. В заголовке вкладки даты вида «Сб, 3 окт», не «сегодня». Сеанс ведёт на `/p/…?s=`. Цена есть только там, где она есть в данных.
8. Переслать эту ссылку в Telegram. Превью: свой заголовок, абсолютная дата, картинка 1200×630 открывается. То же сообщение вставить в WhatsApp или Viber — ссылка открывается в браузере, не требует Telegram.
9. На странице нажать Telegram, Viber, WhatsApp, «Скопировать». Скопированный текст начинается с `https://` нашего домена.
10. «Открыть в Telegram» с подборки выходных открывает мини-апп на этом городе, вкладке льда и чипе «Выходные» (`startapp=catalog_<id>_skate_weekend`). С карточки сеанса — карточка этого места и этот сеанс (`arena_<id>_s_<session>`).
11. В мини-аппе «Поделиться подборкой»: превью шита не должно плодить строки. После нажатия канала — одна строка:
    ```sql
    SELECT kind, share_context, payload
    FROM client_share_events
    WHERE occurred_at > now() - interval '1 hour'
    ORDER BY id DESC LIMIT 20;
    ```
    У подборки `kind=selection`, у места `kind=place`, в `payload.channel` канал. Пока шит только открывали — новых строк нет.
    Сторис в шите: `story_tg` (редактор Telegram), `story_os` (системное «Поделиться» с PNG), `story_fallback` — не путать со старым `story`.
11a. **Сторис из мини-аппа:** «Сторис» → в Telegram открывается редактор истории (не только «Файлы»). На `story.png` есть QR и путь `/c/…` или `/p/…`; для Instagram ссылка копируется в буфер — стикер ссылки вешает пользователь.
12. `/sitemap.xml` содержит `/c/<город>` и `/p/…`. `/robots.txt` указывает на sitemap и закрывает `/webapp/` и `/api/`.
13. Телеметрия каталога (после шагов 7–10): открыть `/c/…` в браузере → в БД появляется `public_page_view`. Нажать «Открыть в Telegram» → `public_telegram_cta` (URL в адресной строке на секунду — `/api/public/catalog/open-telegram?…`). Открыть мини-апп с той же подборки → в течение минуты `miniapp_catalog_entry` с тем же `start_param` в колонке.
    ```sql
    SELECT kind, surface, start_param, occurred_at
    FROM catalog_consumer_events
    WHERE occurred_at > now() - interval '1 hour'
    ORDER BY id DESC LIMIT 30;
    ```
14. Сводка для гейта (read-only, с прод-`DATABASE_URL`):
    ```bash
    python scripts/report_catalog_gate_metrics.py --days 7
    ```

## Метрики после выката (0212)

Таблица `catalog_consumer_events`:

| kind | Когда |
|---|---|
| `public_page_view` | GET `/p/…`, `/c/…`, `/ice/…/today` (HTML, не og.png) |
| `public_telegram_cta` | Клик «Открыть в Telegram» → `/api/public/catalog/open-telegram` → 302 в Telegram |
| `miniapp_catalog_entry` | POST `/api/webapp/client/catalog/presence` из мини-аппа (shell / Поиск / карточка места) |

WAU каталога: `COUNT(DISTINCT actor_hash)` за 7 дней по `public_page_view` + `miniapp_catalog_entry`. C-B прокси: `get_catalog_virality_cb_metrics` (shares/WAU, share→deeplink-open по `start_param` arena_/catalog_). `client_share_events` по-прежнему только намерение отправить.
