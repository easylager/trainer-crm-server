# Parser spec: СК «Гололёд» — ледовая арена (Красное Село)

- arena_id: 178
- arena_slug: ledovaya-arena-gololed
- city: Санкт-Петербург/ЛО
- parser_key: gololed_html_v1
- cadence: daily
- requires_by_egress: false

## Sources
- schedule: https://gololed.spb.ru/ (виджет `#schedule_for_all_component`, 8 дней вперёд, все виды сеансов)
- prices: https://gololed.spb.ru/ledovaya-arena/massovye-kataniya («650 руб/сеанс 1 час», «800 руб/сеанс 1 час 15 минут»), https://gololed.spb.ru/ledovaya-arena/chas-hokkeya («Стоимость 650 руб/сеанс»)
- widget/api: none — server-rendered HTML, session cells carry `data-*` attributes
- job.config JSON:

```json
{ "url": "https://gololed.spb.ru/", "public_skate_url": "https://gololed.spb.ru/ledovaya-arena/massovye-kataniya", "hockey_url": "https://gololed.spb.ru/ledovaya-arena/chas-hokkeya", "timezone": "Europe/Moscow", "currency_code": "RUB", "default_duration_minutes": 60, "requires_by_egress": false }
```

## How to extract
1. Fetch the home page. No `id="schedule_for_all_component"` → raise (layout change, not an empty day).
2. Each `div.schedule_td` cell: `data-activity_slug`, `data-start_ts` (unix seconds), `data-start_date` («09 ноября 10:15»), `data-end_date` («11:15»), `data-session_id`, `data-title`, `data-service_url`.
3. Date and start come from `data-start_ts` in Europe/Moscow; the HH:MM in `data-start_date` must match it, otherwise the cell is dropped.
4. Kinds: `massovoe_katanie` → `public_skate`, `chas_hokkeya` → `hockey_practice`, `chas_figurnogo*` → `figure_free`. Any other slug is skipped.
5. Prices (adult only, one ticket price, no child tariff published): public skating by session length (60 → 650, 75 → 800 RUB), hockey hour flat 650 RUB. Price pages are optional — failed fetch → `null` prices, slots still published.
6. Dedup by `data-session_id`; past sessions are dropped by the normalizer.

## Canonical example (expected after validate, now = 2026-11-09 09:00 MSK)
| local_date | starts_at_local | ends_at_local | kind | adult_minor |
|---|---|---|---|---|
| 2026-11-09 | 09:00 | 10:00 | hockey_practice | 65000 |
| 2026-11-09 | 10:15 | 11:15 | public_skate | 65000 |
| 2026-11-09 | 11:15 | 12:15 | public_skate | 65000 |

## Fixture
`data/fixtures/spb-gololed/` — live `curl` snapshots 2026-11-09 of `index.html`, `massovye-kataniya.html`, `chas-hokkeya.html`; `expected.json` = 46 sessions (37 public_skate, 9 hockey_practice) computed with now = 2026-11-09T06:00Z.

## Notes
- Rental (прокат) price is not printed on the schedule/service pages — `price_rental` stays null.
- Раздевалка включена в стоимость билета (massovye-kataniya page).
