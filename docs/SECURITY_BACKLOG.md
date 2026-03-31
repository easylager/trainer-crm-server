# Security backlog

Документ для планирования работ по безопасности до и после релиза. Стек: FastAPI, Telegram Mini App (`initData`), aiogram, PostgreSQL, S3/файлы, публичный API.

**Как пользоваться:** тикеты можно переносить в Jira/Linear/GitHub Issues; префикс `SEC-` условный.

---

## Epic A — Секреты, конфигурация, секреты в логах

**Статус:** закрыт (2026-03-30). Реализация: [`.env.example`](../.env.example), [`docs/ENVIRONMENT.md`](ENVIRONMENT.md), [`docs/SECRET_ROTATION.md`](SECRET_ROTATION.md); маскирование логов — `src/shared/logging_redact.py`, правки в `src/api/app.py` и `src/bot/handlers/client_handlers.py`.

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-A1 | P0 | **Секреты только из окружения** | В продакшене нет секретов в репозитории; `.env` в `.gitignore`; документирован список обязательных переменных (`BOT_TOKEN`, DB URL, S3 keys и т.д.). |
| SEC-A2 | P0 | **Политика логов** | В коде/ревью-чеклист: не логировать `initData`, полные токены, пароли, полные номера телефонов (или маскирование). Spot-check по `logger`/`print`. |
| SEC-A3 | P1 | **Ротация при утечке** | Runbook на 1 страницу: как сменить токен бота в BotFather, обновить env, redeploy, проверить webhook. |

---

## Epic B — Telegram Web App: `initData`

**Статус:** закрыт (2026-03-30). Реализация: [`src/shared/telegram_webapp.py`](../src/shared/telegram_webapp.py) (`validate_init_data` + `auth_date`, `require_telegram_user_id`), роутеры [`webapp.py`](../src/api/routes/webapp.py), [`webapp_trainer_profile.py`](../src/api/routes/webapp_trainer_profile.py); тесты [`tests/shared/test_telegram_webapp.py`](../tests/shared/test_telegram_webapp.py); документ [`TELEGRAM_WEBAPP_INITDATA.md`](TELEGRAM_WEBAPP_INITDATA.md).

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-B1 | P0 | **Проверка `auth_date` (anti-replay)** | После успешной HMAC-проверки отклонять запросы, если `auth_date` старше согласованного окна (например 24h или по доке Telegram). Покрыто тестами. См. `src/shared/telegram_webapp.py`. |
| SEC-B2 | P1 | **Единый helper для webapp-роутов** | Все эндпоинты, требующие клиента/тренера/админа, проходят одну и ту же цепочку: валидация токена (нужного бота) + извлечение `telegram_id` + при необходимости проверка allow-list (админы). |
| SEC-B3 | P1 | **Документация угроз для `initData`** | Кратко в README или здесь: почему нельзя доверять `initData` из query без проверки; что даёт replay без `auth_date`. |

---

## Epic C — Авторизация на уровне API (IDOR, привязка субъекта)

**Статус:** закрыт (2026-03-30). Краткий отчёт: [`SECURITY_EPIC_C.md`](SECURITY_EPIC_C.md).

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-C1 | P0 | **Аудит IDOR по webapp API** | Для каждого роута под `/api/webapp/...`: идентификаторы сущностей (`trainer_id`, `booking_id`, …) берутся из БД по `telegram_id` из валидного `initData`, либо явно проверяется принадлежность; тело запроса не может подменить чужого пользователя. Зафиксированы исключения (если есть). |
| SEC-C2 | P0 | **Публичный API vs приватные данные** | Проверка `/api/public/...`: отсутствуют поля, позволяющие идентифицировать клиентов или внутренние идентификаторы сверх необходимого для каталога. |
| SEC-C3 | P1 | **Загрузки и presigned URL** | Presigned выдаётся только на ключи в namespace текущего тренера; срок жизни минимально достаточный; запрет перезаписи чужих объектов. См. webapp trainer profile / S3. |

---

## Epic D — Злоупотребление и доступность (rate limits, DoS)

**Статус:** закрыт (2026-03-30). Реализация: [`src/api/middleware/http_limits.py`](../src/api/middleware/http_limits.py) (sliding window по IP для `/api/*`, без `/api/webhooks`; `OPTIONS` без лимита), лимиты тела по `Content-Length` (`MaxBodySizeMiddleware`); настройки в `Settings`; тесты [`tests/api/test_http_limits.py`](../tests/api/test_http_limits.py). Per-user лимит после валидации `initData` при масштабировании — Redis/edge (вне scope).

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-D1 | P0 | **Rate limiting на FastAPI** | Для чувствительных маршрутов (логин через `initData`, публичный каталог, выдача файлов) — лимиты по IP и/или по идентификатору после валидации. Не полагаться только на rate limit в aiogram. |
| SEC-D2 | P1 | **Лимиты размера тела запроса** | Настроены лимиты на upload JSON / multipart согласованно с бизнес-ожиданиями (защита от огромных payload). |

---

## Epic E — Публичные файлы и S3

