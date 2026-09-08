# Parser spec: Минск Арена

- arena_id: 2
- parser_key: minskarena_saleframe_v1
- cadence: daily
- requires_by_egress: false

## Sources

- schedule: https://saleframe.minskarena.by/service/55 (Vue-оболочка, слотов в HTML нет)
- prices: те же события ABWS (`expand=prices`)
- widget/api: `https://abws.minskarena.by` (публичный JSON, без cookie / Bearer для чтения)
- job.config JSON (черновик):

```json
{
  "url": "https://saleframe.minskarena.by/service/55",
  "api_host": "https://abws.minskarena.by",
  "service_id": 55,
  "init_path": "/api/v3/frame/init",
  "init_query": { "seid": 55, "target": "saleframe", "lang": "ru" },
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
  "adult_zone_id": 970,
  "child_zone_id": 971,
  "kind": "public_skate",
  "kind_allow_substrings": ["массовое катание"],
  "drop_item_name_substrings": ["заточка"],
  "requires_by_egress": false,
  "requires_auth": false
}
```

Не использовать: `minskarena.by/services.html` (виджет мёртв), ByCard `abws.bycard.by` (`calendar=[]` на момент снимка), `/api/v3/frame/data` (микс концертов и чужих услуг), inner `serviceId` 144 как path календаря (404).

## How to extract (reverse)

1. GET init `?seid=55&target=saleframe&lang=ru` — `service.id=55`, `duration=45`, performance «Массовое катание на хоккейной площадке», зоны 970/971.
2. GET calendar — список локальных дат с продажей. Горизонт = эти даты (часто **один ближайший день**).
3. Для каждой даты calendar: `from`/`to` = unix **начала и конца суток Europe/Minsk**, не UTC-полночь. GET events с `expand=prices`.
4. Kind filter: событие оставляем, если хотя бы один `prices[].mapZoneId` мапится на staticZone с «массовое катание» в имени. Drop заточка (`items` init), концерты, сауна, кёрлинг, хоккейный лёд `service/7`, соседние MK-виджеты 62 и 139 (другая площадка / пустой календарь). `kind = public_skate` только.
5. Times: `start`/`end` unix → Europe/Minsk. UI-сентинел `03:01` («Купить») — drop. Если `end` нет — default **45** явно из `service.duration`. Не брать прошедшие слоты, которых уже нет в calendar (широкое окно events их ещё отдаёт).
6. Prices: `prices[].price` **уже minor**. Не умножать на 100. UI делит на 100. Зона 970 → `price_adult_minor`, 971 → `price_child_minor`. `outerCommissionSum` — комиссия кассы, игнор. `performance.isSelling` бывает 0 при живых билетах — игнор, доверять calendar/events.
7. Rental: `price_rental_minor = null`. Заточка 12.00 BYN — не прокат. Виджет `service/138` «Прокат коньков на конькобежном стадионе» — **другой лёд**, не джойнить к 55.
8. Merge: API уже кладёт взр+дет на **один event**. SPA рисует две строки. Канон — один слот на `(local_date, starts_at_local)` / `event.id`. Если фид когда-нибудь разрежет на два event — merge по этой паре.

## Canonical example (expected after validate)

Снимок 2026-09-05 вечер, calendar day 2026-09-06:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-06 | 17:00 | 17:45 | public_skate | 850 | 600 | null |
| 2026-09-06 | 19:00 | 19:45 | public_skate | 850 | 600 | null |

UTC: 14:00–14:45Z и 16:00–16:45Z. `currency_code=BYN`. `age_note` из staticZone: «детский до 14 лет» (в секции текста бывает «до 16» — брать зону).

## Fixture

`data/fixtures/minsk-arena/` — `calendar.json`, `events.json`, `init.json` + `expected.json`.

## Blockers / notes

- HTML scrape бесполезен. Playwright не нужен, пока ABWS открыт.
- CORS `*`, geo-403 нет.
- Каденс daily: касса выкладывает ближайший день.
- Sibling MK (главная арена / конькобежка) — отдельные jobs, не этот `service_id`.
