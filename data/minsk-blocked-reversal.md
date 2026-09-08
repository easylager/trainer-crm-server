# Reverse-engineering blocked Minsk sources (2026-09-05)

Spike notes — public copies and APIs only. No auth bypass.

## What we tried (and the result)

| Trick | Юность `junost.by` | ledlife.by | Минск-Арена |
|---|---|---|---|
| Browser UA | 403 | 403 | 200, widget stale |
| `X-Forwarded-For` BY IP | 403 | 403 | n/a |
| Googlebot / YandexBot UA | 403 | 403 | n/a |
| jina.ai reader | 403 | 403 | n/a |
| Wayback CDX | **empty** | snapshots through 2025-04 | old HTML |
| Google cache URL | search page, not snapshot | same | — |
| JS bundle → JSON API | — | — | **ByCard `abws.bycard.by` HIT** |
| Secondary public reprint | **stable weekend grid** | Google snippet (often stale) | ticket description |

nginx 1.10.3 on junost/ledlife filters **real egress IP**. Header spoof is not a geo-proxy.

## Working methods

### 1. Юность — reprinted weekend grid (confidence medium)

Origin `https://junost.by/seansy_massovogo_kataniya_na_vyhodnyh/` is 403 from non-BY IP.

Same grid is public on:

- `https://junost.hockey.by/clubs/skating/` (prices + “эти выходные”)
- slivki.by / bestbelarus.by: **сб/вс 17:00–17:45 и 18:15–19:00**

Extractor: `junost_weekend_grid_v1` — materializes next 4 weekend days. Not a live weekly scrape; treat as template until BY egress can confirm the 403 page.

### 2. Минск-Арена — ByCard JSON (the modern way)

Official `minskarena.by/services.html` widget is dead. Tickets live in 24afisha/ByCard.

Discovered in Nuxt `_nuxt/*.js`:

```
GET https://abws.bycard.by/api/v3/pages/events/konkobezhnyy-stadion-minsk-arena
GET https://abws.bycard.by/api/v2/schedule/events/5821807
```

Today: `calendar=[]`, `isSelling=0`, season window `2025-11-01 … 2026-12-31`, duration 45 min, rental **5.50 BYN** in `description`. When касса opens sessions, they land in `calendar` — same parser, no CSS.

### 3. ledlife (СДЮШОР) — still blocked from this IP

Search engines **do** see a weekly HTML table (Google snippet). Wayback has the same table format (`Дата / Начало / Арена / минут / Название`).

Dead ends:

- App **КатОК** (`katok.pasul.dev`) — unpublished in 2025
- Reader proxies inherit the 403

**Real next step:** fetch from a Belarus egress (home IP / BY VPS / Railway region) or a Playwright run on that IP. Then reuse the Wayback table parser.

### 4. Олимпик-арена — not a parser problem

`olympicarena.by` is a hockey/training complex. No public mass-skating schedule. Do not invent sessions.

## What not to do

- Spoofing Googlebot to “look like a crawler” still 403’s — waste
- Publishing Wayback April-2025 rows as current week — lying
- Scraping KatOK after takedown — gone
