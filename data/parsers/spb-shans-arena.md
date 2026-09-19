# Parser spec: Ледовый комплекс «Шанс Арена» (СПб)

- arena_id: 100
- city: Санкт-Петербург
- parser_key: shansarena_html_v1
- cadence: daily
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

- schedule: `https://shans-arena.ru/` (homepage) — static server-rendered HTML, no JS
  widget. A `cdn-public.torrow.net/widget/torrow-widget.min.js` script is also embedded on
  the page but never fires any network call — a dead include, not the real data source.
- prices: `https://shans-arena.ru/services/ledovaya-arena/massovoe-katanie/` — separate
  static price page.
- job.config JSON (draft):

```json
{
  "url": "https://shans-arena.ru/",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "price_adult_minor": 90000,
  "price_child_minor": 90000,
  "price_rental_minor": 60000,
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET the homepage. It publishes a **14-day rolling schedule**: one `<h3>Weekday<br>
   DD.MM.YYYY</h3>` per day (full year printed, unlike most RU-pilot sources), each
   followed by a `<div class="dayinclude">` holding one `<div class="schitem TYPE">` block
   per session.
2. `TYPE` is a genuine CSS class — `mass` (Свободное массовое катание), `hockey` (Час
   хоккея), `figure` (Час фигурного катания). **Filter to `TYPE == "mass"` only** — same
   "public skate only" rule as every other RU-pilot adapter (see
   `IceburgArenaJsonParser`).
3. Each `schitem` has a `schitemtime` div with two `<p>` tags (start, end). **Real source
   quirk**: the first published week prints a literal dash between the two `<p>` tags
   (`<p>09:15</p> - <p>10:15</p>`); the *second* week omits the dash and the
   `schitemtime`'s trailing class-name space (`<p>09:15</p><p>10:15</p>`) — a template
   inconsistency between weeks, not a typo in one row. The extraction regex uses two
   independent non-greedy gaps between `<p>` tags rather than requiring a literal dash, so
   both weeks parse identically. **Caught by counting**: a raw `grep -c 'class="schitem
   mass"'` on the page found 31 occurrences while a dash-requiring first-draft regex only
   matched 15 — the under-count would have silently dropped the entire second week without
   that check.
4. Price is not printed inline on the schedule page at all — flat
   `price_adult_minor`/`price_child_minor` (900 ₽ each, genuinely identical — confirmed on
   the separate price page, both "Массовое катание для взрослых" and "...для детей" list
   900 руб.) and `price_rental_minor` (600 ₽, "Прокат коньков") come from job.config.
5. No stable per-slot id is exposed — `source_id` stays unset; the normalizer's
   `(local_date, starts_at_local)` dedup key is sufficient (no two `mass` slots on the same
   day start at the same time in the snapshot).

## Canonical example (expected after validate)

Snapshot 2026-09-19 — 23 "mass" slots from 2026-09-19 through 2026-09-27 (the schedule's
first 5 days, 14.09–18.09, were already in the past relative to the snapshot and are
excluded from `expected.json`). Full set in `expected.json`. Representative rows:

| local_date | starts_at_local | ends_at_local | price_adult_minor |
|---|---|---|---|
| 2026-09-19 | 13:45 | 14:45 | 90000 |
| 2026-09-21 | 09:15 | 10:15 | 90000 |

## Fixture

`data/fixtures/spb-shans-arena/` — `index.html` (the full raw homepage, captured
2026-09-19 via plain curl) + `expected.json` (23 "mass" sessions, hand-extracted from the
same raw HTML independently of the parser code).
