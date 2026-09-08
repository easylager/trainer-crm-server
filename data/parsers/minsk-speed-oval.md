# Parser spec: Конькобежный стадион

- arena_id: 115
- city: Минск
- parser_key: minskarena_speed_oval_v1
- cadence: daily
- requires_by_egress: false

Это **другая площадка**, не хоккейная «Минск Арена» (`minskarena_saleframe_v1` / service 55 / arena_id 2). Слоты oval не писать на arena 2.

## Sources

- schedule: https://saleframe.minskarena.by/service/139 (Vue-оболочка, слотов в HTML нет)
- tickets shell: https://saleframe.minskarena.by/?oid=4
- CMS: https://www.minskarena.by/page.html?slug=massovie-katania (слотов в HTML нет)
- prices: те же события ABWS (`expand=prices`)
- rental: https://saleframe.minskarena.by/service/138 — джойнить к MK **по unix `start`**, не по `end` (прокат 60 мин, MK 45 мин)
- widget/api: `https://abws.minskarena.by` (публичный JSON, без cookie / Bearer)
- job.config JSON (черновик):

```json
{
  "url": "https://saleframe.minskarena.by/service/139",
  "api_host": "https://abws.minskarena.by",
  "service_id": 139,
  "init_path": "/api/v3/frame/init",
  "init_query": { "seid": 139, "target": "saleframe", "lang": "ru" },
  "calendar_path": "/api/v1/frame/service/{service_id}/calendar",
  "events_path": "/api/v1/frame/service/{service_id}/events",
  "events_query": {
    "sort": "start",
    "expand": "prices",
    "fields": "id,start,end,quota",
    "target": "saleframe",
    "lang": "ru"
  },
  "timezone": "Europe/Minsk",
  "default_duration_minutes": 45,
  "prices_already_minor": true,
  "adult_zone_id": 1008,
  "child_zone_id": 1009,
  "rental_service_id": 138,
  "rental_zone_id": 1056,
  "kind": "public_skate",
  "kind_allow_substrings": ["массовое катание"],
  "drop_item_name_substrings": ["заточка"],
  "requires_by_egress": false,
  "requires_auth": false
}
```

Не использовать: hockey `service/55` (другой лёд), ByCard, inner HTML CMS.

## How to extract (reverse)

1. GET init `?seid=139&target=saleframe&lang=ru` — `service.id=139`, `duration=45`, performance «Массовое катание на конькобежной дорожке», зоны 1008 взрослый / 1009 детский до 14. Object id=4 «Конькобежный стадион».
2. GET calendar — локальные даты с продажей.
3. Для каждой даты calendar: `from`/`to` = unix начала и конца суток Europe/Minsk. GET events с `expand=prices`.
4. Kind filter: «массовое катание» в имени зоны или mapZoneId 1008/1009. Drop заточка. `kind = public_skate` только.
5. Times: `start`/`end` unix → Europe/Minsk. UI-сентинел `03:01` — drop. Если `end` нет — default **45**. Не брать дни вне calendar.
6. Prices: `prices[].price` **уже minor**. Зона 1008 → `price_adult_minor`, 1009 → `price_child_minor`.
7. Rental: GET events `service/138` на те же calendar days. Зона 1056. `price_rental_minor` = цена события, у которого **тот же `start`**, что у MK. Не джойнить по `end` (прокат длиннее). Если пары нет — `null`.
8. Merge: один слот на `(local_date, starts_at_local)` / `event.id`.

## Canonical example (expected after validate)

Снимок 2026-09-07, calendar days 2026-09-10 и 2026-09-11:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-10 | 14:00 | 14:45 | public_skate | 700 | 550 | 650 |
| 2026-09-11 | 21:15 | 22:00 | public_skate | 900 | 650 | 650 |

`currency_code=BYN`. `age_note` из staticZone: «детский до 14 лет».

## Fixture

`data/fixtures/minsk-speed-oval/` — `calendar.json`, `events.json`, `init.json`, `rental_events.json` + `expected.json`. Stem спеки = имя папки.

## Blockers / notes

- HTML scrape бесполезен. Playwright не нужен, пока ABWS открыт.
- CORS `*`, geo-403 нет.
- Каденс daily: касса выкладывает ближайшие дни.
- Sibling MK hockey/55 — отдельный job на arena 2.
