# Contract: Mini App CSS design tokens

Источник правды после внедрения: `static/webapp/theme.css`.

## Обязательные переменные (v1)

Страницы, прошедшие миграцию, **MUST** использовать для соответствующей семантики только эти имена (или их `var()`-цепочки), а не «сырые» hex в правилах компонентов.

| Variable | Role |
|----------|------|
| `--app-bg` | Main viewport background |
| `--app-text` | Primary text |
| `--app-surface` | Elevated surfaces (cards, inputs background) |
| `--app-muted` | Secondary / hint text |
| `--app-accent` | Primary button / key action fill |
| `--app-accent-text` | Text/icon on primary button |
| `--app-danger` | Error text or error borders |

## Опционально (v1.1+)

| Variable | Role |
|----------|------|
| `--app-success` | Success states |
| `--app-border` | Default border color |
| `--app-radius-sm`, `--app-radius-md` | Border radii |

## Мост к Telegram

Если на странице доступны `Telegram.WebApp.themeParams`, скрипт или `theme.css` **MAY** синхронизировать `--app-*` с `--tg-theme-*`. Имена `--tg-theme-*` **SHOULD NOT** размножаться в инлайн-стилях новых экранов — только в `theme.css`.

## Порядок подключения

```html
<link rel="stylesheet" href="theme.css" />
<!-- затем при необходимости page-local overrides, минимальные -->
```
