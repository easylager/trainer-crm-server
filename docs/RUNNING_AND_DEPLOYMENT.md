# Запуск и деплой

## Что нужно поднять

| Процесс | Назначение |
|--------|------------|
| **API** | Сайт, Mini App (каталог, записи, заявки), вебхуки не используются — боты на polling |
| **Client bot** | Обработка сообщений и callback от клиентов (команды, «Мои записи», каталог и т.д.) |
| **Trainer bot** | Обработка сообщений и callback от тренеров (расписание, заявки, записи) |
| **Notification service** | Все отложенные уведомления: напоминания, «занятие завершено», отмена, отклики, неактивные клиенты и т.д. |

Все четыре процесса используют **одну БД** и **один .env** (токены ботов, `DATABASE_URL`, `WEBAPP_BASE_URL` и т.д.).

---

## Локальный запуск

1. **БД:** поднять PostgreSQL (например `docker-compose up -d` в корне — поднимется только postgres).
2. **Миграции:** `alembic upgrade head`.
3. **Запуск четырёх процессов** (четыре терминала из корня проекта, один и тот же venv и .env):

```bash
# Терминал 1 — API (Mini App, каталог, записи)
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000

# Терминал 2 — клиентский бот
python -m src.bot.client_app

# Терминал 3 — тренерский бот
python -m src.bot.trainer_app

# Терминал 4 — уведомления (напоминания, завершение занятий, отмены, отклики и т.д.)
python -m src.bot.notification_service
```

Если **notification_service не запущен**, клиенты и тренеры по-прежнему смогут пользоваться ботом и API, но не будут приходить напоминания, уведомления «занятие завершено», «тренер отменил», «тренер откликнулся» и т.п.

Остановка notification_service: **Ctrl+C** (SIGINT) или `kill -TERM <pid>` — циклы корректно завершаются, сессии ботов закрываются.

---

## Деплой в связке

Идея: те же четыре процесса на сервере, каждый под контролем супервизора или контейнерами.

### Вариант 1: systemd (VPS / одна машина)

Один юнит на каждый процесс, один и тот же `WorkingDirectory` и `EnvironmentFile` (.env).

Пример для **notification_service**:

```ini
[Unit]
Description=Trainer CRM Notification Service
After=network.target postgresql.service

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/trainer-crm-belarus
EnvironmentFile=/opt/trainer-crm-belarus/.env
ExecStart=/opt/trainer-crm-belarus/venv/bin/python -m src.bot.notification_service
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Аналогично делаются юниты для `uvicorn src.api.app:app`, `src.bot.client_app`, `src.bot.trainer_app`. Запуск/остановка/рестарт — через `systemctl start|stop|restart notification-service` (и остальных). Так ты контролируешь notification_service независимо от ботов и API.

### Вариант 2: Docker Compose

В `docker-compose.yml` добавить сервисы (образ один и тот же, меняется только команда):

```yaml
services:
  api:
    build: .
    command: uvicorn src.api.app:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on: [postgres]
    ports: ["8000:8000"]

  client_bot:
    build: .
    command: python -m src.bot.client_app
    env_file: .env
    depends_on: [postgres]

  trainer_bot:
    build: .
    command: python -m src.bot.trainer_app
    env_file: .env
    depends_on: [postgres]

  notification_service:
    build: .
    command: python -m src.bot.notification_service
    env_file: .env
    depends_on: [postgres]
    restart: unless-stopped
```

Сборка: `docker-compose build`. Запуск всего: `docker-compose up -d`. Остановка только уведомлений: `docker-compose stop notification_service`; снова запуск: `docker-compose start notification_service`.

### Вариант 3: Отдельная нода для notification_service

При высокой нагрузке можно вынести notification_service на отдельный сервер: те же переменные окружения (доступ к той же БД и те же токены ботов), только процесс `python -m src.bot.notification_service`. Остальные три (API, client_app, trainer_app) — на другой машине. Независимый рестарт и масштабирование (при необходимости можно запустить второй экземпляр notification_service; дубликаты писем минимизируются за счёт пометок в БД).

---

## Контроль notification_service

- **Логи:** смотреть stdout/stderr процесса (или вывод systemd/docker). В коде используется `logging` без отдельного файла — перенаправление через systemd/docker.
- **Остановка:** SIGTERM или SIGINT — graceful shutdown (ожидание отмены задач и закрытие сессий ботов).
- **Рестарт:** после рестарта сервис снова подхватывает все циклы; необработанные записи в БД (pending reminders, unsent notifications) будут обработаны при следующих проходах циклов.
