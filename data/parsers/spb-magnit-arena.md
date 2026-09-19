# Parser spec: Ледовая арена «Магнит» (СПб, Магнитогорская ул. 51В)

- arena_id: 187
- city: Санкт-Петербург
- parser_key: magnitarena_html_v1
- cadence: weekly
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

- schedule+prices: `http://magnit-arena.ru/` — static Tilda page. The visible accordion
  content sits behind a plain `hidden` attribute (CSS-only hide), not a JS fetch — the data
  is present in the raw server-rendered HTML, confirmed via plain `curl`.
- job.config JSON (draft):

```json
{
  "url": "http://magnit-arena.ru/",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "run_year": 2026,
  "base_price_adult_minor": 60000,
  "rental_price_flat_minor": 30000,
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET the URL above. The page publishes **two** rink schedules as `t120`/`t1118` Tilda
   blocks: "Ледовая Арена 1" and "Ледовая Арена 2".
2. **Only "Ледовая Арена 1" is public "массовое катание"** — its per-day description text
   leads with `Массовое катание - 600 р. за сеанс`. **"Ледовая Арена 2" is "Час хоккея"**
   (hockey-hour) — a different product, confirmed by its own per-day text
   (`Час хоккея - 600 р. за сеанс`) — never scraped, same "public skate only" rule as every
   other RU-pilot adapter (see `IceburgArenaJsonParser`). Locate Arena 1's HTML chunk by
   slicing between the two `"Ледовая Арена 1"`/`"Ледовая Арена 2"` title markers.
3. Within that chunk, each day is one `t1118__accordion` block: a title span
   (`DD.MM / <weekday>`, no year — `run_year` in job.config) and a `li_descr__<id>` content
   div holding a mix of prose (base price, rental price, trainer-lesson upsell) followed by
   a flat, unstructured `<ul><li>` list of time ranges. The Tilda rich-text editor splits
   some digits across multiple `<a>`/`<span>` tags (an observed source quirk, e.g.
   `11:</a><a>0</a><span>0</span>` for `11:00`) — **strip all HTML tags first**, then
   `html.unescape`, then regex the flattened plain text; the fragments rejoin cleanly once
   tags are gone.
4. Most listed times (plain, e.g. `12:45 - 13:45`) carry the flat
   `base_price_adult_minor` (600 ₽ at capture time). A subset are individually suffixed
   inline with `/ NNN р.*` (e.g. `09:45 - 11:00 / 150 р.*` — an off-peak promo, 150 ₽ at
   capture time) — when present, that marked price overrides the flat base for that one
   slot.
5. Rental is a flat per-session price printed as prose on every day block
   (`Прокат - 300 р.`) — read from `job.config["rental_price_flat_minor"]`, not re-parsed
   per day, same convention as `SokolnikiHtmlParser`. No child price is published.
6. No stable per-slot id is exposed — `source_id` stays unset; the normalizer's
   `(local_date, starts_at_local)` dedup key is sufficient (no two Arena-1 slots on the same
   day start at the same time in the snapshot).

## Canonical example (expected after validate)

Snapshot 2026-09-19 — page showed the week of 14.09–20.09 (Arena 1 only), 62 slots across 7
days. Full set in `expected.json`. Representative rows:

| local_date | starts_at_local | ends_at_local | price_adult_minor | price_rental_minor |
|---|---|---|---|---|
| 2026-09-14 | 06:45 | 08:00 | 60000 | 30000 |
| 2026-09-14 | 09:45 | 11:00 | 15000 | 30000 |
| 2026-09-20 | 21:00 | 22:30 | 60000 | 30000 |

## Fixture

`data/fixtures/spb-magnit-arena/` — `index.html` (the full raw page, captured 2026-09-19
via plain curl) + `expected.json` (62 "Ледовая Арена 1" sessions, hand-extracted from the
same raw HTML independently of the parser code — flatten tags, then regex, done by a
one-off script, not by importing `MagnitArenaHtmlParser`).
