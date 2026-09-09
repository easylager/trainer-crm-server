# Parser spec: Ледовый дворец спорта Минской области (led.by)

- arena_id: 5
- parser_key: ledby_html_v1
- cadence: weekly
- requires_by_egress: false

## Sources

- schedule: http://led.by/category/timetable/
- prices: http://led.by/mass_skating/
- widget/api: нет (онлайн-касса на момент снимка «временно не работает»)
- job.config JSON (черновик):

```json
{
  "schedule_url": "http://led.by/category/timetable/",
  "prices_url": "http://led.by/mass_skating/",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "schedule_block_start": "МАССОВОЕ КАТАНИЕ",
  "schedule_block_stop": ["ОТРАБОТКА", "Далее"],
  "disco_marker": "*",
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET timetable, strip tags. Вырезать блоки `МАССОВОЕ КАТАНИЕ …` до `ОТРАБОТКА` / `Далее`. Пропустить чанки без маркера дня (`Пн.dd.mm.yyyy`) — в навменю слово «Массовые катания» даёт ложный кусок.
2. Kind filter: только эти блоки → `public_skate`. Drop `ОТРАБОТКА` (ОХМ), корпоративные, индивидуальные с инструктором, прокат великов. Синоним «свободное» на сайте не используется.
3. Times: день `(?:Пн|Вт|Ср|Чт|Пт|Сб|Вс)\.(\d{2}\.\d{2}\.\d{4})`; время после последнего маркера дня `(\d{1,2}:\d{2})\s*\((\d+)\s*час`. Дата **с страницы**, не rolling week. Длительность = N×60 из `(N час)` (на снимке везде 1 час). `end = start + duration`.
4. `*` сразу после длительности = дискотека на МК → тот же `public_skate`, `session_label=дискотека` (не отдельный продукт).
5. Prices с `/mass_skating/` («СТОИМОСТЬ СЕАНСОВ»), матрица длительность × будни/выходные. Не хардкодить. На снимке 2026-09-05:

| duration | weekday adult/child | weekend adult/child | rental (пара) |
|---|---|---|---|
| 45 мин | 700 / 500 | 800 / 600 | 450 |
| 60 мин | 900 / 700 | 1000 / 800 | 500 |
| 75 мин | 1100 / 900 (одна полоса) | та же | 550 |

Выходной = сб/вс (и «праздничные» на прайсе; V1 — сб/вс). `age_note`: «детский с 3 до 14 лет». Детям до 3 — бесплатно, в слот не пишем отдельной строкой.

6. Drop с прайса: абонементы, инструктор 15 мин, зрительский 1.50, заточка, камера хранения.
7. Merge: один слот на `(local_date, starts_at_local)`. Взр/дет не дублируют время. Прокат берётся по **той же** длительности сеанса.

## Canonical example (expected after validate)

Снимок timetable: 21 слот, все 60 мин. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor | label |
|---|---|---|---|---|---|---|---|
| 2026-09-04 | 19:30 | 20:30 | public_skate | 900 | 700 | 500 | |
| 2026-09-05 | 20:15 | 21:15 | public_skate | 1000 | 800 | 500 | дискотека |
| 2026-09-06 | 19:00 | 20:00 | public_skate | 1000 | 800 | 500 | дискотека |
| 2026-09-12 | 19:15 | 20:15 | public_skate | 1000 | 800 | 500 | |

## Fixture

`data/fixtures/minsk-ledby/` — `timetable.html`, `mass_skating.html` + `expected.json`.

## Blockers / notes

- Geo-блока нет. Сайт на http.
- Спайк ставил всем `price_minor=500` (детский 45 мин) и не парсил прайс — адаптер должен матчить длительность+день.
- Пятн/суббота: «предварительная продажа на выходные» на клиентский слот не влияет.
