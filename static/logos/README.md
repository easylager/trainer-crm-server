# GLIDE logos

Бренд: **GLIDE — Digital Skating Ecosystem**  
Исходники от дизайнера разложены по роли. Точные дубликаты (одинаковые пиксели) отброшены в `_source/duplicates-skipped/`.

## Цвета бренда (из макетов)

| Роль | Hex (примерно) | Где |
|------|----------------|-----|
| Accent / primary | `#47B6B9` | знак, акценты UI |
| Ink on light | `#000000` | текст на белом |
| Ink subtle on dark | `#2B2B2B` … `#333333` | «тёмный» lockup на чёрном (низкий контраст) |
| Ink on dark | `#FFFFFF` | белые lockup’ы |
| Canvas dark | `#000000` | dark theme |
| Canvas light | `#FFFFFF` | light / landing |

> Для UI на чёрном фоне **не** используй dark-text варианты как основной текст — они decorative/subtle. Для читаемости: `white-on-black` или `teal-icon-black-text-on-white`.

## Что для чего

### `01-icon/` — только знак
Иконка приложения, favicon, аватар бота, маленький логотип в навбаре.

| Файл | Когда брать |
|------|-------------|
| `glide-icon-teal-on-black.png` | **Основной** brand mark |
| `glide-icon-white-on-black.png` | Dark UI, когда нужен нейтральный белый знак |
| `glide-icon-dark-on-black.png` | Watermark / очень subtle |

### `02-horizontal-full/` — знак + GLIDE + tagline в ряд
Шапка сайта, презентации, email, широкий header.

| Файл | Когда брать |
|------|-------------|
| `glide-horizontal-teal-icon-black-text-on-white.png` | **Основной light** (лендинг, светлая тема) |
| `glide-horizontal-white-on-black.png` | **Основной dark** header |
| `glide-horizontal-all-teal-on-black.png` | Акцентный / marketing dark |
| `glide-horizontal-teal-icon-dark-text-on-black.png` | Brand art на чёрном (текст слабо читается) |
| `glide-horizontal-dark-on-black.png` | Subtle / footer art |

### `03-stacked-full/` — знак сверху, GLIDE + tagline снизу
Splash, about, квадратные превью, сторис.

| Файл | Когда брать |
|------|-------------|
| `glide-stacked-white-on-black.png` | Основной stacked dark |
| `glide-stacked-all-teal-on-black.png` | Акцентный stacked |
| `glide-stacked-teal-icon-dark-text-on-black.png` | Brand art (текст subtle) |
| `…-alt.png` | Другой кроп того же варианта — можно удалить позже, если не нужен |

### `04-stacked-wordmark/` — знак + GLIDE **без** tagline
Login, app splash, Telegram WebApp header, где tagline не нужен.

| Файл | Когда брать |
|------|-------------|
| `glide-wordmark-white-on-black.png` | **Основной** app mark dark |
| `glide-wordmark-all-teal-on-black.png` | Акцентный |
| `glide-wordmark-teal-icon-dark-text-on-black.png` | Brand art |
| `…-alt.png` | Альтернативный кроп |

## Рекомендация для редизайна системы

1. **Light UI / landing:** `02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png` + icon teal  
2. **Dark mini-app / CRM:** `01-icon/glide-icon-teal-on-black.png` + `04-stacked-wordmark/glide-wordmark-white-on-black.png`  
3. **CSS primary:** `#47B6B9` (уточнить у дизайнера точный токен, если есть)

## Каталог файлов

- `01-icon/glide-icon-dark-on-black.png` (1024×345) — Только знак. Тёмный charcoal на чёрном — subtle / watermark.
  - source: `24.08________1-6636c015-388f-45c7-a3da-897a870180fc.png`
- `01-icon/glide-icon-white-on-black.png` (1024×345) — Только знак. Белый на чёрном — favicon / аватар в dark UI.
  - source: `24.08________3-ffd83437-03b2-4761-9ed0-a54f58bdbb7c.png`
- `01-icon/glide-icon-teal-on-black.png` (1024×345) — Только знак. Teal brand accent — основной icon / favicon.
  - source: `24.08___________________1_______3-db6c072f-01df-4dd7-b4e4-5fb23ea80e55.png`
- `02-horizontal-full/glide-horizontal-all-teal-on-black.png` (1024×345) — Горизонтальный lockup целиком teal. Шапка / баннер dark.
  - source: `24.08_________2-ab75a3c4-1565-484a-a8bd-a410305328a2.png`
