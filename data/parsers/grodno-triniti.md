# Parser spec: ТЦ «Тринити» (Гродно)

- arena_id: 10
- city: Гродно
- parser_key: triniti_ice_api_v1
- cadence: daily
- requires_by_egress: false

## Sources

- schedule: https://ice.triniti-grodno.by/ (dhtmlx scheduler; слоты в JSON)
- prices: слот в API (`price` / `c_price`) + https://ice.triniti-grodno.by/prajs.html для проката
- widget/api: `GET https://ice.triniti-grodno.by/api/ice.php` (без query; query игнор)
- job.config JSON (черновик):

```json
{
  "url": "https://ice.triniti-grodno.by/",
  "api_url": "https://ice.triniti-grodno.by/api/ice.php",
  "prices_url": "https://ice.triniti-grodno.by/prajs.html",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "prices_are_major_byn": true,
  "adult_field": "price",
  "child_field": "c_price",
  "rental_minor": 800,
  "drop_if_adult_minor_gte": 2000,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET `api/ice.php` → `{ "data": [ ... ] }`. HTML главной для extract не нужен (касса «только офлайн» на снимке не отключает JSON).
2. Kind filter: этот фид — сеансы катка. `section_id` — корзина времени, не вид услуги. Drop если `price >= 20` (тариф «Хоккеист» 25 руб на прайсе; в снимке 2026-09-05 таких нет). Drop аренда зала / ледовая машина — их нет в `ice.php`.
3. Times: `start_date` / `end_date` naive local (`YYYY-MM-DD HH:MM:SS`) в Europe/Minsk. Длительность на снимке 45 мин. `tt` = квота мест (120), **не** минуты.
4. Prices: `price` и `c_price` — **рубли BYN**, не minor. ×100 → 900/700 будни, 1100/900 выходные. Совпадает с прайсом «с НДС». Не путать с saleframe (там уже копейки).
5. Rental: в JSON нет. С прайса «Прокат коньков … с НДС 8,00» → `price_rental_minor=800` (общий на арену).
6. Merge: API уже один объект на сеанс с взр+дет. Один канонический слот на `id` / `(local_date, starts_at_local)`.
7. `age_note`: «детский от 3 до 12 лет» (прайс).

## Canonical example (expected after validate)

Снимок 2026-09-05, горизонт 6–12 сен, 71 слот. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-06 | 11:00 | 11:45 | public_skate | 1100 | 900 | 800 |
| 2026-09-08 | 11:00 | 11:45 | public_skate | 900 | 700 | 800 |
| 2026-09-12 | 11:00 | 11:45 | public_skate | 1100 | 900 | 800 |

## Fixture

`.ai/data/fixtures/grodno-triniti/` — `ice.json`, `prajs.html`, `expected.json`.

## Blockers / notes

- Geo-блока нет. Каденс daily: JSON на неделю вперёд.
- Онлайн-оплата на сайте может быть выключена — на extract не влияет.