**Статус:** закрыт (2026-03-30). Реализация: нормализация и проверка префиксов — `resolve_object_key_under_prefixes` в [`src/infrastructure/s3.py`](../src/infrastructure/s3.py) (`get_file`, `get_photo`, `presign_get_url`); документ [`docs/ENVIRONMENT.md`](ENVIRONMENT.md) (раздел «Объектное хранилище (S3)»); тесты [`tests/infrastructure/test_s3_object_keys.py`](../tests/infrastructure/test_s3_object_keys.py).

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-E1 | P0 | **`/api/public/photos/{file_key}`** | Невозможно получить приватный объект перебором `file_key`; при едином бакете — строгие префиксы public/private или отдельные бакеты/политики IAM. |
| SEC-E2 | P1 | **Конфигурация S3** | Бакет не публичный целиком без необходимости; минимальные права ключей приложения. |

---

## Epic F — Вебхуки и бот

**Статус:** закрыт (2026-03-30). **Telegram:** long polling (`src/bot/*_app.py`), вебхук не используется — см. [RAILWAY_DEPLOY.md](RAILWAY_DEPLOY.md) (раздел «Telegram: long polling и вебхуки»). **Платежный webhook:** `POST /api/webhooks/bepaid` — проверка HTTP Basic при заданных `BEPAID_SHOP_ID` и `BEPAID_SECRET_KEY` ([`src/api/bepaid_webhook_auth.py`](../src/api/bepaid_webhook_auth.py)); идемпотентность подтверждения счёта — [`confirm_subscription_invoice_after_payment`](../src/application/subscription_use_cases.py).

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-F1 | P0 | **Webhook Telegram / платежи** | Telegram: вебхук не включён (polling); платежный маршрут — только `POST`, при настроенных bePaid-учётных данных — HTTP Basic; критичное подтверждение счёта идемпотентно. |
| SEC-F2 | P1 | **Long polling vs webhook** | В доке деплоя указано, что используется, и нет двойной обработки одних и тех же апдейтов. |

---

## Epic G — Транспорт, заголовки, CORS

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-G1 | P0 | **TLS** | Прод: только HTTPS к API; валидные сертификаты; редирект HTTP→HTTPS на edge. |
| SEC-G2 | P1 | **Заголовки для статического HTML** | Для отдаваемых Mini App HTML: разумный `Cache-Control` (уже учтён), при возможности `X-Content-Type-Options: nosniff`; CSP согласован с inline-скриптами Telegram SDK. |
| SEC-G3 | P1 | **CORS** | Задокументировано: `allow_origins=["*"]` + `credentials=False` в `src/api/app.py` — намеренно для Mini App; правило не включать `allow_credentials=True` с `*` без смены модели. |

---

## Epic H — Данные, бэкапы, соответствие

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-H1 | P1 | **Бэкапы БД** | Автоматические бэкапы; тест восстановления хотя бы раз в квартал; RPO/RTO записаны. |
| SEC-H2 | P1 | **Права приложения к БД** | Отдельный пользователь БД с минимальными правами (не superuser). |
| SEC-H3 | P2 | **PII и юрисдикция** | Определена юрисдикция персональных данных; политика хранения/удаления; при необходимости тексты согласий и ответы на запросы субъектов данных. |

---

## Epic I — Зависимости и процесс

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-I1 | P1 | **Автоматическая проверка зависимостей** | CI или периодический job: `pip-audit` / Dependabot; процесс разбора критичных CVE. |
| SEC-I2 | P2 | **Внешний пентест или bug bounty** | После стабилизации API — заказной пентест или программа вознаграждений. |

---

## Epic J — Инциденты и админ-доступ

| ID | Приоритет | Тикет | Критерии приёмки |
|----|-----------|-------|------------------|
| SEC-J1 | P1 | **Incident response runbook** | Кто останавливает деплой/бота; ротация токенов; эскалация; шаблон уведомления пользователей (при утечке). |
| SEC-J2 | P2 | **Админы (`admin_telegram_ids`)** | Список актуален; минимальное число ID; при появлении веб-админки вне Telegram — отдельная модель аутентификации (2FA и т.д.). |

---

## Рекомендуемый порядок (релиз)

1. **До прод:** SEC-A1, SEC-A2, SEC-B1, SEC-C1, SEC-C2, SEC-D1, SEC-E1, SEC-F1, SEC-G1.  
2. **Первые спринты после релиза:** SEC-B2, SEC-C3, SEC-G2, SEC-G3, SEC-H1, SEC-H2, SEC-I1, SEC-J1.  
3. **По мере роста:** SEC-H3, SEC-I2, SEC-J2, SEC-A3.

---

## Связь с кодом (ориентиры)

| Область | Файлы / модули |
|---------|----------------|
| Валидация `initData` + `auth_date` | `src/shared/telegram_webapp.py` |
| Угрозы и env для Mini App | [`docs/TELEGRAM_WEBAPP_INITDATA.md`](TELEGRAM_WEBAPP_INITDATA.md) |
| Webapp API и `init_data` | `src/api/routes/webapp.py`, `src/api/routes/webapp_trainer_profile.py` |
| Публичный API и фото | `src/api/routes/public.py`, префиксы ключей — `src/infrastructure/s3.py` |
| CORS | `src/api/app.py` |
| Rate limit бота | `src/bot/middlewares/rate_limit_middleware.py`, `src/shared/rate_limit.py` |
| Rate limit HTTP API, размер тела | `src/api/middleware/http_limits.py`, `src/api/app.py` |

---

*Последнее обновление: 2026-03-30*
