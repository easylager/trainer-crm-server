# Parser spec: Ледовая арена «Озерки» (СПб)

- arena_id: 101
- city: Санкт-Петербург
- parser_key: ozerki_gcal_v1
- cadence: daily
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

The facility has multiple rinks (`/raspisanie/` lists Большая арена, Малая арена, a
training/central arena, a gym, and a throwing zone). Two rinks publish a genuine public
"Свободное катание" schedule via an embedded Google Calendar (FullCalendar widget); this
parser covers those two only.

- `https://katok-ozerki.ru/raspisanie/big-arena.html` — Большая арена. The page's own JS
  embeds a **public Google Calendar API key** (`AIzaSyB6QYcTzKpA8kiRcjl47XJ_tEYbY2mcUVg`,
  found directly in page source, not secret) and two calendar ids for the `#calendar2`
  FullCalendar instance: one unlabeled (the site's own hourly-rental booking form marking
  busy/occupied time, no `summary` field) and one — `jgl24dlkvmobfa4eh6ob5qomks@group.calendar.google.com`
  — carrying the real public schedule (`summary: "Свободное катание"`). Static prose on the
  page: `Входной билет - 500 р.`
- `https://katok-ozerki.ru/raspisanie/little-arena.html` — Малая арена. Same API key, div
  id `#calendar`, calendar id `pj4va06gncb1vgv76864hbsh08@group.calendar.google.com`. This
  calendar mixes `summary: "Свободное катание"` **and** `summary: "Час хоккея"` events —
  only the former is a public skate session. Static prose: `Входной билет - 400 р.`
- job.config JSON (draft):

```json
{
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "google_api_key": "AIzaSyB6QYcTzKpA8kiRcjl47XJ_tEYbY2mcUVg",
  "horizon_days": 7,
  "rinks": [
    {
      "code": "big",
      "label": "Большая арена",
      "calendar_id": "jgl24dlkvmobfa4eh6ob5qomks@group.calendar.google.com",
      "price_adult_minor": 50000
    },
    {
      "code": "little",
      "label": "Малая арена",
      "calendar_id": "pj4va06gncb1vgv76864hbsh08@group.calendar.google.com",
      "price_adult_minor": 40000
    }
  ],
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. For each rink, GET `https://www.googleapis.com/calendar/v3/calendars/{url-encoded
   calendar_id}/events?key={api_key}&timeMin=...&timeMax=...&singleEvents=true&orderBy=startTime`.
   `timeMin`/`timeMax` are `today`/`today + horizon_days` at midnight in
   `Europe/Moscow` (the venue's own timezone), matching the page's own prose ("расписание
   сеансов массовых катаний актуально на 1 неделю вперед").
2. Each event has `summary`, `start.dateTime`, `end.dateTime` (already carrying the
   `+03:00` Moscow offset — read the local date/time directly off the string, no
   re-interpretation needed) and a stable `id`.
3. **Filter to `summary.strip() == "Свободное катание"` only.** One observed calendar
   prefixes a stray leading space on some entries (`" Свободное катание"`) — `.strip()`
   handles it. `"Час хоккея"` events on the Малая арена calendar, and the unlabeled
   busy-marker events on both calendars, are never public sessions.
4. Price isn't in the calendar at all — it's a flat, per-rink constant from
   `job.config["rinks"][i]["price_adult_minor"]` (the page's own static prose price). No
   child or rental price is published for either rink.
5. `source_id`: `"{code}:{event.id}"` — the Google Calendar event id is a real, stable
   idempotency key; prefixed with the rink code since two different calendars could in
   principle mint the same raw id.

## Canonical example (expected after validate)

Snapshot 2026-09-19, `timeMin`=2026-09-19, `timeMax`=2026-09-26 — 27 "Свободное катание"
slots across both rinks. Full set in `expected.json`. Representative rows:

| rink | local_date | starts_at_local | ends_at_local | price_adult_minor |
|---|---|---|---|---|
| Большая арена | 2026-09-19 | 09:00 | 10:00 | 50000 |
| Малая арена | 2026-09-19 | 12:30 | 13:30 | 40000 |

## Known limitation

`IceSessionNormalizer` dedupes slots by `(local_date, starts_at_local)` only, not per-rink
— if both rinks ever publish a "Свободное катание" session at the exact same clock time on
the same date, one would silently be dropped in favor of the other (last-write-wins inside
the normalizer's merge loop). Not observed in the 2026-09-19 snapshot (checked: 27 sessions,
27 distinct `(date, time)` keys — zero collisions), but not structurally impossible. Flagged
as a known limitation rather than silently risked; a real collision would need a
normalizer-level fix (out of scope for this adapter).

## Fixture

`data/fixtures/spb-ozerki/` — `big-arena-events.json` + `little-arena-events.json` (raw
Google Calendar API responses, captured 2026-09-19 via plain curl with the public API key)
+ `expected.json` (27 "Свободное катание" sessions, hand-filtered from the same raw data
independently of the parser code).
