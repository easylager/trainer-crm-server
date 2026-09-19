# Parser spec: ЛД «Гранд Каньон Айс» (СПб)

- arena_id: 99
- city: Санкт-Петербург
- parser_key: grandice_json_v1
- cadence: daily
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

- schedule+prices: `GET https://cp.grand-ice.ru/api/schedules` — a **genuine public JSON
  API, no auth**. Confirmed with a plain `curl -H "User-Agent: Mozilla/5.0"`, no
  cookies/session state.
- job.config JSON (draft):

```json
{
  "url": "https://cp.grand-ice.ru/api/schedules",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

No query params needed or accepted — the endpoint just returns whatever the admin has
currently published (a rolling window; the 2026-09-19 snapshot mixed already-past August
dates with future dates through 2026-09-27). No per-run URL construction needed, unlike
`IceburgArenaJsonParser` — `IceSessionNormalizer`'s own `ends_at_utc <= now` filter drops
the past ones automatically.

## How to extract (reverse)

1. GET the URL above. Returns `{"data": {"schedules": [...]}}`, one entry per published
   date (58 entries in the 2026-09-19 snapshot).
2. Each entry has `schedule_type.name` — one of `"Свободное катание"` (public/free skate,
   what we want), `"Секция"` (training section — no price, `schedule_time[].notes` reads
   `"Свободного катания нет"`), or `"Мероприятие"` (private event — same "no free skate"
   shape). **Filter to `schedule_type.name == "Свободное катание"` only** — same rule as
   every other RU-pilot adapter never turning a non-public activity into a catalog session.
3. `price` is a single flat decimal string for the whole date (e.g. `"750.00"`, whole
   rubles — not minor units, multiply by 100) applied to *every* nested `schedule_time` row
   for that date. There is no per-slot price and no child/rental price anywhere in the
   response.
4. Each `schedule_time` row gives `time_start`/`time_end` as `"HH:MM:SS"` strings (take the
   first 5 chars). No stable per-slot id is exposed — `source_id` stays unset, same as
   `BalticArenaHtmlParser`; the normalizer's `(local_date, starts_at_local)` dedup key is
   sufficient since a single date's times never repeat.

## Canonical example (expected after validate)

Snapshot 2026-09-19 — 39 "Свободное катание" slots across 9 future dates (2026-09-19
through 2026-09-27; 08-01..09-18 already in the past relative to the snapshot and expected
to be dropped by `IceSessionNormalizer`, so excluded from `expected.json`). Full set in
`expected.json`. Representative rows:

| local_date | starts_at_local | ends_at_local | price_adult_minor |
|---|---|---|---|
| 2026-09-19 | 15:45 | 16:45 | 75000 |
| 2026-09-20 | 10:00 | 11:00 | 75000 |
| 2026-09-21 | 12:00 | 13:00 | 65000 |

## Fixture

`data/fixtures/spb-grand-canyon-ice/` — `schedules.json` (the full raw API response, 58
entries, captured 2026-09-19 via plain curl) + `expected.json` (39 "Свободное катание"
sessions from 2026-09-19 onward, hand-filtered from the same raw data independently of the
parser code).
