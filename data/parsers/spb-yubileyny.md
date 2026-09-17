# Parser spec: СК «Юбилейный» (СПб, пр. Добролюбова 18)

- arena_id: 97
- city: Санкт-Петербург
- parser_key: yubileyny_afisha_html_v1
- cadence: event-driven (не daily/weekly сетка — кассовая афиша публикует единичные события по мере готовности)
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

- schedule (список событий): https://www.yubi.ru/afisha/katok/ ← карточки «Часовая спортивная докатка» со ссылками `?event=<id>`
- schedule (цена/зал/дата на конкретное событие): https://www.yubi.ru/afisha/katok/chasovaya_sportivnaya_dokatka.../?event=<id> ← **primary** для цены, не сводная `/price/`
- prices (сводная, **расходится** с ценой события — см. блокер): https://www.yubi.ru/afisha/katok/price/
- widget/api: нет отдельного JSON API, вся SoT — server-rendered HTML собственного CMS (bquadro.ru), не Bitrix
- job.config JSON (черновик):

```json
{
  "listing_url": "https://www.yubi.ru/afisha/katok/",
  "event_url_pattern": "https://www.yubi.ru/afisha/katok/{slug}/?event={id}",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "default_duration_minutes": 60,
  "price_source": "per_event_page",
  "price_source_not": "https://www.yubi.ru/afisha/katok/price/",
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET `listing_url`. Каждая карточка «Часовая спортивная докатка» даёт `event_id` (query `?event=`) и краткую дату/время — но **не** цену и **не** зал (арену).
2. Для каждого `event_id` GET event-страницу. Там: `Дата:19 сентября 2026`, `Время:18:45`, `Арена:Малая`, `Цена:800 р.`, `Ограничение по возрасту посещения 0+`. Это единственное надёжное место с ценой на конкретный сеанс — цены **разные по событиям в общем случае** (здесь на снимке все три совпали на 800, но поле per-event, не константа).
3. Duration: `Стоимость одного сеанса составляет 800 руб.\ 1 час` → `default_duration_minutes=60`, `ends_at_local = starts_at_local + 60`.
4. Kind: вся страница `/afisha/katok/` — один продукт «докатка для всех» → `public_skate`. Текст «Спортивная докатка» на этом сайте — синоним массового катания для непрофессионалов, не путать с закрытыми тренировками фигуристов/хоккеистов (те через `/afisha/sport/`, drop).
5. Age: 0+ на каждой проверенной странице — единый билет, без детского тарифа. `price_child_minor = null`.
6. Rental: «Прокат коньков не предусмотрен» на всех event-страницах → `price_rental_minor = null`.
7. Merge: один event = один слот, `event_id` — естественный ключ идемпотентности (крепче чем `(local_date, starts_at_local)`, т.к. может быть несколько залов в одно время — здесь все три на снимке «Малая», но поле `Арена` заложить в `session_label`).
8. **Расхождение цен, не унифицировать молча**: `/afisha/katok/price/` называет «Спортивная докатка (сеанс 1 час) — 600 руб.», подвал `/afisha/katok/` пишет «Стоимость одного сеанса составляет 700 руб.», а конкретные event-страницы дают **800 руб.** Канон = цена с event-страницы (шаг 2), т.к. она привязана к конкретному проверяемому сеансу; две другие цифры — вероятно устаревшие/базовые тексты шаблона. Не усреднять и не выбирать «типичную» — брать событие.

## Canonical example (expected after validate)

Снимок 2026-09-17, три текущих события на `/afisha/katok/`:

| local_date | starts_at_local | ends_at_local | kind | session_label | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|---|
| 2026-09-19 | 18:45 | 19:45 | public_skate | Малая арена | 80000 | null | null |
| 2026-09-20 | 10:15 | 11:15 | public_skate | Малая арена | 80000 | null | null |
| 2026-09-20 | 18:15 | 19:15 | public_skate | Малая арена | 80000 | null | null |

Полный набор — 3 слота в `expected.json` (это весь текущий репертуар кассы на момент снимка, не усечение).

## Fixture

`data/fixtures/spb-yubileyny/` — `katok-listing.md`, `price.md`, `event-11207.md`, `event-11208.md`, `event-11206.md` (все — reader-proxy markdown-снимки, см. блокер сети) + `expected.json`.

## Blockers / notes

- **Сеть**: прямой доступ к `www.yubi.ru` из этой sandbox зависает так же, как `newarena.spb.ru` (см. `spb-ledovyy-dvorets.md`) — обойдено через `r.jina.ai` reader-proxy. Фикстуры — markdown-извлечения, не raw HTML DOM; продовый парсер должен целиться в реальную разметку с иного egress, структура (event-страница = поля Дата/Время/Арена/Цена/возрастное ограничение) должна сохраниться, но точные CSS/DOM-селекторы не подтверждены.
- Каденс: это НЕ регулярная еженедельная сетка как в BY-спеках — касса публикует события штучно (сейчас всего 3 на 2 дня вперёд). Джоб должен перечитывать `listing_url` часто (daily) и подтягивать новые `event_id`, а не полагаться на устойчивый недельный шаблон.
- Официальный сайт explicitly предупреждает о поддельных «афишах Юбилейного» («участились случаи распространения ложной информации... поддельные сайты») — сверять домен `www.yubi.ru`, не брать зеркала.
- Аггрегатор `vse-katki.ru`: у него ЕСТЬ карточка «Юбилейный» (`/rink/yubi`, `code=yubi`, `rinkId=3`) с собственным JSON API `GET /api/rink/yubi`, но полезная нагрузка отдаётся зашифрованной (поле `image` — на деле AES-256-CBC/PBKDF2-HMAC-SHA512(999 iter) JSON, ключи `key`/`key2`(=iv, hex16)/`key3`(=salt, hex256); пароль PBKDF2 — статическая подстрока из хардкод-строки `his`, которую компонент `rink-scheduler` передаёт как `getIs()` = `"aDadWdFjQAVSgpUdeBmFPBzBA3sDz^KzZzAF*%))zAaDM%vLAF"`, `password = his.slice(6, len(his)-28)`). Расшифровка **успешна** (проверено), но payload заморожен на **2025-08-11…2025-08-17** (>13 месяцев устарел на снимке 2026-09-17) и **не содержит поля цены вообще** (`date/from/to/rinkId/description/icon`). Не использовать как источник — задокументировано только чтобы не повторять reverse дважды, если понадобится для другой арены на той же площадке (из СПб-пилота там были только id=3 «Юбилейный»; остальные 4 целевые арены на `vse-katki.ru` не найдены вовсе).
