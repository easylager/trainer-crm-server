# Trainer CRM Belarus

CRM-платформа для тренеров в Беларуси. Два Telegram-бота в одном репо: клиентский (публичный) и тренерский (вход по ссылке с сайта после оплаты).

## Стек

- Python 3.11+
- Telegram Bot (aiogram / python-telegram-bot)
- PostgreSQL
- SQLAlchemy 2.0 + Alembic

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
- **Переменные окружения** (`.env`):
  - `TELEGRAM_BOT_TOKEN_CLIENT` — токен клиентского бота.
  - `TELEGRAM_BOT_TOKEN_TRAINER` — токен тренерского бота.
  - Опционально `TRAINER_LINK_TOKEN` — токен для ссылки привязки тренера (dev: по умолчанию `test`).
  - `DATABASE_URL` — async‑URL для приложения, по умолчанию:
    - `postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm`
  - `DATABASE_URL_SYNC` — sync‑URL для Alembic:
    - `postgresql://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm`

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

## Структура проекта

См. [PROJECT_PLAN.md](./PROJECT_PLAN.md) — полный план задач и этапов.

## Лицензия

Proprietary. Все права защищены.
