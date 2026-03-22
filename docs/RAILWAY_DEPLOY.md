# Деплой на Railway (push → deploy)

Один репозиторий → один **проект** Railway → **PostgreSQL** + **5 процессов приложения** (API, три Telegram-бота, сервис уведомлений). Переменные задаёте в dashboard.

**После первого деплоя из GitHub обычно поднимается только API** (web по Procfile). Остальные процессы добавляются отдельными сервисами с **Custom Start Command** (раздел 2).

Подробнее про **staging vs production** и CI: **[CI_CD.md](CI_CD.md)**.

---

## 1. Подготовка (один раз на окружение)

1. **Репозиторий на GitHub** — код в целевой ветке (`main` для prod, `develop` для staging — см. [CI_CD.md](CI_CD.md)).
2. **Railway:** [railway.app](https://railway.app) → Login → **New Project**.
3. **Подключить GitHub:** в проекте → **Add Service** → **GitHub Repo** → выберите репо → укажите **ветку деплоя** (Settings → Deploy → Branch).  
   Первый сервис стартует по **Procfile** (`web: sh scripts/railway-start-api.sh`). Если в логах **Failed to parse start command** — в **Settings** → **Deploy** → **Custom Start Command** укажите одну строку без кавычек:  
   `sh scripts/railway-start-api.sh`  
   Домен: **Settings** → **Networking** → **Generate Domain**.
4. **База:** в том же проекте → **Add Service** → **Database** → **PostgreSQL**.  
   Railway подставит переменную **`DATABASE_URL`** (формат `postgresql://...`) во все сервисы. Код сам подставляет `+asyncpg` для приложения и использует этот URL для Alembic — отдельно `DATABASE_URL_SYNC` не нужен.
5. **Связать сервисы с БД:** в каждом сервисе приложения → **Variables** → **Add Reference** → `DATABASE_URL` от PostgreSQL. Так все процессы получат один и тот же `DATABASE_URL`.

---

## 2. Пять процессов приложения из одного репо

Все сервисы — **один и тот же репозиторий**, Root Directory не меняем.

| Сервис | Назначение | Start Command |
|--------|------------|----------------|
| **Web (первый)** | API + миграции | Procfile / `sh scripts/railway-start-api.sh` (`alembic upgrade head` + uvicorn). Custom Start Command можно не задавать. |
| **client-bot** | Клиентский бот | `python -m src.bot.client_app` |
| **trainer-bot** | Тренерский бот | `python -m src.bot.trainer_app` |
| **admin-bot** | Админ-бот | `python -m src.bot.admin_app` |
| **notification-service** | Напоминания, отложенные уведомления, outbox писем и т.д. | `python -m src.bot.notification_service` |

Без **notification-service** боты и API работают, но не уходят фоновые уведомления (напоминания, «занятие завершено», отмены и т.п.) — см. [RUNNING_AND_DEPLOYMENT.md](RUNNING_AND_DEPLOYMENT.md).

Как добавить сервисы:

- В проекте → **Add Service** → **Empty Service** или снова **GitHub Repo** (тот же репо, та же ветка).
- **Settings** → **Deploy** → **Custom Start Command** → команда из таблицы (для web не нужна, если используется Procfile).

---

## 3. Переменные окружения

В **каждом** сервисе (или в **Project** → **Variables** — тогда они общие для всех):

| Переменная | Обязательно | Откуда |
|------------|-------------|--------|
| `DATABASE_URL` | да | Reference из PostgreSQL add-on. |
| `TELEGRAM_BOT_TOKEN_CLIENT` | да | BotFather → клиентский бот. |
| `TELEGRAM_BOT_TOKEN_TRAINER` | да | BotFather → тренерский бот. |
| `TELEGRAM_BOT_TOKEN_ADMIN` | для админ-бота | BotFather → админ-бот. |
| `ADMIN_TELEGRAM_IDS` | для админ-бота | Список Telegram ID через запятую, например `123456789,987654321`. |
| `API_BASE_URL` | желательно | Публичный URL API этого окружения, например `https://your-api.up.railway.app`. Нужен клиентскому боту. |
| `TRAINER_LINK_TOKEN` | опционально | Токен для ссылки привязки тренера (с сайта). |

S3 (фото): `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` (и при необходимости `S3_REGION`, `S3_PATH_STYLE`).

**Staging и production:** используйте **разные** проекты Railway или разные окружения с **отдельными** ботами (токены), **отдельной** БД и **своим** `API_BASE_URL`. Не смешивайте токены prod и staging.

---

## 4. После деплоя

- **API:** открыть домен → `/health`. Ожидается `{"status":"ok","db":"ok",...}`.
- **Боты:** проверить ответы в Telegram.
- **Миграции** выполняются при каждом деплое **только API** (см. `scripts/railway-start-api.sh`).

---

## 5. Push → автоматический деплой

После привязки репозитория:

- Пуш в **ветку, привязанную к проекту**, запускает сборку и деплой **всех** сервисов этого проекта, подключённых к этому репо.
- **Staging** и **production** — обычно два проекта Railway с ветками `develop` и `main` (см. [CI_CD.md](CI_CD.md)).

---

## 6. Краткий чеклист

- [ ] Проект Railway создан, репо подключено, выбрана нужная **ветка**.
- [ ] Добавлен PostgreSQL, `DATABASE_URL` доступен всем сервисам приложения (Reference).
- [ ] Пять сервисов: web (Procfile), client-bot, trainer-bot, admin-bot, notification-service.
- [ ] Заданы токены ботов, при необходимости `ADMIN_TELEGRAM_IDS`, `API_BASE_URL`, S3.
- [ ] Домен API сгенерирован, `/health` возвращает 200.
- [ ] Боты отвечают; при необходимости проверены фоновые уведомления (notification-service в логах без ошибок).

Дальше достаточно пушить в целевую ветку — Railway пересоберёт и задеплоит сервисы проекта.
