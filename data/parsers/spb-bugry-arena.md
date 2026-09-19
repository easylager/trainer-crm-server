# Parser spec: Ледовая арена «Бугры» (СПб)

- arena_id: 111
- city: Санкт-Петербург
- parser_key: bugryarena_html_v1
- cadence: weekly
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

- schedule+prices: `https://spb-katok.ru/` — static HTML `<table>`, no JS widget at all.
  Confirmed via plain `curl`.
- job.config JSON (draft):

```json
{
  "url": "https://spb-katok.ru/",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "run_year": 2026,
  "default_duration_minutes": 45,
  "rinks": {
    "big": {"label": "Большая арена", "price_adult_minor": 60000, "price_rental_minor": 50000},
    "small": {"label": "Малая арена", "price_adult_minor": 60000, "price_rental_minor": 40000}
  },
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET the URL above. One `<table>` with columns `Дата | Большая | Малая`, one `<tr>` per
   date (`XX (DD.MM)` — two-letter weekday abbreviation, no year, `run_year` in
   job.config). Each of the two rink columns holds a semicolon-separated list of times, or
   is empty for that date.
2. **Times are `HH-MM` — a dash, not a colon** (a real source quirk, unlike every other
   RU-pilot adapter's `HH:MM`).
3. **No end time and no session duration is printed anywhere on the page** — every slot
   relies entirely on `IceSessionNormalizer`'s own `default_duration_minutes` fallback
   (`ExtractedSlot.ends_at_local` is left `None` here, never a guessed literal end time).
   45 minutes in job.config is a typical St. Petersburg public-skate session length, **not
   confirmed against this specific source** (no prose on the page states it) — flagged as
   an assumption, not asserted as fact; an operator with local knowledge of this arena
   should confirm or correct it.
4. **Both rink columns are parsed structurally**, not hardcoded to "Большая only" — in the
   2026-09-19 snapshot, every row's "Малая" cell is empty (zero published sessions), but if
   the operator ever starts publishing Малая massovoe-kataniye times, this adapter picks
   them up without a code change. Price is a flat per-rink constant from
   `job.config["rinks"][code]` (same convention as `OzerkiCalendarParser`) — both rinks
   currently read 600 ₽ for the ticket, but rental already differs (500 ₽ Большая vs.
   400 ₽ Малая on the page's own price table), so the two rinks are kept independently
   configurable rather than collapsed into one shared constant.
5. No stable per-slot id is exposed, and no child price is published — `source_id` and
   `price_child_minor` stay unset/`null`. The normalizer's `(local_date, starts_at_local)`
   dedup key is sufficient (no two slots on the same day start at the same time in the
   snapshot, and Малая is empty so there's no big/small collision risk either, unlike the
   documented risk in `spb-ozerki.md`).

## Canonical example (expected after validate)

Snapshot 2026-09-19 — page showed the week of 14.09–20.09, 47 slots, all on "Большая
арена" (Малая empty every day). Full set in `expected.json`. Representative rows:

| rink | local_date | starts_at_local | ends_at_local (45 min default) | price_adult_minor |
|---|---|---|---|---|
| Большая арена | 2026-09-14 | 09:00 | 09:45 | 60000 |
| Большая арена | 2026-09-19 | 14:15 | 15:00 | 60000 |

## Fixture

`data/fixtures/spb-bugry-arena/` — `index.html` (the full raw page, captured 2026-09-19
via plain curl) + `expected.json` (47 sessions, hand-extracted from the same raw HTML
independently of the parser code — end times computed by adding the 45-minute assumed
default to each printed start time).
