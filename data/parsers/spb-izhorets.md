# Parser spec: СПб ГБУ СОК «Ижорец» — ФОК «Ижорец» (пос. Металлострой)

- arena_id: 185
- parser_key: izhorets_html_v1
- cadence: daily
- requires_by_egress: false

## Sources
- schedule: https://www.sok-izhorets.ru/massovoe-katanie-fok-izhorets
- prices: none published on the schedule page; a separate page (https://www.sok-izhorets.ru/platnye-uslugi-2/fok-izhorets-pos-metallostroj-ul-pushkinskaya-d-3-lit-b) links a PDF price list whose filename changes on every update and returned HTTP 404 when checked live on 2026-09-22 — not parsed in v1
- widget/api: none — plain server-rendered Joomla page
- job.config JSON (черновик):

```json
{ "url": "https://www.sok-izhorets.ru/massovoe-katanie-fok-izhorets", "timezone": "Europe/Moscow", "currency_code": "RUB", "kind": "public_skate", "default_duration_minutes": 60, "week_start": null, "horizon_days": 7, "requires_by_egress": false }
```

## How to extract (reverse)
1. Fetch the page, strip tags, anchor on the label text "Расписание сеансов" (bounded until the next label "Возможны изменения" to avoid picking up unrelated content elsewhere on the page).
2. Within that window, match `<Weekday> <HH.MM или HH:MM>[, HH:MM]...` — the source mixes `.` and `:` as the hour/minute separator on the same line (confirmed real quirk, not a typo). One weekday can list more than one time (comma-separated) — treat each as a separate session start, not a start/end range (no "до"/dash separator is ever used here, unlike Kupchino's explicit ranges).
3. Kind filter: everything on this page is "Платно:" (paid) public/mass skating → `public_skate`. No free/`open_ice` sessions are published.
4. Times: start-only, no end time or duration printed anywhere → rely on `IceSessionNormalizer`'s `default_duration_minutes` fallback (60 min, not confirmed against the source).
5. Dates: the page names weekdays, not calendar dates — project the extracted weekday→times map forward over a `horizon_days`-day sliding window starting at `week_start` (defaults to the run date), same convention as `LidaLdsParser` (`adapters_regional_batch_b.py`).
6. Prices: none present in the HTML. The linked PDF price list 404s intermittently and its filename changes on every operator update — out of scope for this pass. `price_adult` / `price_child` / `price_rental` are always `null`.
7. Merge: N/A — no adult/child pair to merge; every slot carries only a start time.

## Canonical example (expected after validate)
| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-26 | 20:00 | 21:00 | public_skate | null | null | null |
| 2026-09-27 | 13:00 | 14:00 | public_skate | null | null | null |
| 2026-09-27 | 14:15 | 15:15 | public_skate | null | null | null |

## Fixture
`data/fixtures/spb-izhorets/` — real `curl` snapshot of the schedule page (2026-09-22) as `massovoe-katanie.html`, plus `expected.json` canon (computed with `week_start=2026-09-22`, `horizon_days=7`).

## Blockers / notes
- Primary candidate this round, Академия ледовых видов спорта «Динамо» СПб (arena_id=175, likely duplicate of id=176), was tried first and ruled infeasible: the academy's own domain `school-internat576.ru` sits fully behind DDoS-Guard (clean HTTP 403 bot-challenge, both http:// and https://); its sports-school subdomain `kids.dynamo-spb.com` is live but is the youth hockey school portal with no public-skating schedule; the only other public-facing schedule/booking page, `novikova.ledokat.ru`, is a third-party booking SaaS widget (Ledokat) — explicitly out of scope for this lane (needs a real API integration). Ижорец (arena_id=185, this spec) was tried next as backup 1 and is feasible.
- Prices are PDF-only and the PDF link 404s intermittently with a filename that changes per update — not scraped; `price_*` fields always null until a future pass adds PDF parsing (see e.g. `baranovichi-lds` / `kobrin-lds` for existing PDF-price precedent in the BY lane).
- Two comma-separated times on the same weekday ("Воскресенье 13.00, 14:15") are read as two separate session starts, not a start/end range — flagged, not asserted as fact; the source never spells out which reading is intended.
- Arena has a second physical location under the same operator, СПОРТИВНЫЙ КОМПЛЕКС «ИЖОРЕЦ» (г. Колпино, ул. Тверская, д. 25) — distinct from this ФОК «Ижорец» (пос. Металлострой) venue and its schedule page; not covered here.
