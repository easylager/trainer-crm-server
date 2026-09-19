# Parser spec: Айсбург Арена (СПб, Парашютная ул. 11)

- arena_id: 193
- city: Санкт-Петербург
- parser_key: iceburgarena_yclients_v1
- cadence: weekly
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

- schedule+prices: `https://api.yclients.ru/api/v1/activity/1662558/search?from=YYYY-MM-DD&weekly_schedule=1&page=1&count=50`
  — a **genuine public JSON API**, unlike every other RU-pilot adapter which scrapes HTML.
  The site's own `/schedule/` page embeds the yclients `client.booking` widget in an
  iframe, and this is the exact call that widget makes to populate its weekly grid.
- `1662558` is the yclients `company_id` (== `location_id` in some yclients endpoints) —
  found via the widget's other calls (`booking/locations/1662558/...`), not guessed.
- job.config JSON (draft):

```json
{
  "company_id": 1662558,
  "bearer_token": "gtcwf654agufy25gsadh",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

Two things unlike every other RU-pilot adapter here:

- `prices_already_minor: true` — this parser converts `service.price_min` (whole rubles) to
  minor units itself inside `extract()` (see item 4 below), so `IceSessionNormalizer` must
  not convert a second time.
- No static `url` in config. The endpoint's `?from=YYYY-MM-DD` window advances every week —
  a job.config URL with a fixed date would keep re-fetching the same stale week forever.
  `extract()` builds the request URL itself from `company_id` + "today" in Europe/Moscow
  (the venue's own timezone, not server-local) at fetch time, and sends `bearer_token` as
  the `Authorization: Bearer` header. A `job.config["url"]` is still honored as a fallback
  when `fixture_dir` is set (tests), matching the shared `load_source_json` convention.

## How to extract (reverse)

1. GET the URL above. `count=50` with `weekly_schedule=1` returns every bookable "activity"
   (group-session slot) at the venue for the 7-day window starting at `from`, ~45 items in
   the 2026-09-19 snapshot covering 14.09–20.09.
2. Each item has `date` (`"YYYY-MM-DD HH:MM:SS"`, local time, string — not epoch), `length`
   (seconds), `capacity`, and a nested `service` object with `title`, `price_min`,
   `price_max` (whole currency units, e.g. `900` = 900 ₽, **not** minor units — multiply by
   100, unlike the HTML adapters' job.config price constants which are pre-converted).
3. **Filter to `service.title == "Массовое катание"` only.** The endpoint mixes in private
   bookings that must never become public `ice_sessions` rows: "Час фигурного катания"
   (1h/75min variants), "Час хоккея" (+ weekend variant), "Групповая функциональная
   тренировка" — same rule as the BY adapters never turning ОХМ/training-only slots into
   catalog sessions (`test_minsk_adapters.py` AC-003).
4. `price_min == price_max` for every "Массовое катание" item in the snapshot (single flat
   ticket price, no adult/child split) — `price_child_minor` stays `null`. No rental price
   is exposed by this endpoint either (`price_rental_minor` stays `null`).
5. `source_id`: the item's own `id` (yclients activity id) is a real, stable idempotency
   key — used instead of `(local_date, starts_at_local)` since it's available and stronger
   (two activities could theoretically share a start time on different ice sheets).
6. **Not covered by this pass**: `"Ночное катание"` (night skating) appeared twice in the
   snapshot and visually reads as public-facing (advertised alongside massovoe katanie on
   the site's own schedule page, same "100% предоплата" flow, no obvious staff/private
   framing) — but wasn't confirmed either way, so it's excluded rather than guessed into
   `public_skate`. Flagged as a follow-up decision for the owner, not silently dropped.
7. Auth: the widget sends `Authorization: Bearer gtcwf654agufy25gsadh` — verified via a
   plain `curl` with no cookies/session state that this is a fixed, non-company-specific
   app token (the yclients `client.booking` web app's public client token), not a
   per-visitor or per-company secret. No `x-app-client-context` or other session header was
   needed for the plain curl to succeed.

## Canonical example (expected after validate)

Snapshot 2026-09-19 — 7 "Массовое катание" slots across 19.09–20.09 in the fetched window
(14.09–18.09 had none). Full set in `expected.json`. Representative rows:

| local_date | starts_at_local | ends_at_local | price_adult_minor | source_id |
|---|---|---|---|---|
| 2026-09-19 | 16:30 | 17:30 | 90000 | 51801273 |
| 2026-09-19 | 17:45 | 18:45 | 90000 | 51801336 |
| 2026-09-20 | 20:00 | 21:00 | 90000 | 51801528 |

## Fixture

`data/fixtures/spb-iceburg-arena/` — `activity-search.json` (the full raw API response, 45
activities, captured 2026-09-19 via a real browser network trace) + `expected.json` (7
"Массовое катание" sessions, hand-filtered from the same raw data independently of the
parser code).
