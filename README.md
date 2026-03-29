# Trainer CRM Belarus

CRM-платформа для тренеров в Беларуси. Два Telegram-бота в одном репо: клиентский (публичный) и тренерский (вход по ссылке с сайта после оплаты).

## Стек

- Python 3.11+
- Telegram Bot (aiogram / python-telegram-bot)
- PostgreSQL
- SQLAlchemy 2.0 + Alembic

## Cursor: MCP (AI + локальная разработка)

В репозитории есть [`.cursor/mcp.json`](.cursor/mcp.json): filesystem, fetch, PostgreSQL (read-only), GitHub, Playwright, опционально Notion и др.  
Подстановка секретов через переменные окружения (`POSTGRES_MCP_URL`, `GITHUB_PERSONAL_ACCESS_TOKEN`, `NOTION_TOKEN` для Notion). Подробности и чеклист после правок — **[docs/CURSOR_MCP.md](docs/CURSOR_MCP.md)**. Продуктовый хаб для Notion (копирование в рабочее пространство) — **[docs/NOTION_PRODUCT_HUB.md](docs/NOTION_PRODUCT_HUB.md)**.

## Cursor: Spec Kit (spec-driven фичи)

В репозитории настроен **[GitHub Spec Kit](https://github.com/github/spec-kit)** для Cursor: slash-команды **`/speckit.constitution`**, **`/speckit.specify`**, **`/speckit.plan`**, **`/speckit.tasks`**, **`/speckit.implement`** и др. в [`.cursor/commands/`](.cursor/commands/). Кратко — **[docs/SPEC_KIT.md](docs/SPEC_KIT.md)**.

## Деплой и CI/CD

- **Railway:** PostgreSQL + API + 3 бота + **notification service** — **[docs/RAILWAY_DEPLOY.md](docs/RAILWAY_DEPLOY.md)**.
- **Staging / production, ветки, чеклист Railway:** **[docs/CI_CD.md](docs/CI_CD.md)**.
- Тесты на GitHub Actions: [`.github/workflows/tests.yml`](.github/workflows/tests.yml) (`main`, `master`, `develop`, `staging`).

---

## Быстрый старт

```bash
# Клонировать репозиторий
git clone <repo-url>
cd trainer-crm-belarus

# Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Установить зависимости
pip install -r requirements.txt

# Скопировать конфиг
cp .env.example .env
# Отредактировать .env (токен бота, DATABASE_URL/DATABASE_URL_SYNC)

# Поднять локальную базу PostgreSQL через docker-compose
docker compose up -d postgres

# Проверить, что база доступна (опционально)
# psql postgresql://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm -c "\dt"

# Запустить миграции (Alembic)
alembic upgrade head

# Запустить ботов (два процесса; на проде — два воркера/контейнера)
python -m src.bot.client_app   # клиентский бот (публичный)
python -m src.bot.trainer_app  # тренерский бот (вход по ссылке с сайта)
# Либо по умолчанию: python -m src.bot.main  → запускает client_app
```

## Настройка окружения и базы данных

- **PostgreSQL через Docker**:
  - Локальная база поднимается из `docker-compose.yml`:
    - пользователь: `trainer_crm`
    - пароль: `trainer_crm_dev`
    - база: `trainer_crm`
    - порт: `5432`
- **Переменные окружения** (`.env`): полный список и политика логов — **[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)**.
  - `TELEGRAM_BOT_TOKEN_CLIENT` — токен клиентского бота.
  - `TELEGRAM_BOT_TOKEN_TRAINER` — токен тренерского бота.
  - Опционально `TRAINER_LINK_TOKEN` — токен для ссылки привязки тренера (dev: по умолчанию `test`).
  - `DATABASE_URL` — async‑URL для приложения, по умолчанию:
    - `postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm`
  - `DATABASE_URL_SYNC` — sync‑URL для Alembic:
    - `postgresql://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm`
  - **Файлы (фото тренеров)** — хранятся в S3 (`S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`). В БД только метаданные: `trainer_photos.file_key`.

**Загрузить фото с компьютера в S3 и привязать к тренеру (legacy, только dev):** в `.env` задайте `INTERNAL_UPLOAD_API_KEY` (и заголовок `X-Internal-Upload-Key` в запросе); без этого эндпоинт отключён — в продакшене загрузка идёт через Mini App с `initData`. При настроенных S3 и ключе:
```bash
curl -X POST http://localhost:8000/api/upload/photo \
  -H "X-Internal-Upload-Key: $INTERNAL_UPLOAD_API_KEY" \
  -F "trainer_id=1" -F "file=@/путь/к/фото.jpg"
```
Ответ `{"file_key":"trainers/1/....jpg"}` — файл в S3, запись в `trainer_photos` создана.

**API для сайта (профили тренеров заполняются и управляются на сайте):**
- **POST /api/trainers** — создать тренера. Тело (JSON): `first_name`, `last_name`, `age` (обязательные), `experience_years`, `description`, `phone`, `contacts`, `education`, `service_ids` (опционально). Ответ: `{"id": 1}`.
- **GET /api/trainers/{id}** — тренер целиком: профиль, фото (file_key), service_ids.
- **PATCH /api/trainers/{id}/profile** — частичное обновление профиля и/или `service_ids`.
- **GET /api/trainers** — список тренеров (limit, offset).
- **GET /api/trainers/education-options** — варианты образования для select при заполнении профиля тренера.

Профиль: имя, фамилия, возраст (обязательные), стаж в годах (опционально), описание, телефон, контакты, образование. После миграции 0005: `alembic upgrade head`. Заполнить пару профилей для теста: `python scripts/seed_trainer_profiles.py` (нужны услуги: сначала `python scripts/seed_services.py`).

## Health-check (`/health`)

HTTP‑сервис ещё не реализован. План health‑эндпоинта:

- Будет отдельный веб‑сервис (например, FastAPI) с GET `/_health` или `/health`.
- Эндпоинт будет проверять:
  - доступность базы данных;
  - готовность основных инфраструктурных зависимостей (S3, платёжный провайдер и т.п.).
- После добавления веб‑сервиса:
  - локальная проверка будет выглядеть как:
    - `curl http://localhost:<port>/health`

Пока в Phase 1 можно считать "health" успешным, если:

- контейнер Postgres здоров (`docker compose ps` показывает `healthy`);
- Telegram‑бот запускается без ошибок и отвечает в чате.

## Telegram: два бота

Правила единообразия: [.specify/memory/constitution.md](.specify/memory/constitution.md) — **§ VII** (боты: тексты, клавиатуры, разметка), **§ VIII** (Mini App в `static/webapp/`: цвета, типографика, общие UI-токены).

- Создать **двух** ботов в @BotFather (например: «Запись к тренеру» — клиентский, «Trainer CRM» — тренерский).
- В `.env` прописать `TELEGRAM_BOT_TOKEN_CLIENT` и `TELEGRAM_BOT_TOKEN_TRAINER`.
- Запуск:
  - `python -m src.bot.client_app` — клиентский; любой пользователь может /start.
  - `python -m src.bot.trainer_app` — тренерский; вход только по ссылке с сайта `?start=link_<token>` (без ссылки — сообщение «только для тренеров по ссылке»).
- На проде — два процесса (два воркера/контейнера).

### Как тренер попадает в бот (маппинг в БД)

- В БД: таблицы **trainers** (id, telegram_id, created_at) и **trainer_link_tokens** (token, trainer_id, expires_at, used_at).
- Тренер создаётся на сайте (регистрация, проверка, оплата). После оплаты сайт создаёт запись тренера и одноразовый токен (или вызывает наш API/скрипт) и выдаёт пользователю ссылку `https://t.me/TrainerBot?start=link_<token>`.
- Пользователь открывает ссылку в Telegram → тренерский бот получает /start link_<token> → проверяет токен в БД, проставляет `trainers.telegram_id`, помечает токен использованным. Другого пути в бота нет: без валидной ссылки показывается «только для тренеров по ссылке с сайта».

**Создать тренера и ссылку вручную (для теста или сида):**
```bash
PYTHONPATH=. python scripts/create_trainer_link.py --bot-username YourTrainerBotUsername
```
Скрипт создаёт запись в `trainers`, токен в `trainer_link_tokens` и выводит готовую ссылку.

## Структура проекта и боевой режим

- [PROJECT_PLAN.md](./PROJECT_PLAN.md) — полный план задач и этапов.
- [docs/PRODUCTION_PLAN.md](./docs/PRODUCTION_PLAN.md) — **боевой план**: CI, деплой, откат, мониторинг, runbook для продакшена.

## CI

На каждый push и pull request в `master`/`main` запускается [GitHub Actions](.github/workflows/tests.yml): поднимается PostgreSQL 16, накатываются миграции, выполняется `pytest tests/`. Токены ботов в CI задаются заглушками.

## Лицензия

Proprietary. Все права защищены.
