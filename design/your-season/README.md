# Макеты эпика your-season — первая итерация

Источник правды по виду для задач TASK-366…377. Всё здесь открывается без Claude: HTML — в любом браузере, PNG — картинкой.

## Экраны

| Экран | HTML | PNG | Задача |
|---|---|---|---|
| Новый таб-бар: 4 и 5 вкладок, смысл каждой | [tab-bar.html](tab-bar.html) | [png](png/tab-bar.png) | TASK-369 |
| «Я» — в сезоне (клуб, каток, цифры, строки), светлая | [me-season-light.html](me-season-light.html) | [png](png/me-season-light.png) | TASK-370 |
| «Я» — в сезоне, тёмная | [me-season-dark.html](me-season-dark.html) | [png](png/me-season-dark.png) | TASK-370 |
| «Я» — первый день (ничего не выбрано), светлая | [me-new-light.html](me-new-light.html) | [png](png/me-new-light.png) | TASK-370 |
| «Я» — первый день, тёмная | [me-new-dark.html](me-new-dark.html) | [png](png/me-new-dark.png) | TASK-370 |
| «За кого болеешь?» — клуб выбран | [club-picker.html](club-picker.html) | [png](png/club-picker.png) | TASK-371 |
| «За кого болеешь?» — ничего не выбрано | [club-picker-none.html](club-picker-none.html) | [png](png/club-picker-none.png) | TASK-371 |
| «Мой каток» — шаг 1, выбор | [rink-picker-step1.html](rink-picker-step1.html) | [png](png/rink-picker-step1.png) | TASK-372 |
| «Мой каток» — шаг 2, «Писать о новом расписании?» | [rink-picker-step2.html](rink-picker-step2.html) | [png](png/rink-picker-step2.png) | TASK-372 |
| «Как тебя зовут?» — имя изменено | [name-sheet.html](name-sheet.html) | [png](png/name-sheet.png) | TASK-373 |
| «Как тебя зовут?» — пусто | [name-sheet-empty.html](name-sheet-empty.html) | [png](png/name-sheet-empty.png) | TASK-373 |
| «Кто кого» во вкладке (скриншоты игры 11.11 + бар) | [kk-tab.html](kk-tab.html) | [png](png/kk-tab.png) | TASK-374 |

PNG — 390 px по ширине в масштабе 2× (780 px), как экран телефона. HTML — та же разметка с inline-стилями: отступы, кегли, радиусы, тексты брать прямо из неё (DevTools → Inspect).

## Папки

- `*.html`, `png/` — готовые экраны (сгенерированы, руками не править).
- `source/*.dc.html` — исходники экранов в формате холста (данные и состояния — в `renderVals()`).
- `source/support.js` — мини-рендер этого формата; `tools/export.js` — пересборка HTML и PNG.
- `img/` — картинки, которые используют экраны (скриншоты игры).

Изменили исходник — пересобрать из корня репозитория:

```bash
node design/your-season/tools/export.js
```

(нужен установленный `playwright` с Chromium — он уже есть в `node_modules`). Список экранов и состояний — массив `JOBS` в `tools/export.js`.

Живой холст с теми же экранами (и отложенными рядами «Главная», «ПОЗЖЕ»): https://claude.ai/artifact/Nd37p9Ak6gHPPYsHT1u1dQ — приватный, нужен доступ от владельца. Для работы он не нужен: всё есть здесь.

## Цвета: макет → токены кода

В коде — только токены `static/shared/glide-tokens.css` (светлая `:root`, тёмная `body.tg-dark`). Хексы макета им равны:

| Макет (`t.*`) | Светлая | Тёмная | Токен |
|---|---|---|---|
| `bg` | #f5f7f8 | #17212b | `--g-bg` |
| `surface` | #ffffff | #1d2733 | `--g-surface` |
| `ink` | #0d1b26 | #f1f5f7 | `--g-ink` |
| `ink2` | #4a5f71 | #c3d2dc | `--g-ink-2` |
| `muted` | #5d7285 | #8aa0b3 | `--g-muted` |
| `line` | #e1e8ec | #2b3744 | `--g-line` |
| `lineStrong` | #c9d5dc | #3a4857 | `--g-line-strong` |
| `accentInk` | #0B6E70 | #7FD7D8 | `--g-accent-ink` |
| `wash` | #D3EFEF | #163638 | `--g-accent-wash` |
| кнопка-заливка | #45B9BB, текст #04262A | #7FD7D8, текст #04262A | `--g-accent` / `--g-on-accent` |
| `chip` | #eef2f4 | #263240 | нет токена — завести `--g-chip` в обоих блоках (TASK-370) |
| `shadow` | `0 1px 2px rgba(13,27,38,.05), 0 10px 28px -18px rgba(13,27,38,.35)` | `0 1px 2px rgba(0,0,0,.3)` | `--glide-shadow-card` (светлая) |

Шрифты: Dela Gothic One — заголовки и цифры; Golos Text — остальное. В коде — локальные `/static/shared/glide-public-fonts.css`; Google Fonts в макетах только для просмотра.

Шторки нарисованы в светлой теме; тёмная — те же токены из таблицы.

## Что в макетах условно

- Цифры (14 тренировок, 3 недели, 340 очков, 12-е место, «4 занятия», «Аня» (имена людей семьи, не число), «5»), имя «Максим», «Матч в пятницу, 19:00», сеансы катков — примеры; в коде всё из `GET /client/me` (контракт — TASK-368) и источников «Поиска».
- Обложка «Я» в макете синяя с красной полосой. В коде — сплошной `club.color` без полосы (второго цвета у клуба в данных нет), подпись клуба цветом `club.label_ink`.
- Значки клубов в «За кого болеешь?» серые с буквой. В коде — `logo` из `team_card()`, нет логотипа — круг `color` с `short`.
- «Мои записи» в «Я» показана, потому что в баре макета 4 вкладки; при вкладке «Записи» строки нет.
- `kk-tab` — скриншоты игры 11.11 плюс бар: игру не перерисовываем.
