# Parser spec: Центр ледовых видов спорта «Парнас» (СПб)

- arena_id: 174
- city: Санкт-Петербург
- parser_key: parnasarena_text_v1
- cadence: weekly
- timezone: Europe/Moscow
- currency: RUB
- requires_by_egress: false

## Sources

- schedule+prices: `https://parnas-arena.ru/massovie-kataniya` — a dedicated subpage.

Two blockers ruled out the more obvious sources:

- The homepage (`https://parnas-arena.ru/`) has its own "Расписание" tab widget
  (Час хоккея / Массовые катания / Аренда льда). Its "Массовые катания" tab is
  **genuinely broken**: `aria-controls="rec850565068"` on the tab button, but no element
  with that id exists anywhere in the DOM (confirmed via `page.evaluate` +
  `getElementById`, re-checked after a 1s wait to rule out lazy-load timing, and via
  `document.querySelectorAll('[id*="850565068"]')` returning empty) — not a hidden/timing
  issue, the content is simply missing from this page. The dedicated `/massovie-kataniya`
  subpage (linked from the same nav) has the real content instead.
- The whole domain sits behind **DDoS-Guard** (a bot-challenge CDN, HTTP header
  `server: ddos-guard`) — a plain `curl`/`aiohttp` GET returns a `200` wrapper containing a
  `403 Forbidden` Tilda error page in the body, not the real page. A real browser
  (Playwright) passes the challenge fine.
- job.config JSON (draft):

```json
{
  "url": "https://parnas-arena.ru/massovie-kataniya",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "run_year": 2026,
  "base_price_adult_minor": 70000,
  "rental_price_flat_minor": 50000,
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. Load the page in a real browser and read `document.body.innerText` (a reader-proxy
   plain-text capture, same convention as `LedovyyDvoretsHtmlParser`/
   `YubileynyAfishaParser` — not raw HTML with CSS selectors, since the DOM here is
   Tilda-generated and the useful content is a flat text block anyway).
2. Under the "Расписание массовых катаний" heading: **one week only** (not a rolling
   horizon like `ShansArenaHtmlParser`) — one line per weekday
   (`<Weekday>[,][ ]<DD> <month месяца>`), immediately followed by a semicolon-separated
   list of `HH:MM-HH:MM` ranges on the next line, padded with decorative trailing dashes
   (`---...`) that the extraction simply ignores (scans for time-range tokens directly
   rather than splitting on `;` first). No year printed — `run_year` in job.config, same
   convention as `BalticArenaHtmlParser`.
3. **Real source quirk**: the weekday-header comma spacing is inconsistent —
   `"Вторник,15 сентября"` and `"Воскресенье,20 сентября"` have no space after the comma,
   while every other day does (`"Среда, 16 сентября"`). The day-header regex uses `,?\s*`
   (zero or more spaces), not `,?\s+` — an earlier draft with `\s+` silently dropped both
   of those two days entirely (8 sessions matched instead of 10) before this was caught.
4. **Real source quirk #2**: the Saturday slot's start time uses a *dot* separator
   (`20.30-22:30`) while every other slot uses a colon (`HH:MM-HH:MM`) — the time regex
   accepts either (`[.:]`) for both the start and end hour:minute separator.
5. That same Saturday slot is inline-priced: `20.30-22:30(900 р.дискотека на льду)`. It's
   still a public "Массовые катания" session per the page's own section heading (a themed
   "ice disco" night, not a different product), so it's kept — but at its own inline
   900 ₽, overriding the flat `base_price_adult_minor` (700 ₽) for that slot only.
   **This inline figure disagrees with the page's separate price-list entry** ("ЛЕДОВАЯ
   ДИСКОТЕКА — 800 руб.") two sections below — the date-specific inline number is trusted
   over the generic price-list one, same precedence rule as `IceburgArenaJsonParser`'s
   docstring on stale summary numbers vs. the live source; flagged here rather than
   silently picking one without comment.
6. Rental is a flat price from the page's own price list ("ПРОКАТ КОНЬКОВ — 500 руб.") —
   `rental_price_flat_minor` in job.config, same convention as `SokolnikiHtmlParser`. Adult
   and child tickets are both 700 ₽ (identical) per the price list — no separate child
   price is tracked (`price_child_minor` stays `null` for every slot; tracking it would add
   no information since it never diverges from adult in the source).
7. No stable per-slot id is exposed — `source_id` stays unset; the normalizer's
   `(local_date, starts_at_local)` dedup key is sufficient (no two slots on the same day
   start at the same time in the snapshot).

## Canonical example (expected after validate)

Snapshot 2026-09-19 — page showed the week of 14.09–20.09, 10 slots. Full set in
`expected.json`. Representative rows:

| local_date | starts_at_local | ends_at_local | price_adult_minor |
|---|---|---|---|
| 2026-09-16 | 13:00 | 15:00 | 70000 |
| 2026-09-19 | 20:30 | 22:30 | 90000 |

## Fixture

`data/fixtures/spb-parnas-arena/` — `schedule.md` (a reader-proxy plain-text capture of
the schedule + price section, captured 2026-09-19 via a real browser) + `expected.json`
(10 sessions, hand-extracted from the same text independently of the parser code).
