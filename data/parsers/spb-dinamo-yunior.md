# Parser spec: Ледовая арена «Динамо-Юниор»

- arena_id: 173
- parser_key: dinamoyunior_html_v1
- cadence: daily
- requires_by_egress: false

## Sources
- schedule + prices: https://shorspb.ru/Skating
- widget/api: none — plain static HLNet CMS page, no JS-rendered widget, no bot-block observed (plain `curl` returns 200, ~74KB real HTML)
- job.config JSON (черновик):

```json
{
  "url": "https://shorspb.ru/Skating",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "week_start": null,
  "horizon_days": 7
}
```

## How to extract (reverse)
1. Fetch `/Skating`, strip tags. The schedule text is a single hand-maintained paragraph (sitting inside a stray `<h1>` on the source page — not semantically a heading, just how the operator's editor saved it), not a repeating label→value block like Kupchino, so there's no separate label to anchor a window on; the weekday+time regex is specific enough (weekday stem + digit pair + dash + digit pair) not to false-match anywhere else on the page (checked: no other place on the page prints a weekday word immediately followed by an `HH:MM-HH:MM` range).
2. Kind filter: none needed — the page publishes exactly one product ("массовое катание на коньках"); everything matched is in scope.
3. Times: match `<weekday stem>...в HH:MM-HH:MM` — the 2026-09-22 snapshot reads "Каждую субботу в 21:00-22:00" (every Saturday, 21:00-22:00). Both start and end are always present in the source, no duration fallback needed.
4. Dates: the page names a weekday, not calendar dates — project the extracted weekday→(start,end) map forward over a `horizon_days`-day sliding window starting at `week_start` (defaults to the run date), same convention as `IzhoretsHtmlParser` / `LidaLdsParser`.
5. Prices: two figures in the same paragraph — "Стоимость входного билета ... 1 час (60 минут) – 500 руб." (adult) and "Стоимость проката коньков ... 1 пара/1 час (60 минут) – 300 р." (rental). **Quirk**: a naive "first number after the label" read is wrong here — the source prints an unrelated "1 час (60 минут)" duration *before* the actual price on the same line, so the adapter anchors on the currency suffix (`руб`/`р.`) instead of label proximity alone. No child price is published anywhere on the page.
6. Merge: not applicable — only one weekday/time pair is currently published; nothing to merge across rows.

## Canonical example (expected after validate)
| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-26 | 21:00 | 22:00 | public_skate | 50000 | null | 30000 |

## Fixture
`data/fixtures/spb-dinamo-yunior/` — `skating.html` (raw fetch, 2026-09-22, plain `curl`, HTTP 200) + `expected.json` канона (computed with `week_start=2026-09-22`, `horizon_days=7`).

## Blockers / notes
- Primary candidate this round, Крытый каток при академии ледовых видов спорта «Динамо» СПб (arena_id=176, ул. Мебельная, д. 33А), was tried first and ruled infeasible: it's a genuinely different physical venue from arena_id=175 (ул. Маршала Новикова, 14, ruled infeasible in a prior round — see `spb-izhorets.md`) but shares the same parent organization and the same outcome. The org's own domain `school-internat576.ru` sits fully behind DDoS-Guard (clean HTTP 403 bot-challenge body, confirmed independently this round, both http:// and https://). Its youth-hockey subdomain `kids.dynamo-spb.com` is live but its "Инфраструктура" page describes a *third*, wholly separate Dynamo rink (пер. Каховского, д. 2Б/2К) — it never mentions Мебельная at all. The hockey club's own site `hcdynamopiter.orgs.biz` mentions Мебельная only inside VK-sourced player-tryout announcement images, no schedule text anywhere. The only public-facing schedule/booking surface actually tied to this address is a third-party booking SaaS widget, `ledovyy-mebelnaya.ledokat.ru` ("Олимпийские надежды" hall) — explicitly out of scope for this lane (needs a real API integration, not a static-HTML scrape).
- Backup 1, «Динамо-Юниор» (arena_id=181, ул. Бутлерова, д. 36), was tried next: its operator's own site `shorspb.ru` is live and has this exact `/Skating` page — but the page's own text names a *different* street address for the actual sessions ("на ледовой арене школы по хоккею «Динамо-юниор» по адресу г. Санкт-Петербург, ул. Фаворского, д.7"), i.e. this spec's venue, not Бутлерова. Бутлерова, 36 (on the grounds of SK «Спартак») is the school's administrative/training address per its Contacts page — no public-skating schedule is published for it specifically. Treated as infeasible for that arena row.
- Backup 2, «Ледовая арена Динамо-Юниор» (arena_id=173, ул. Фаворского, 7), is this spec — feasible, same site, schedule text is explicitly about this address.
- Only one weekly session is currently published (Saturday 21:00-22:00). If the operator adds more days, the regex/projection already generalizes (matches any of the 7 weekday stems, any number of occurrences).
- `cadence: daily` chosen per this lane's default preference — the page could change the single published session's day/time/price at any point with no advance notice, and a less-frequent cadence risks missing that for days.