- `02-horizontal-full/glide-horizontal-dark-on-black.png` (1024×345) — Горизонтальный lockup charcoal на чёрном — subtle.
  - source: `24.08_________4-3c25774c-ae2c-40e6-a9e1-0b24def23da3.png`
- `02-horizontal-full/glide-horizontal-teal-icon-dark-text-on-black.png` (1024×345) — Teal знак + тёмный текст. Brand lockup для dark UI.
  - source: `24.08___________2_-a3883f4a-14a1-402a-bd9a-b2f53e239169.png`
- `02-horizontal-full/glide-horizontal-white-on-black.png` (1024×345) — Горизонтальный lockup белый на чёрном — основной dark header.
  - source: `24.08___________________1_______2-f6ea7241-4800-48fa-9750-9e731dbbb3ca.png`
- `02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png` (1024×558) — Teal знак + чёрный текст на белом — основной light / landing.
  - source: `photo_2026-08-21_18-20-27-448db22a-cdce-426b-9bd8-0ab3bed1b23c.png`
- `03-stacked-full/glide-stacked-teal-icon-dark-text-on-black.png` (1024×751) — Стек: teal знак сверху, тёмный GLIDE + tagline. Splash / about.
  - source: `24.08_______________-f8df913c-d4a2-4cf8-a9c4-497212073954.png`
- `03-stacked-full/glide-stacked-teal-icon-dark-text-on-black-alt.png` (1024×751) — Альт. кроп того же stacked teal+dark (другой кадр от дизайнера).
  - source: `24.08________________-1619199d-c7bb-4dc9-9eda-b63703af072f.png`
- `03-stacked-full/glide-stacked-all-teal-on-black.png` (1024×751) — Стек целиком teal на чёрном.
  - source: `24.08________________3-543e4f7e-ce9b-4b6a-b57d-4cc380ee2561.png`
- `03-stacked-full/glide-stacked-white-on-black.png` (1024×751) — Стек белый на чёрном.
  - source: `24.08________________4-7dc6f77f-9dfb-450c-abf0-6a510534aa47.png`
- `03-stacked-full/glide-stacked-dark-on-black.png` (1024×751) — Стек charcoal на чёрном — subtle.
  - source: `24.08______________________-1f0ad887-3cd8-4af2-be5c-c2e22deaa2bf.png`
- `03-stacked-full/glide-stacked-white-on-black-alt.png` (1024×751) — Альт. кроп stacked white.
  - source: `24.08_______________________3-caa1badb-ff66-46d6-b274-a4766bd370b4.png`
- `04-stacked-wordmark/glide-wordmark-teal-icon-dark-text-on-black.png` (1024×751) — Знак + GLIDE без tagline. App splash / login.
  - source: `24.08________________5-00c058cc-403d-4b54-9ca4-ee953c79bd84.png`
- `04-stacked-wordmark/glide-wordmark-dark-on-black.png` (1024×751) — Знак + GLIDE charcoal — subtle.
  - source: `24.08________________6-f45191e6-e177-4f9d-8c4d-b52d759eb850.png`
- `04-stacked-wordmark/glide-wordmark-all-teal-on-black.png` (1024×751) — Знак + GLIDE целиком teal.
  - source: `24.08________________7-3902a7d4-9b08-4867-8bc0-cbcad3bf77f1.png`
- `04-stacked-wordmark/glide-wordmark-white-on-black.png` (1024×751) — Знак + GLIDE белый — основной app mark dark.
  - source: `24.08________________8-26c00477-0b91-41c9-b3fd-a69801a343dc.png`
- `04-stacked-wordmark/glide-wordmark-teal-icon-dark-text-on-black-alt.png` (1024×751) — Альт. кроп wordmark teal+dark.
  - source: `24.08_______________________4-27397010-27e4-48a0-bfbc-3e552eecab36.png`
- `04-stacked-wordmark/glide-wordmark-all-teal-on-black-alt.png` (1024×751) — Альт. кроп wordmark all-teal.
  - source: `24.08_______________________6-dcbb3634-d30f-469c-933e-44ce7af3d4bf.png`
- `04-stacked-wordmark/glide-wordmark-white-on-black-alt.png` (1024×751) — Альт. кроп wordmark white.
  - source: `24.08_______________________7-209bc550-a9a8-4ea9-90e9-aed6c2f7d677.png`

## `_source/`
Оригинальные имена файлов от дизайнера (для сверки). Не использовать в UI напрямую.
