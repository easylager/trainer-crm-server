# Research: Mini App shared theme

## 1. Единый файл стилей

**Decision:** Один файл `static/webapp/theme.css`, подключается через `<link rel="stylesheet" href="theme.css">` с путём относительно текущего документа (все страницы лежат в одной папке `static/webapp/`).

**Rationale:** Без сборщика и npm для статики — простой HTTP-кэш, предсказуемые пути при раздаче через FastAPI/static.

**Alternatives considered:** Inline `<style>` с `@import url(theme.css)` (хуже кэш и порядок); общий `.js`-бандл — избыточно для CSS-only задачи.

## 2. Именование токенов: `--tg-theme-*` vs `--app-*`

**Decision:** Ввести семантический слой `--app-*` (например `--app-bg`, `--app-text`, `--app-surface`, `--app-accent`, `--app-accent-text`, `--app-muted`, `--app-danger`), в `:root` задать значения по умолчанию, совпадающие с текущими продуктовыми hex из `catalog.html` / `book.html`. Опционально: `theme.css` может устанавливать `--app-*` из `var(--tg-theme-*)` там, где Telegram уже проставил переменные (если страница вызывает `Telegram.WebApp` и тема доступна).

**Rationale:** Конституция требует одного источника правды; `--tg-*` остаётся мостом к Telegram, `--app-*` — стабильный контракт для компонентных классов.

**Alternatives considered:** Только `--tg-theme-*` без `--app-*` — имена привязаны к Telegram и не покрывают семантику «ошибка/успех».

## 3. Тёмная тема

**Decision:** Сохранить подход `prefers-color-scheme: dark` и/или класс на `<html>`, как в существующих страницах; значения токенов для тёмной ветки задавать внутри `theme.css` в одном месте (`@media` или `:root.tg-dark` после договорённости с JS).

**Rationale:** Уже используется в кодовой базе; централизация убирает расхождения между HTML.

## 4. Миграция

**Decision:** Итеративно: (1) добавить `theme.css` + контракт токенов; (2) пилот 2 страницы; (3) остальные по списку в tasks; (4) скрипт `grep '#[0-9a-fA-F]' static/webapp/*.html` как ручную проверку на хвосты.

**Rationale:** Снижает риск регрессий в WebView.

## 5. Тестирование

**Decision:** Автотесты не обязательны для CSS-токенов; ручной smoke в Telegram + опционально лёгкий grep/CI на запрет новых hex вне `theme.css` (future).

**Rationale:** Нет существующего visual-regression pipeline в репо; FR по домену не затронуты.

## 6. Реализация (2026-03-23)

- Добавлен `static/webapp/theme.css` с `--tg-theme-*`, `--app-*`, светлая база и `@media (prefers-color-scheme: dark)`.
- Все `static/webapp/*.html` подключают `theme.css`; дублирующие блоки `:root` с базовыми цветами удалены там, где были идентичны каталогу.
- `trainer-stats.html` и `trainer-pass-products.html`: локальные `--tg-theme-*` убраны в пользу `theme.css`; оставлены только дашборд-специфичные (`--card-bg`, `--accent-dim`, `--up`, `--down`, `--muted` и т.д.). Базовая тема теперь **light-first**, как в остальных Mini App (раньше часть экранов была dark-first — возможное визуальное отличие в светлой ОС).
- `book.html`: удалены жёсткие `!important` на body/кнопки и IIFE, дублировавшие токены; пилот `catalog.html` — hex в `.btn-primary` заменены на `var(--tg-theme-button-color)`.
- **Техдолг:** во многих файлах остаются блоки «JUSTSKATE — перебить Telegram» с `#FFFBEB` / `#F7A600` и короткие IIFE в конце `<body>`; они избыточны рядом с `theme.css`, но функционально совместимы. Следующий проход — заменить на `var(--app-*)` / `var(--tg-theme-*)` и убрать скрипты.
