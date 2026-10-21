# Parser spec: Витебск Дворец спорта

- arena_id: 29
- arena_slug: vitebsk-ds
- city: Витебск
- parser_key: vitebsk_ds_v1
- cadence: daily
- requires_by_egress: false

Не путать с Новополоцком id=30 (ХК «Химик»).

## Sources

- schedule+prices: `GET https://api.24afisha.by/api/v2/schedule/events/1385106?cityId=11&lang=ru&slug=true&jsonld=0&ignoreEndTime=1`
- event page (wide buy button): https://24afisha.by/ru/vitebsk/event/massovoe-katanie-v-vitebskom-dvortse-sporta
- per-session checkout: `https://saleframe.24afisha.by/?sid={session_id}&lang=ru`
- hockey.by `massovoe-katanie` is not the source. On 2026-10-21 it still showed 30 Apr–3 May. Do not parse it.
- job.config JSON:

```json
{
  "schedule_api_url": "https://api.24afisha.by/api/v2/schedule/events/1385106?cityId=11&lang=ru&slug=true&jsonld=0&ignoreEndTime=1",
  "afisha_event_id": 1385106,
  "afisha_city_id": 11,
  "afisha_object_id": 124,
  "afisha_event_url": "https://24afisha.by/ru/vitebsk/event/massovoe-katanie-v-vitebskom-dvortse-sporta",
  "session_tickets_url": "https://saleframe.24afisha.by/?sid={session_id}&lang=ru",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "default_duration_minutes": 60,
  "requires_by_egress": false,
  "prices_already_minor": true
}
```

## How to extract

1. GET the schedule JSON. Take `data[].objects[]` where `id` is 124 (Ледовый Дворец Витебск). Drop any other object.
2. Each `sessions[]` row is one public skate. `dateStr` is `DD.MM.YYYY`, `timeStr` is `HH:MM`, both already Europe/Minsk. `end = start + duration` from the event (60). Skip a row with no parseable date or time.
3. `minPrice` is already minor (`700` = 7.00 BYN) → `price_adult`. No child tariff. Skate rental is two sizes (5,00 BYN up to 34, 10,00 BYN from 35), so it stays on the arena card (`rental_catalog`), not in the single `price_rental_minor` column.
4. `external_url` is `https://saleframe.24afisha.by/?sid={id}&lang=ru`. `source_id` is the session id. Kind is массовое катание.
5. Jobs seeded before this switch still have `url` = hockey.by. The adapter ignores that key and calls the API above.
6. The first GET from a server is an HTML page titled Verification. It contains `hg-security=<token>`. Repeat the GET with that cookie. Do not run the page's JavaScript.

## Canonical example

Снимок API 2026-10-21. Полный набор — `data/fixtures/vitebsk-ds/expected.json`.

| local_date | starts_at_local | ends_at_local | adult_minor | external_url |
|---|---|---|---|---|
| 2026-10-23 | 22:00 | 23:00 | 700 | saleframe `?sid=1769799` |
| 2026-10-24 | 20:30 | 21:30 | 700 | saleframe `?sid=1769800` |
| 2026-10-25 | 21:00 | 22:00 | 700 | saleframe `?sid=1769801` |

## Fixture

`data/fixtures/vitebsk-ds/schedule.json` + `expected.json`. `massovoe-katanie.html` is the old club-site snapshot and is not an input.

## Notes

- Wide buy button on the place page is `arena_profiles.tickets_url` (the event page). Per-session checkout is `ice_sessions.external_url`.
- `age_note`: до 3 лет нельзя; 3–12 только с взрослым 18+ на коньках; поздние сеансы — с законным представителем.
