# Parser spec: Ледовая арена «Купчино»

- arena_id: 110
- parser_key: `kupchinoarena_html_v1`
- cadence: daily
- requires_by_egress: false

## Sources
- schedule + prices: https://arenakupchino.ru/massskating
- widget/api: none — plain static Tilda page, no JS-rendered widget, no bot-block observed (plain `curl` with a browser User-Agent returns 200, 442KB real HTML)
- job.config JSON (черновик):

```json
{
  "url": "https://arenakupchino.ru/massskating",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "prices_already_minor": true
}
```

## How to extract (reverse)
1. Fetch `/massskating`. It's a Tilda export: dozens of `<h2 label/><h3 value/>` pairs sharing the same generic shape (feature blurbs, rules list, contacts) — do NOT match `<h2>...</h2>.*?<h3>...</h3>` positionally/globally, it will pick up unrelated blocks. Anchor on the literal label text instead.
2. Kind filter: none needed — the page publishes exactly one product ("массовое катание"); everything found under the "Время сеанса:" label is in scope. No hockey-hour/figure-skating section exists on this page to exclude.
3. Times: find the `<h2 ...>Время<br>сеанса:</h2>` block, then the very next `<h3>` sibling. Its text is one or more `DD.MM.YY <с|c> HH:MM до HH:MM` lines joined by `<br />`. Two-digit year (`26` → 2026, assume `2000 + YY`). **Quirk**: the preposition before the start time is inconsistent — the first line uses Cyrillic "с" (U+0441), the second uses Latin "c" (U+0063), a copy-paste typo in the operator's own hand-edited text (confirmed byte-for-byte in the fixture). Accept either.
4. Prices: two more label→value pairs, same page, found the same way — `<h2>Стоимость<br>входного билета</h2>` → next `<h3>` (adult ticket, `500 ₽` at capture time) and `<h2>Стоимость<br>проката коньков</h2>` → next `<h3>` (skate rental, also `500 ₽`). Both flat, applied to every extracted slot. No child price is published anywhere on the page. The adapter converts these to minor units itself via `parse_price_to_minor(..., already_minor=False)` at extract time (same convention as `SokolnikiHtmlParser`) — job.config must set `"prices_already_minor": true` or `IceSessionNormalizer` will double-multiply by 100.
5. Merge: not applicable — each `HH:MM до HH:MM` line is already one full slot (both start and end are always printed), so there's nothing to merge across rows.

## Canonical example (expected after validate)
| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-26 | 15:15 | 16:15 | public_skate | 50000 | null | 50000 |
| 2026-09-26 | 19:45 | 20:45 | public_skate | 50000 | null | 50000 |

## Fixture
`data/fixtures/spb-kupchino-arena/` — `massskating.html` (raw fetch, 2026-09-22, plain `curl` with a browser User-Agent, HTTP 200) + `expected.json` канона.

## Blockers / notes
- This is **not** a weekly grid like most other SPb adapters — it's a single hand-maintained text block the operator updates with just the next upcoming session(s). The 2026-09-22 snapshot has exactly two sessions, both on the same date (26.09.26). An empty/missing block is a legitimate "nothing scheduled yet" state (same convention as `SokolnikiHtmlParser`'s empty `.schedule-list`), not a parse failure — the adapter yields zero slots rather than erroring.
- `cadence: daily` chosen specifically because of the above: since the operator republishes only the immediate next session(s) rather than a rolling multi-week horizon, a less-frequent cadence risks missing sessions entirely if they're added and skated before the next scrape.
- Backup candidates (ТРК «Континент», ТРК «РИО») were not investigated — primary candidate was feasible on the first pass, per the workflow's stop-once-feasible rule.
- 2ГИС / Zoon / peterburg2.ru listings and a third-party `arenakupchino.ledokat.ru` booking-widget mirror quote a *different* Sat/Sun schedule (15:30–16:45 Sat, 13:45–15:00 Sun) than what's actually printed on the operator's own site at capture time (15:15–16:15 and 19:45–20:45, both same date) — the site's own page is trusted as source of truth, per this project's general precedence rule (see `ParnasArenaTextParser`'s docstring in `adapters_ru_pilot.py` for the same "inline/primary source over secondary listing" rule), the third-party listings are stale/generic, not re-scraped.
