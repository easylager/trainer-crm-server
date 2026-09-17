# Parser spec: ВТБ Арена (каток «Академия спорта Динамо»)

- arena_id: 53
- city: Москва
- parser_key: vtbarena_qtickets_v1
- cadence: weekly
- requires_by_egress: false
- requires_auth: true (Qtickets REST API — see blockers)

Прод-адрес арены — Ленинградский пр-т 36 (территория «ВТБ Арена Парк» / стадион «Динамо»). Сама услуга «Катание на крытой ледовой площадке» физически проходит в здании **«Академия спорта Динамо»**, ул. Юрия Никулина, 3 — это отдельное здание внутри того же комплекса ВТБ Арена Парк (5 минут от м. Динамо / м. Петровский парк), не отдельная арена. Цепочка подтверждена официальной навигацией: `vtb-arena.com` (пункт меню «Посетителям» → «Массовое катание») → редирект `arena-park.ru/ice-skating/` (301) → `akademiya-dynamo.ru/services/katanie-na-krytoy-ledovoy-ploshchadke/`. Несовпадение адреса — не ошибка выбора источника, а особенность комплекса (несколько зданий, один прод-arena_id).

## Sources

- schedule/prices: https://akademiya-dynamo.ru/services/katanie-na-krytoy-ledovoy-ploshchadke/ (Bitrix, статический HTML — но **только** цены и правила, календаря дат/времени сеансов в DOM нет)
- widget/api: Qtickets, `data-event-id="136634"`, JS `https://qtickets.ru/js/openapi` (SPA). REST `https://qtickets.ru/api/rest/v1/shows/136634` и `.../events/136634` отвечают `403 {"error":"Wrong authorization"}` без API-ключа/Bearer.
- публичная страница события `https://qtickets.ru/event/136634` (200, реальная арена/название подтверждены — «Катание на крытой ледовой площадке Академии спорта «Динамо»»), но это тоже SPA-обёртка: в отданном HTML нет ни одной даты/времени (проверено grep на `HH:MM` и месяцы — пусто), данные подгружаются JS после аутентифицированного запроса.
- job.config JSON (черновик, для будущего runner с API-ключом):

```json
{
  "prices_url": "https://akademiya-dynamo.ru/services/katanie-na-krytoy-ledovoy-ploshchadke/",
  "qtickets_event_id": 136634,
  "qtickets_api_base": "https://qtickets.ru/api/rest/v1",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "session_name": "Массовое катание",
  "price_adult_minor": 60000,
  "price_child_minor": 40000,
  "price_child_note": "7-17 лет, студенты вузов РФ",
  "price_preferential_minor": 20000,
  "price_rental_minor": 30000,
  "prices_already_minor": false,
  "requires_by_egress": false,
  "requires_auth": true,
  "auth_note": "Qtickets REST v1 shows/events возвращает 403 Wrong authorization без ключа. Нужен API-токен организатора (Qtickets Open API) или headless-рендер SPA с реальной сессией."
}
```

## How to extract (reverse)

1. GET `https://akademiya-dynamo.ru/services/katanie-na-krytoy-ledovoy-ploshchadke/` без авторизации — отдаётся статически (Bitrix, `bitrix/cache/css/...`), geo-блока нет (проверено обычным `curl` без прокси и через WebFetch, идентичный контент).
2. На странице — блок `<section class="schedule">` с `.schedule__itprice`: три «Входной билет» (взрослый/детский/льготный) и прокат инвентаря. Это статический прайс, **не** сетка сеансов. Текст прямо предупреждает: «Расписание сеансов появляется по пятницам в течение дня» и «Билеты на сеансы появляются в продаже по пятницам в течение дня» — источник обновляется **еженедельно по пятницам**, каденс `weekly`.
3. Кнопки «Купить билет» — не `<a href>`, а `<a rel="qtickets" data-event-id="136634" ...>`, перехватываются `qtickets.ru/js/openapi` и открывают модальное окно виджета Qtickets. Самого iframe/src в статическом HTML нет (открывается JS `onclick`).
4. Публичная страница `https://qtickets.ru/event/136634` (не встроенный виджет, отдельный URL) грузится (200), подтверждает событие, но весь календарь дат/сеансов рендерится SPA после запроса к REST API, которое требует авторизации.
5. Проверены прямые REST-эндпоинты: `GET /api/rest/v1/shows/136634` → `403 Wrong authorization`; `GET /api/rest/v1/events/136634` → тот же 403. Пути `/api/rest/v1/shows/136634/events`, `/api/v1/shows/136634/events`, `/api/widget/shows/136634` → 404 (не существуют / другой формат пути). Прямых виджет-эндпоинтов `qtickets.ru/widget/136634` и `qtickets.ru/iframe/136634` — таймаут соединения при повторных попытках (не подтверждён рабочий путь).
6. Даты/время сеансов **не публиковать** без реального ответа API — выдумывать сетку запрещено (см. паттерн `minsk-junost.md` / `minsk-ledlife.md`).
7. Цены и правила — parse-able уже сейчас: `600 руб.` взрослый, `400 руб.` детский (7–17 лет, студенты вузов РФ), `200 руб.` льготный (пенсионеры, многодетные, ветераны труда). Прокат коньков `300 руб.`, «помощник пингвин» `300 руб.`, шлем `250 руб.`, наколенники/налокотники/перчатки `200 руб.` — плоские допуслуги, не по сеансам.
8. Длительность сеанса на странице не указана нигде (ни цифрой, ни текстом) — `default_duration_minutes` неизвестен, не угадывать. Уточнять из реального ответа Qtickets API, когда появится ключ.
9. `age_note`: детский тариф — «7-17 лет, студенты вузов РФ» (не просто возраст, включает студентов).

## Canonical example (expected after validate)

Слотов нет — терминал для V1 без API-ключа Qtickets. `sessions: []`, `blocked_reason: "qtickets_rest_api_requires_auth"`. Прайс и `kind=public_skate` подтверждены живым фетчем 2026-09-17, дата/время сеансов — нет.

## Fixture

`data/fixtures/msk-vtbarena/`:

| файл | смысл |
|---|---|
| `katanie-na-krytoy-ledovoy-ploshchadke.html` | akademiya-dynamo.ru, полный HTML, снимок 2026-09-17 — цены/правила, без дат |
| `qtickets-event-136634.html` | qtickets.ru/event/136634, полный HTML, снимок 2026-09-17 — подтверждает событие, но 0 совпадений `HH:MM`/месяцев в теле — доказательство, что сетка SPA-only |
| `expected.json` | терминал V1: `sessions: []` |

## Blockers / notes

- Geo-блока нет (RU-сайт отдаётся с текущего egress без BY-подобных 403).
- Реальный блокер — авторизация: Qtickets REST v1 (`shows/{id}`, `events/{id}`) требует API-ключ/Bearer, публично не отдаёт JSON. Без ключа организатора — сетка сеансов недостижима без headless-браузера с реальной пользовательской сессией (не то же самое, что Playwright без сети — тут нужен именно валидный API-ответ, не просто JS-рендер statичной страницы).
- Каденс по тексту сайта — еженедельно по пятницам («расписание… билеты… появляются по пятницам»); полезно для будущего планировщика даже пока извлечение блокировано.
- Длительность сеанса не публикуется нигде на сайте — не хардкодить 45/60 мин без подтверждения из API.
- Прод-адрес арены (Ленинградский пр-т 36) и адрес самой ледовой площадки (ул. Юрия Никулина, 3) — разные строки, оба относятся к одному комплексу «ВТБ Арена Парк»; не путать со сторонней ошибкой источника.
