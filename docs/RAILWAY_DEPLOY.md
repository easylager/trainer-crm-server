# Деплой на Railway (push → deploy)

Один репозиторий → один проект Railway → 4 сервиса (API + 3 бота). PostgreSQL подключается как add-on, переменные задаёте в dashboard.

---

## 1. Подготовка (один раз)

1. **Репозиторий на GitHub** — код в `main`/`master`, всё закоммичено.
2. **Railway:** [railway.app](https://railway.app) → Login → **New Project**.
3. **Подключить GitHub:** в проекте → **Add Service** → **GitHub Repo** → выберите репо → Deploy.  
   Первый сервис должен подняться по **Procfile** (web = API + миграции). Если сборка прошла, но процесс не стартует — в **Settings** → **Deploy** → **Custom Start Command** задайте:  
   `sh -c 'alembic upgrade head && uvicorn src.api.app:app --host 0.0.0.0 --port $PORT'`  
   Дамейн: **Settings** → **Networking** → **Generate Domain**.
4. **База:** в том же проекте → **Add Service** → **Database** → **PostgreSQL**.  
   Railway подставит переменную **`DATABASE_URL`** (формат `postgresql://...`) во все сервисы. Код сам подставляет `+asyncpg` для приложения и использует этот URL для Alembic — отдельно `DATABASE_URL_SYNC` не нужен.
5. **Связать сервисы с БД:** в проекте перетащите PostgreSQL на каждый сервис (или в каждом сервисе → Variables → Add Reference → `DATABASE_URL` от PostgreSQL). Так все 4 процесса получат один и тот же `DATABASE_URL`.

---

## 2. Четыре сервиса из одного репо

Сейчас у вас один сервис (API). Нужно ещё три — боты. Все из **того же репо**, без Root Directory.

| Сервис      | Назначение | Start Command |
|-------------|------------|----------------|
| **Первый (уже есть)** | API + миграции | из Procfile: `alembic upgrade head && uvicorn ...` — ничего не меняем. |
| **client-bot** | Клиентский бот | `python -m src.bot.client_app` |
| **trainer-bot** | Тренерский бот | `python -m src.bot.trainer_app` |
| **admin-bot**   | Админ-бот      | `python -m src.bot.admin_app` |

Как добавить ботов:

- В проекте → **Add Service** → **Empty Service** (или **GitHub Repo** снова, тот же репо).
- В настройках сервиса: **Settings** → **Build** → Root Directory не трогаем. **Deploy** → **Custom Start Command** → вставить команду из таблицы.
- Повторить для трёх ботов (три отдельных сервиса, три разных Start Command).

Первый сервис (API) уже использует Procfile — для него Start Command можно не задавать.

---

## 3. Переменные окружения

В **каждом** сервисе (или в **Project** → **Variables** — тогда они общие для всех):

| Переменная | Обязательно | Откуда |
|------------|-------------|--------|
| `DATABASE_URL` | да | Подставляется из PostgreSQL add-on (Reference). Вручную не задавать, если добавили БД в проект и связали сервисы. |
| `TELEGRAM_BOT_TOKEN_CLIENT` | да | BotFather → клиентский бот. |
| `TELEGRAM_BOT_TOKEN_TRAINER` | да | BotFather → тренерский бот. |
| `TELEGRAM_BOT_TOKEN_ADMIN` | для админ-бота | BotFather → админ-бот. Если не задан, админ-бот не стартует (код это учитывает). |
| `ADMIN_TELEGRAM_IDS` | для админ-бота | Список Telegram ID через запятую, например `123456789,987654321`. |
| `API_BASE_URL` | желательно | Публичный URL API, например `https://your-api.up.railway.app`. Нужен клиентскому боту для каталога/фото. Взять из API-сервиса → Settings → Networking → Domain. |
| `TRAINER_LINK_TOKEN` | опционально | Токен для ссылки привязки тренера (с сайта). |

S3 (фото): если используете Railway Buckets или свой S3 — задать `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` (и при необходимости `S3_REGION`, `S3_PATH_STYLE`). Иначе загрузка фото будет недоступна.

---

## 4. После деплоя

- **API:** открыть сгенерированный домен → `/health`. Должно быть `{"status":"ok","db":"ok"}`.
- **Боты:** написать в Telegram клиентскому и тренерскому боту — должны отвечать.
- Миграции выполняются при каждом деплое **API** (команда в Procfile: `alembic upgrade head` перед запуском uvicorn).

---

## 5. Push → автоматический деплой

После того как все сервисы созданы и привязаны к одному репо:

- Пуш в ветку, с которой связан проект (обычно `main`/`master`), запускает сборку и деплой **всех** сервисов этого проекта.
- В **Deployments** видно логи и статус каждого сервиса.

---

## 6. Краткий чеклист

- [ ] Проект Railway создан, репо подключён.
- [ ] Добавлен PostgreSQL, `DATABASE_URL` доступен всем сервисам (Reference).
- [ ] 4 сервиса: один с Procfile (API), три с Start Command для ботов.
- [ ] В Variables заданы токены ботов, `ADMIN_TELEGRAM_IDS` (если есть админ-бот), при необходимости `API_BASE_URL` и S3.
- [ ] Домен для API сгенерирован, `/health` возвращает 200.
- [ ] Все три бота отвечают в Telegram.

Готово: дальше достаточно пушить в репо — Railway сам соберёт и задеплоит все сервисы.
