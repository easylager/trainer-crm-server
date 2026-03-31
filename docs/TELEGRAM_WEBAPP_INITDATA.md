# Telegram Web App: `initData` и безопасность

Клиент (Mini App) передаёт строку `initData` в заголовке `X-Telegram-Init-Data` или в query `init_data`. **Доверять этой строке без проверки на сервере нельзя:** любой может отправить поддельный запрос с чужим `user` в JSON.

## Что делает бэкенд

1. **HMAC-SHA256** — проверка подписи по токену **соответствующего** бота (клиентский / тренерский / админский), см. [документацию Telegram](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).
2. **`auth_date`** — Unix-время, когда пользователь открыл Web App. Запрос отклоняется, если `auth_date` отсутствует, слишком далеко в будущем (учёт расхождения часов) или **старше окна** (по умолчанию 24 часа). Это ограничивает **replay**: перехваченная ранее валидная строка `initData` не годится бесконечно.

Реализация: `src/shared/telegram_webapp.py` (`validate_init_data`, `require_telegram_user_id`).

## Настройка окна

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `TELEGRAM_WEBAPP_INIT_DATA_MAX_AGE_SEC` | `86400` | Максимальный возраст `auth_date` в секундах. |
| `TELEGRAM_WEBAPP_INIT_DATA_CLOCK_SKEW_SEC` | `300` | Допустимое «будущее» для `auth_date` относительно часов сервера. |

## Единая точка входа для API

Эндпоинты под `/api/webapp/...` не должны сами парсить `initData`: используется `require_telegram_user_id` (или обёртки `_get_telegram_id_from_init_data` / `_trainer_telegram_id_from_init` в роутерах), чтобы везде применялись одни и те же правила (токен бота + `auth_date` + наличие `user.id`).

Админские маршруты дополнительно проверяют, что `telegram_id` входит в `ADMIN_TELEGRAM_IDS`.

## См. также

- [ENVIRONMENT.md](ENVIRONMENT.md) — переменные окружения.
- [SECURITY_BACKLOG.md](SECURITY_BACKLOG.md) — эпик B.
