# Переменные окружения

Секреты и конфигурация задаются только через окружение (локально: файл `.env`, на проде: панель хостинга). Репозиторий не должен содержать реальные токены; `.env` в `.gitignore`.

Шаблон со всеми именами переменных: [`.env.example`](../.env.example). Источник правды по полям — `src/shared/config.py` (класс `Settings`).

## Обязательные для запуска ботов и API

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_BOT_TOKEN_CLIENT` | Токен клиентского бота (BotFather). |
| `TELEGRAM_BOT_TOKEN_TRAINER` | Токен тренерского бота. |
| `DATABASE_URL` | Async SQLAlchemy URL (`postgresql+asyncpg://...`). |

Остальные поля имеют значения по умолчанию в коде или опциональны (см. таблицу ниже).

## Опциональные и продакшен

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_BOT_TOKEN_ADMIN` | Админ-бот; если не задан — функции админ-Mini App недоступны. |
| `ADMIN_TELEGRAM_IDS` | Список Telegram ID администраторов. Формат: **JSON-массив**, например `[123456789,987654321]` (так парсит Pydantic). |
| `TRAINER_LINK_TOKEN` | Токен ссылки привязки тренера с сайта (если используется). |
| `DATABASE_URL_SYNC` | Sync URL для Alembic (`postgresql+psycopg://...`). |
| `S3_*`, `LOCAL_STORAGE_PATH` | Объектное хранилище или локальная папка для загрузок. |
| `API_BASE_URL` | Базовый URL API для ботов и клиентов (например `https://…railway.app`). |
| `WEBAPP_BASE_URL` | Базовый URL для Telegram Web App (HTTPS на проде). |
| `PHOTO_BASE_URL`, `PHOTO_CDN_BASE_URL`, `PHOTO_PRESIGNED_EXPIRES_SEC` | Раздача фото каталога. |
| `PHOTO_UPLOAD_PRESIGN_EXPIRES_SEC` | Срок presigned PUT для прямой загрузки фото в S3 (по умолчанию 600 с). |
| `INTERNAL_UPLOAD_API_KEY` | Если не задан — отключены legacy `POST /api/upload/photo` и presign без `initData`. Для локальных curl: задайте секрет и передавайте заголовок `X-Internal-Upload-Key`. В продакшене обычно не задаётся. |
| `DEBUG` | `true` только для локальной отладки; в проде должен быть `false`. |
| `LOG_LEVEL`, `AUDIT_LOG_LEVEL` | Уровни логирования. |
| `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SEC` | Лимит запросов бота на пользователя. |
| `SCHEDULE_REMINDER_COOLDOWN_MINUTES` | Кулдаун напоминаний о заявках. |
| `BEPAID_SHOP_ID`, `BEPAID_SECRET_KEY`, `BEPAID_CHECKOUT_BASE_URL`, `PAYMENT_SANDBOX` | Оплата bePaid. Если оба ключа заданы, `POST /api/webhooks/bepaid` требует `Authorization: Basic` (shop id и secret, как в [доке bePaid](https://docs.bepaid.by/en/using_api/webhooks/)). |
| `TRIAL_PERIOD_DAYS`, `SUBSCRIPTION_REMINDER_DAYS_AHEAD` | Подписки тренеров. |
| `NOTIFY_TELEGRAM_ID` | Тестовые уведомления (скрипты). |
| `CLIENT_BOT_USERNAME` | Username бота без `@` для deep links (сертификаты и т.д.). |
| `SMTP_*` | Отправка писем (сертификаты); если не заданы — отправка отключена. |
| `TELEGRAM_WEBAPP_INIT_DATA_MAX_AGE_SEC` | Окно свежести `auth_date` в Mini App `initData` (секунды), по умолчанию `86400`. |
| `TELEGRAM_WEBAPP_INIT_DATA_CLOCK_SKEW_SEC` | Допустимый сдвиг «в будущее» для `auth_date` (секунды), по умолчанию `300`. |

Подробнее про угрозы и проверки: **[TELEGRAM_WEBAPP_INITDATA.md](TELEGRAM_WEBAPP_INITDATA.md)**.

### HTTP API (FastAPI, Epic D)

- **`API_RATE_LIMIT_ENABLED`** — включить лимиты по IP для путей `/api/*` (кроме `/api/webhooks`). По умолчанию `true`.
- **`API_RATE_LIMIT_*_MAX_REQUESTS`**, **`API_RATE_LIMIT_*_WINDOW_SEC`** — окна для бакетов `public`, `webapp`, `upload`, `default` (см. `rate_limit_bucket_for_path` в `src/api/middleware/http_limits.py`). IP берётся из `X-Forwarded-For` (первый hop) или `request.client`.
- **`API_MAX_BODY_BYTES_DEFAULT`**, **`API_MAX_BODY_BYTES_UPLOAD`**, **`API_MAX_BODY_BYTES_WEBHOOK`** — верхняя граница тела запроса, если передан заголовок `Content-Length` (иначе проверка пропускается; в проде задайте `client_max_body_size` на nginx/ingress).

## Объектное хранилище (S3): бакет и ключи (SEC-E)

- **Не делайте весь бакет публичным** без необходимости. Клиенты получают фото каталога через presigned URL, CDN (`PHOTO_CDN_BASE_URL`) или прокси `GET /api/public/photos/...`; приложение читает из бакета по ключам с префиксом `trainers/` и не отдаёт через публичный эндпоинт ключи `legal/`, `certificates/` и др. (см. `resolve_object_key_under_prefixes` в `src/infrastructure/s3.py`).
- **Права ключей доступа (IAM / Railway):** минимально достаточные — как правило `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` на нужный бакет (или на префиксы, если провайдер поддерживает политику по префиксу). Не используйте root/широкие admin-ключи для приложения.
- **Один бакет:** в коде зафиксированы логические префиксы: публичные снимки тренеров — `trainers/…`, юридические документы — `legal/…`, PDF сертификатов — `certificates/…`. При желании можно вынести публичные объекты в отдельный бакет и настроить CDN только на него.

## Политика логов (ревью)

- Не логировать: сырой `initData`, заголовок `X-Telegram-Init-Data`, токены ботов, пароли SMTP, полные номера телефонов без необходимости.
- Коды подтверждения телефона — только при `DEBUG=true` (см. `src/bot/handlers/client_handlers.py`).
- Ошибки валидации FastAPI: в лог пишется версия без поля `input` (см. `src/shared/logging_redact.py`, `src/api/app.py`).
- Для маскирования телефона в новых логах можно использовать `redact_phone()` из `src/shared/logging_redact.py`.

## См. также

- [SECRET_ROTATION.md](SECRET_ROTATION.md) — смена токенов при утечке.
- [SECURITY_BACKLOG.md](SECURITY_BACKLOG.md) — эпик A и остальные задачи по безопасности.
