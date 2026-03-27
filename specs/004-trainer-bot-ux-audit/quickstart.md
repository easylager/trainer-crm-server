# Quickstart: 004-trainer-bot-ux-audit

## 1. Активная фича в Spec Kit

На ветке фичи или через переменную окружения:

```bash
export SPECIFY_FEATURE=004-trainer-bot-ux-audit
```

При необходимости см. `.specify/active-feature` и [docs/SPEC_KIT.md](../../docs/SPEC_KIT.md).

## 2. Запуск тренерского бота локально

- Токен: `telegram_bot_token_trainer` в `.env` (не коммитить).
- Запуск: `python -m src.bot.trainer_app` (см. [trainer_app.py](../../src/bot/trainer_app.py)).
- Уведомления — отдельный процесс; для UX-аудита основных сценариев достаточно polling тренерского бота.

## 3. Аудит сценариев в боте

1. Войти по продуктовому сценарию (ссылка `t.me/...?start=link_<token>` или тестовый токен по правилам команды).
2. Пройти минимум **5** сценариев из спека (меню: расписание, заявки, записи, клиенты, абонементы, подписка, статистика, помощь — выбрать приоритетные для продукта).
3. Зафиксировать находки в таблице по полям [data-model.md](./data-model.md) (в PR или временном файле в ветке — **без PII**).
4. Пройти [contracts/trainer-ux-checklist.md](./contracts/trainer-ux-checklist.md).

## 4. Аудит Mini App (тренер)

1. Из бота открыть каждый релевантный Web App (`trainer-*.html`).
2. Проверить светлую/тёмную тему Telegram при необходимости.
3. Сверить с [theme.css](../../static/webapp/theme.css) и § VIII.

## 5. Код

- Хендлеры: [trainer_handlers.py](../../src/bot/handlers/trainer_handlers.py).
- Строки: [messages.py](../../src/bot/messages.py).
- После правок: конституция п. III — тесты при изменении поведения; иначе чеклист.

## 6. Следующий шаг

`/speckit.tasks` → исполнение по `tasks.md`.
