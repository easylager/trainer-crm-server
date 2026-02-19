# Trainer CRM Belarus

CRM-платформа для тренеров в Беларуси. Связь тренеров и клиентов через Telegram бот (Phase 1).

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
# Отредактировать .env (токен бота, DATABASE_URL)

# Запустить миграции
alembic upgrade head

# Запустить бота
python -m src.bot.main
```

## Структура проекта

См. [PROJECT_PLAN.md](./PROJECT_PLAN.md) — полный план задач и этапов.

## Лицензия

Proprietary. Все права защищены.
