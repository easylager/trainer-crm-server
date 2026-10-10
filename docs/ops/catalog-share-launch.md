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

## Надёжный шаринг объекта (TASK-223)

Проверки после выката ветки `feat/TASK-223-reliable-object-share`. План: `docs/plans/2026-10-09-reliable-object-share.md`.

15. **Main Mini App у клиентского бота.** Без него `t.me/<bot>?startapp=arena_X_s_Y` не открывает карточку, и никто этого не замечает. Бот при старте спрашивает у Telegram `getMe` → `has_main_web_app` (Bot API 7.8) и пишет WARNING (и сообщение в Sentry), если `CLIENT_BOT_MAIN_MINI_APP=true`, а Telegram говорит «нет». В админ-боте `/version` есть строка `Main Mini App: ok` / `warn` / `unknown`. `warn` → BotFather → Main Mini App на тот же домен (или `CLIENT_BOT_MAIN_MINI_APP=false`, тогда ссылки идут через `/start`). `unknown` — Telegram не ответил за 5 с или токен не принят; не тревога, повторить `/version`. Поле `has_main_web_app` проверяет **наличие**, не совпадение URL: домен в BotFather глазами.
16. **Стабильные id сеансов.** Публикация расписания больше не пересоздаёт строки: ссылка `?s=<id>` живёт, пока сеанс есть в расписании. Проверка на проде: выбрать одну арену, запомнить 5 id и дождаться следующего прогона парсера (днём до 45 минут).
    ```sql
    SELECT id, starts_at_utc, kind FROM ice_sessions
    WHERE arena_id = :arena_id AND starts_at_utc > now()
    ORDER BY starts_at_utc LIMIT 5;
    ```
    После прогона тот же запрос: те же `id` на тех же `starts_at_utc`. Другие id у тех же слотов — парсер снова пересоздаёт строки, откатывать.
17. **Откуда пришли по шарингу (`src`).** Канал в ссылке: `tg`, `vb`, `wa`, `vk`, `copy`, `story`, `sys`, `img`. Открыть `/p/…?s=<id>&src=wa`, затем:
    ```sql
    SELECT payload->>'src', count(*)
    FROM catalog_consumer_events
    WHERE kind='public_page_view' AND payload ? 'src'
      AND occurred_at > now() - interval '1 day'
    GROUP BY 1;
    ```
    Своя открытая ссылка видна строкой `wa`. Значения вне списка в `payload` не попадают. Клик «Открыть в Telegram» несёт тот же `src` в `public_telegram_cta`.
18. **Ранний диплинк (вручную, телефон с Telegram).** Из чата открыть `t.me/<bot>?startapp=arena_<id>_s_<session>` при холодном старте Mini App: карточка арены открывается сразу, без вспышки хаба. Повторить с `catalog_<id>_skate_weekend` — сразу лёд с чипом «Выходные».
19. **Сеанс убрали из расписания.** Открыть ссылку с id, которого нет (`?s=999999999` на вебе, `arena_<id>_s_999999999` в мини-аппе): «Этого сеанса уже нет в расписании», рядом ближайшие сеансы; кнопка «Позвать на …» не подставляет другой слот молча.

## Метрики после выката (0212)

Таблица `catalog_consumer_events`:

| kind | Когда |
|---|---|
| `public_page_view` | GET `/p/…`, `/c/…`, `/ice/…/today` (HTML, не og.png) |
| `public_telegram_cta` | Клик «Открыть в Telegram» → `/api/public/catalog/open-telegram` → 302 в Telegram |
| `miniapp_catalog_entry` | POST `/api/webapp/client/catalog/presence` из мини-аппа (shell / Поиск / карточка места) |

WAU каталога: `COUNT(DISTINCT actor_hash)` за 7 дней по `public_page_view` + `miniapp_catalog_entry`. C-B прокси: `get_catalog_virality_cb_metrics` (shares/WAU, share→deeplink-open по `start_param` arena_/catalog_). `client_share_events` по-прежнему только намерение отправить.

### TASK-189: стабильный актёр, дедуп, отчёт по городам (migration 0220)

**Обязательная переменная до выката:** `CATALOG_ACTOR_HMAC_SECRET` на сервисах `api-server`
(пишет события) — ≥ 32 символов, `openssl rand -hex 32`. Ни из чего не выводится.

* Не задана или короче 32 → `actor_hash` **не пишется** (fail closed, в любом окружении: в
  `src/shared/config.py` нет признака «прод», поэтому правило одно), в лог одна ошибка
  `CATALOG_ACTOR_HMAC_SECRET is unset…`. События пишутся без актёра и без дедупа — WAU и
  недели × города их не видят. Никакого отката на `SECRET_KEY` или литерал.
* Смена секрета = новые псевдонимы для всех: ряд «неделя к неделе» рвётся. Не ротировать без нужды.
* `actor_hash` = HMAC(секрет, telegram id | IP+UA), без дня. Дедуп — уникальный `dedup_key`
  (вид | поверхность (вход в мини-апп — одна группа) | актёр | сутки по Минску | город | арена).
* Сопоставимый ряд начинается с первой строки нового формата (`dedup_key IS NOT NULL`) —
  ставится сам в момент, когда выкат и секрет оба на месте. Ручная граница —
  `CATALOG_METRICS_COMPARABLE_SINCE=YYYY-MM-DD` (полночь по Минску). История до этого не пересчитывается.
* C-B share→open: только вход в мини-апп по диплинку места/подборки, **запущенный из чата**
  (`chat_type` в подписанной initData). Голый `catalog` (`/go`) и переход с CTA публичной
  страницы (браузер, чата нет) не считаются. Сейчас шеры уходят веб-ссылками на `/p/`, поэтому
  эта цифра честно мала; веб-воронку смотреть по `public_telegram_cta_clicks`.
* Ретеншн: TTL-цикл `ice_scrape_ttl` (notification_service, раз в час) удаляет события старше 400 дней.
* Отчёт: `DATABASE_URL=… python scripts/report_catalog_gate_metrics.py` — WAU, C-B, недели × города, топ арен.

