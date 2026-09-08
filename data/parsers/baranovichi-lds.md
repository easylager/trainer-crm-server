# Parser spec: Ледовый дворец спорта (Барановичи)

- arena_id: 23
- city: Барановичи
- parser_key: baranovichi_html_v1
- cadence: weekly
- requires_by_egress: false

## Sources

- schedule: https://dvorec.by/?p=509
- prices: PDF с https://dvorec.by/?p=85 → `Прейскурант действующих тарифов_1.pdf`
- widget/api: нет; WordPress HTML + scanned PDF
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://dvorec.by/?p=509",
  "prices_page_url": "https://dvorec.by/?p=85",
  "prices_pdf_href_contains": "Прейскурант",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "duration_minutes": 45,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET `?p=509`. Таблица дней: дата | день недели | старты. Пустая ячейка времени («—») = нет сеанса, не изобретать.
2. Kind filter: вся эта страница — массовые катания → `public_skate`. Drop фигурное (`?p=466`), абонементы с прайса.
3. Times: токены `HH.MM` и `HH:MM` в третьей колонке (на снимке воскресенье смешивает `16:45` и `18.45`). Нормализовать в `HH:MM`. `ends_at_local = start + 45` (явно: «Длительность сеанса — 45 минут»). Даты **с таблицы**, год 2026.
4. Prices: скачать PDF прейскуранта со страницы `?p=85` (OCR/текст). На снимке 24.02.2025:
   - «свободного катания для детей до 14 лет» / 45 мин → `3,60` → 360
   - «свободного катания для взрослых» / 45 мин → `4,80` → 480
   - прокат коньков взрослые 1 час → `5,00` → `price_rental_minor=500` (детский прокат 4,50 в слот не дублировать: одно поле)
   - Drop: абонементы 8/12, зритель 0,80, тренажёрка, бильярд, сауна, обучение с тренером
5. Merge: один слот на `(local_date, starts_at_local)`. Взр/дет не режут время.
6. `age_note`: «дети до 14 лет».

## Canonical example (expected after validate)

Неделя 31.08–06.09.2026, 16 слотов. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-08-31 | 19:45 | 20:30 | public_skate | 480 | 360 | 500 |
| 2026-09-05 | 17:30 | 18:15 | public_skate | 480 | 360 | 500 |
| 2026-09-06 | 16:45 | 17:30 | public_skate | 480 | 360 | 500 |

## Fixture

`data/fixtures/baranovichi-lds/` — `schedule.html`, `mass-skating.html`, `prices.pdf`, `prices-page1-sm.jpg` + `expected.json` (16 слотов).

## Blockers / notes

- Geo-блока нет. Каденс weekly: таблица на `?p=509` переписывается на новую неделю.
- PDF — скан; адаптер OCR/текст прейскуранта, не хардкод 360/480.
- hockey.by/news (Авиатор) — анонсы сезона, не сетка; не источник V1.
