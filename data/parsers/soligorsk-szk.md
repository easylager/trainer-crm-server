# Parser spec: СЗК Солигорск

- arena_id: 19
- arena_slug: soligorsk-szk
- city: Солигорск
- parser_key: soligorsk_szk_html_v1
- cadence: weekly
- requires_by_egress: false

Адрес в проде: ул. К. Заслонова, 25. Официальный сайт http://www.szk.by/ (http).

## Sources

- schedule+prices: http://www.szk.by/uslugi/massovoe-katanie
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "url": "http://www.szk.by/uslugi/massovoe-katanie",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "default_duration_minutes": 45,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET HTML. Блок «РАСПИСАНИЕ МАССОВЫХ КАТАНИЙ:» — строки `N сентября - HH.MM-HH.MM` (несколько через `;`). Год не напечатан: год прогона; около 1 января проверять декабрь vs январь.
2. Kind: вся эта афиша = `public_skate`. Ночное «Рок-хиты» 23.00-00.00 — тот же kind, `session_label=Рок-хиты` (как дискотека на МК). Drop правила посещения, зрительский билет, заточка, абонементы, семейный сеанс (combo).
3. Times: `21.00-21.45` → `21:00`/`21:45`. Переход суток: `23:00-00:00` → `ends_at` следующий календарный день, `local_date` = дата старта.
4. Prices в том же HTML:

| | minor |
|---|---|
| взрослый | 6,60 → 660 |
| детский до 16 (и пенсионный той же строкой) | 5,00 → 500 |
| прокат 1 пара | 4,40 → 440 |

Студенческий 5р — скидка по удостоверению, **не** `price_child`. Не хардкодить, если абзац изменится.
5. Merge: один слот на `(local_date, starts_at_local)`.
6. `age_note`: «детский до 16 лет».

## Canonical example (expected after validate)

Снимок 2026-09-05, 31 авг – 6 сен, 11 слотов:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor | label |
|---|---|---|---|---|---|---|---|
| 2026-09-04 | 21:00 | 21:45 | public_skate | 660 | 500 | 440 | |
| 2026-09-05 | 23:00 | 00:00 | public_skate | 660 | 500 | 440 | Рок-хиты |
| 2026-09-06 | 13:00 | 13:45 | public_skate | 660 | 500 | 440 | |

## Fixture

`.ai/data/fixtures/soligorsk-szk/` — `massovoe-katanie.html` + `expected.json`.

## Blockers / notes

- Geo-блока нет. Сайт на http. Каденс weekly («в расписании возможны изменения»).
- Не брать июльский репринт esoligorsk.by как SoT.
- 2026-10-06: вёрстка сменилась — все дни недели в одном `<h3>` через `<br>`, несколько сеансов дня через запятую (`10 октября - 16.00-16.45 , 21.00-21.45`). Адаптер разбирает по строкам и делит сеансы по `;`/`,`. Снимок: `massovoe-katanie-2026-10-06.html` (тест `test_soligorsk_szk_multi_day_single_h3_layout_2026_10_06`).
