# Parser spec: Шуваловский лёд

- arena_id: 196
- parser_key: shuvalovskyled_html_v1
- cadence: daily
- requires_by_egress: false

## Sources
- schedule: https://shuvalov-ice.ru/shedule/
- prices: https://shuvalov-ice.ru/services/massovoye-kataniye/ (session price matrix) + https://shuvalov-ice.ru/services/prokat-konkov/ (skate rental)
- widget/api: none — plain static WordPress page, no JS-rendered widget, no bot-block observed
- job.config JSON (черновик):

```json
{
  "url": "https://shuvalov-ice.ru/shedule/",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "prices_already_minor": true,
  "run_year": 2026,
  "price_60min_weekday_minor": 70000,
  "price_60min_weekend_minor": 80000,
  "price_75min_weekday_minor": 87500,
  "price_75min_weekend_minor": 100000,
  "price_rental_minor": 60000
}
```

## How to extract (reverse)
1. Fetch `/shedule/`. It's a server-rendered current-week grid: a `.shedule__table` desktop table followed lower on the page by an identical `.shedule__table.shedule__table--mobile` carousel duplicating the exact same 7 days for small screens — only the first (desktop) table should be parsed, or every slot is double-counted.
2. Dates: 7 `.shedule__date` cells in the table header, each `DD месяц` (no year printed anywhere — `run_year` in job.config supplies it). No next/previous-week link exists on the page at all — this is a rolling display of "the current week" only, hence `cadence: daily` rather than weekly, to avoid missing sessions between scrapes.
3. Kind filter: the page lists five row types — "Час фигурного катания", "Массовое катание" (×2, one per rink), "Час хоккея" (×2). Only the two "Массовое катание" rows are in scope; the other three are drop.
4. Rink filter: not a filter — both "Массовое катание" rows are kept. One covers "Большой лед" (60×28 m), the other "Малый лед" (30×21 m); the parenthetical text after the row label names which. Tag each extracted slot's `session_label` with the rink name so the two aren't silently merged if they ever share an identical start time on the same date (not observed in the 2026-09-22 capture).
5. Times: each of the 7 `.shedule__time` cells per row holds zero or more `HH:MM – HH:MM` pairs joined by `<br>` (an empty cell is a legitimate "no session that day" state, not an error). **Quirk**: some end times have an unexplained character glued directly on — a plain `*` or `**` (26 occurrences across the page, no legend found anywhere), and once a stray Cyrillic "Ю" (`14:00 – 15:00Ю`, a one-off typo, not seen elsewhere). None of these are interpreted; the time-pair regex only requires the digit groups, so anything appended right after is silently ignored.
6. Prices: **not printed on the schedule page itself.** The separate `/services/massovoye-kataniye/` page publishes a flat *matrix*, not a per-session figure — one price for a 60-minute session, a higher one for 75 minutes, each further split into "Будние дни" (weekday) vs "Выходные и праздники" (weekend), with a single combined rate for "взрослые и дети" (no separate child price). Every session on the schedule grid is exactly 60 or 75 minutes (verified across all 32 sessions in the 2026-09-22 fixture), so the adapter computes each slot's duration from its own start/end times, checks the local date's weekday, and looks up the matching tier from job.config — rather than leaving price unset. A duration that matches neither tier falls through with `price_adult`/`price_child` left `None` (not observed so far). "Праздники" (public holidays) are not modeled; only the calendar day-of-week decides weekday vs weekend.
7. Rental: flat 600 ₽/hour from `/services/prokat-konkov/`, no weekday/duration split — applied to every slot via `price_rental_minor`.
8. Merge: not applicable — each `HH:MM – HH:MM` entry is already a complete slot (both start and end always printed).

## Canonical example (expected after validate)
| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-22 | 19:00 | 20:15 | public_skate | 87500 | 87500 | 60000 |
| 2026-09-26 | 19:00 | 20:00 | public_skate | 80000 | 80000 | 60000 |
| 2026-09-27 | 14:00 | 15:00 | public_skate | 80000 | 80000 | 60000 |

## Fixture
`data/fixtures/spb-shuvalovsky-led/` — `shedule.html` (raw fetch of the current week's page, 2026-09-22, HTTP 200, via the `r.jina.ai` reader-proxy with `X-Return-Format: html` — direct TLS to shuvalov-ice.ru timed out from the research sandbox, see Blockers) + `expected.json` канона (32 sessions).

## Blockers / notes
- **Feasibility gate note**: primary candidate (arena_id=196) was feasible on the first pass. It shares its street address with arena_id=182 "Ленинградский кёрлинг-клуб" — same physical complex — but shuvalov-ice.ru is unambiguously the public ice-skating side (a dedicated "Массовое катание" product distinct from "Игра в кёрлинг" in the site's own nav), so backup candidates (191 Невский район, 181 Динамо-Юниор) were not needed.
- **Sandbox egress**: both plain `curl` and the WebFetch tool timed out / failed against `shuvalov-ice.ru` directly from this research sandbox (TLS handshake never completed — not a clean HTTP error, not a bot-challenge body). Same documented phenomenon as `LedovyyDvoretsHtmlParser`'s docstring in `adapters_ru_pilot.py`. The `r.jina.ai` reader-proxy (third path) succeeded and returned real static WordPress markup — confirmed by literal `<meta>`/LiteSpeed-cache asset tags and the schedule's dates matching the real capture-date week, not a bot-challenge or empty SPA shell. A production worker with normal egress should reach the origin directly.
- The 32-session count and the 60/75-minute duration split were verified by direct inspection of the fixture, not assumed — see the adapter's docstring in `src/ingestion/adapters_spb_batch_o.py`.
- Skate-rental and mass-skating price pages were fetched once at spec time and hardcoded into job.config (same "flat prices from config, not re-scraped every run" convention as `ShansArenaHtmlParser` and `LedovyyDvoretsHtmlParser` in `adapters_ru_pilot.py`) — a future price change on those pages will require a manual job.config update, not a code change.
