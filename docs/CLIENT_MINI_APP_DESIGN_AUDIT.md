# Аудит дизайна: мини-приложения клиентского бота

Дата: 2026-03-29.  
**Эталон глобального дизайна:** [`static/webapp/theme.css`](../static/webapp/theme.css) (токены `--tg-theme-*`, `--app-*`), [`static/webapp/mini-app-components.css`](../static/webapp/mini-app-components.css), для детальных экранов — принципы из [`docs/TRAINER_MINI_APP_VISUAL_CONSTITUTION.md`](TRAINER_MINI_APP_VISUAL_CONSTITUTION.md) (правила общие для CRM-мини-приложений).

**Охват:** только HTML, отдаваемые как клиентские Mini App (`/webapp/catalog`, `/webapp/book`, `/webapp/client-*`).

| Файл | Маршрут |
|------|---------|
| `catalog.html` | `/webapp/catalog` |
| `book.html` | `/webapp/book` |
| `client-requests.html` | `/webapp/client-requests` |
| `client-bookings.html` | `/webapp/client-bookings` |
| `client-buy-pass.html` | `/webapp/client-buy-pass` |
| `client-passes.html` | `/webapp/client-passes` |
| `client-certificates.html` | `/webapp/client-certificates` |
| `client-passes-certificates.html` | `/webapp/client-passes-certificates` |

---

## 1. Подключение общих стилей

| Страница | `theme.css` | `mini-app-components.css` |
|----------|-------------|---------------------------|
| catalog, book, client-requests | да | да |
| client-bookings, client-buy-pass, client-passes, client-certificates, client-passes-certificates | да | **нет** |

**Несоответствие:** шесть из девяти страниц не подключают слой компонентов. Повторяются локальные кнопки/карточки вместо единых `.btn-primary` / паттернов из `mini-app-components.css`.

---

## 2. Синхронизация с Telegram / тёмная тема

Страницы **catalog.html**, **book.html**, **client-requests.html** выставляют CSS-переменные из `Telegram.WebApp.themeParams` hex-ами, согласованными с `theme.css` (фон `#1c1c1c`, вторичные `#2c2c2e`, акцент `#f5a623`).

Остальные клиентские страницы используют **отдельный** паттерн: короткий IIFE внизу `<head>` с `#F7A600`, фоном тёмной темы `#1a1a1a`, карточками `#2a2a2a`, светлыми поверхностями `#FFF3CC` / `#FFFBEB`.

**Несоответствие:**

- Акцент: **`#F7A600`** вместо токена **`#f5a623`** (`--tg-theme-button-color` в `theme.css`).
- Тёмный фон: **`#1a1a1a`** вместо **`#1c1c1c`**.
- Тёмные карточки: **`#2a2a2a`** вместо **`#2c2c2e`**.
- Светлая вторичная поверхность: **`#FFF3CC`** вместо **`#fff5e1`** (`--tg-theme-secondary-bg-color` в светлой теме).

В `client-bookings.html` дополнительно переопределяются `--tg-theme-bg-color` и `--tg-theme-secondary-bg-color` через тот же IIFE — при открытии в Telegram с кастомной темой возможен **рассинхрон** с теми тремя страницами, где тема применяется через `themeParams`.

---

## 3. «Запрещённые» сырые hex на body/карточках (`!important`)

В нескольких файлах блоки `@media (prefers-color-scheme: light|dark)` жёстко задают фон и цвет карточек через `#FFFBEB`, `#FFF3CC`, `#1a1a1a`, `#2a2a2a` с `!important`, минуя `var(--tg-theme-*)`.

**Где:** `catalog.html` (в т.ч. табы), `client-bookings.html`, `client-passes.html`, `client-buy-pass.html`, `client-certificates.html`, `client-passes-certificates.html`.

**Конфликт с правилами:** в конституции и в комментарии к `theme.css` — не вводить произвольные hex на body/карточках; локальные градиенты — по образцу из `mini-app-components.css`.

---

## 4. Семантические цвета (ошибка / успех)

| Место | Использование | Токен в `theme.css` |
|-------|----------------|---------------------|
| `client-passes.html`, `client-buy-pass.html`, `client-certificates.html`, `client-passes-certificates.html` | `.error { color: #ef4444; }` | `--app-danger: #ff3b30` |
| `client-requests.html` | `#ff453a` у кнопки удаления | то же |
| `catalog.html` | зелёный `#30d158` (чип/статус) | `--app-success: #34c759` |
| `client-bookings.html`, `client-buy-pass.html` | бейджи `#ff9500`, `#34c759` | частично близко к системным iOS, но не к `--app-*` |

**Несоответствие:** палитра ошибок/успеха разъезжается (Tailwind-подобный `#ef4444` vs фирменный красный CRM).

---

## 5. Типографика

| Страницы | Шрифт body |
|----------|------------|
| catalog, book, client-requests | `'DM Sans'` + системный стек |
| client-bookings | `var(--app-font-sans)` (системный стек из `theme.css`) |
| client-passes, client-buy-pass, client-certificates, client-passes-certificates | явный системный стек без DM Sans |

**Несоответствие:** в конституции для «премиальных» и детальных экранов указан **DM Sans**; три главных клиентских потока (каталог, запись, заявки) его используют, остальные — нет, визуально **разные семейства** между разделами одного бота.

---

## 6. Градиенты CTA и кнопки

- **catalog.html**, **client-requests.html**: основной CTA градиентом `#f5a623` → `#e89400` — соответствует янтарной линии.
- **book.html**: градиент `#ffc23d` → `#f0a000` и текст `#141414` — отличается от типичного `btn-primary` в `mini-app-components.css` (другой набор стопов и контраст текста).

**Несоответствие:** три разных «оранжевых» градиента на клиентских экранах без единого класса.

---

## 7. Прочее

- **client-certificates.html**, **client-passes-certificates.html**: у полей ввода inline `border: 1px solid rgba(0,0,0,0.1)` — в тёмной теме граница почти не видна; лучше `rgba` от `--tg-theme` или класс из общих стилей.
- **catalog.html**: дублирование установки темы — скрипт `applyTelegramTheme` + отдельный IIFE с `#F7A600` и другими hex (два источника правды на одной странице).
- **client-requests.html**: частично использует токены (`var(--tg-theme-secondary-bg-color)` в градиентах карточек), но встречаются и «сырые» rgba с фиксированным янтарём `245, 166, 35` — допустимо для блика, но стоит проверить единообразие с `catalog.html`.

---

## 8. Рекомендуемые направления выравнивания (без изменения кода здесь)

1. Подключить **`mini-app-components.css`** ко всем клиентским страницам и переиспользовать `.btn-primary`, `.btn-secondary`, единые отступы.
2. Убрать **IIFE с фиксированными hex** на страницах passes/certificates/bookings/buy-pass: либо общий скрипт как в catalog/book/client-requests, либо только `theme.css` + `Telegram.WebApp` при наличии.
3. Выровнять **тёмные фоны** на `#1c1c1c` / `#2c2c2e` и акцент на **`#f5a623`**.
4. Заменить **#ef4444** на `var(--app-danger)` для ошибок.
5. Рассмотреть единый **DM Sans** (как в `mini-app-components.css` для эталонных экранов) или осознанно оставить системный стек везде — но не смешивать без причины.

---

*Документ сгенерирован по статическому сканированию `static/webapp/*.html` клиентского бота; после правок вёрстки имеет смысл обновить разделы 1–7.*
