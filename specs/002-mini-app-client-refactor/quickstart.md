# Quickstart: 002-mini-app-client-refactor

## 1. Активная фича в Spec Kit

На ветке `develop`:

```bash
export SPECIFY_FEATURE=002-mini-app-client-refactor
# или: см. `.specify/active-feature` в [docs/SPEC_KIT.md](../../docs/SPEC_KIT.md)
```

## 2. Аудит бота

1. Локально или на staging: запустить `client_app`, пройти сценарии из [spec.md](./spec.md) (справка, каталог, запись, заявки, мои записи, поддержка).
2. Заполнить находки (можно таблицей в PR или в `audit-findings.md` в этой папке — не коммитить PII).
3. Пройти [contracts/client-ux-checklist.md](./contracts/client-ux-checklist.md).

## 3. Аудит Mini App

1. Открыть `static/webapp/client-*.html` в Telegram WebView (светлая/тёмная тема).
2. Сверить с `theme.css` и [specs/001-mini-app-theme-css/contracts/theme-tokens.md](../001-mini-app-theme-css/contracts/theme-tokens.md) при необходимости.

## 4. Код

- Строки бота: `src/bot/messages.py`, хендлеры: `src/bot/handlers/client_handlers.py`.
- После правок: см. конституцию п. III — тесты на регрессию при изменении поведения.

## 5. Следующий шаг

`/speckit.tasks` → исполнение по `tasks.md`.
