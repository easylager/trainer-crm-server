# Parser spec: Балтик Арена (СПб, Василеостровский намыв)

- arena_id: 192
- city: Санкт-Петербург
- parser_key: balticarena_html_v1
- cadence: weekly
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

- schedule+prices: https://baltic-arena.ru/mass-skating — single HTML page, Tilda `t431` table widget
- widget/api: none — the visible `<table>` is JS-rendered client-side from two hidden `display:none`
  divs shipped in the raw HTML (`t431__data-part1`, `t431__data-part2`); no separate API call
- job.config JSON (draft):

```json
{
  "url": "https://baltic-arena.ru/mass-skating",
  "run_year": 2026,
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "duration_price_minor": {"60": 70000, "75": 85000},
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET `url`. Two hidden divs carry the real data (confirmed against the live-rendered `<table>`
   via a real browser — see Verification below):
   - `t431__data-part1`: line 1 = weekday names (`Суббота ;Воскресенье;...`), line 2 =
     semicolon-separated `DD.MM` dates, one per column, trailing `;` with no trailing empty token
     (`19.09;20.09;...;27.09;`).
   - `t431__data-part2`: one line per time-slot row, semicolon-separated, columns positionally
     aligned 1:1 with the date row from part1. A day with no session in that row is an empty
     field; if the *trailing* days in a row have no session, the line simply doesn't include
     them (not kept as trailing empty `;;` pairs) — **the column count varies per row**, but
     position 0 is always the first date column, position 1 the second, etc.
2. No year is printed (only `DD.MM`) — `run_year` in job.config, same convention as
   `LedovyyDvoretsHtmlParser`.
3. One observed data typo in the 2026-09-19 snapshot: `22:15:23:15` (colon instead of dash
   before the end time), on the 20.09 column of the 3rd time row. Parser regex accepts either
   `-` or `:` as the start/end time separator.
4. Kind: the whole page is one product, «Массовое катание» → `public_skate`.
5. Price is **not printed per slot** — it's derived from session duration via a small on-page
   legend pairing `60 мин` with `700 руб` and `75 мин` with `850 руб` (verified by comparing
   the legend elements' rendered Y-position in a real browser, since the four numbers/labels
   are visually laid out in a 2×2 grid with no direct text adjacency — do not assume
   reading-order pairing). Both figures live in `job.config["duration_price_minor"]` keyed by
   minutes, not hardcoded, so a price change is a config edit, not a deploy.
6. No child price is published for mass skating — `price_child_minor` stays `null` for every
   slot.
7. No rental price for mass skating either — the 6 000–8 000 ₽ figures elsewhere on the page
   are for private "Час хоккея" ice rental (a different product, `1/3`/`1/2` ice by the hour),
   not skate rental for public sessions. `price_rental_minor` stays `null`.
8. Merge: one slot per `(local_date, starts_at_local)` — no natural external id, this pair is
   the idempotency key (same pattern as most BY weekly-grid adapters). The 2026-09-19 snapshot
   has one real source duplicate under this key — 20.09 22:15-23:15 appears identically in both
   row 3 (as the `22:15:23:15` typo) and row 4 — 26 raw cells collapse to 25 slots after merge;
   this is deliberate dedup, not a parser bug.

## Verification

2026-09-19 snapshot, live-rendered via a real browser (Playwright) against the same URL:
the rendered `<table>` (9 date columns + 1 trailing empty column, 5 body rows) confirmed the
raw hidden-div data's row/column positions map 1:1 to the visible table exactly as described
above, including the trailing-days-omitted behavior on rows 1–4 and the `22:15:23:15` typo on
row 3. The `60 мин`/`700 руб` and `75 мин`/`850 руб` pairing was confirmed by comparing each
legend element's `getBoundingClientRect()` Y coordinate (700 руб and 60 мин share y≈118;
850 руб and 75 мин share y≈160).

## Canonical example (expected after validate)

Snapshot 2026-09-19 — 25 slots total across 19.09–25.09 (26.09/27.09 have none yet). Full set
in `expected.json`. Representative rows:

| local_date | starts_at_local | ends_at_local | price_adult_minor |
|---|---|---|---|
| 2026-09-19 | 09:15 | 10:15 | 70000 |
| 2026-09-19 | 18:30 | 19:45 | 85000 |
| 2026-09-20 | 22:15 | 23:15 | 70000 |
| 2026-09-23 | 14:15 | 15:30 | 85000 |

## Fixture

`data/fixtures/spb-baltic-arena/` — `mass-skating.html` (the two raw hidden-div elements, real
HTML captured 2026-09-19) + `expected.json` (25 sessions after dedup, hand-computed from the
same raw data independently of the parser code).
