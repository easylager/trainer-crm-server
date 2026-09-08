# Parser spec (skip): Крытый каток РГЦ «Силичи»

- arena_id: 16
- city: Силичи
- parser_key: null
- cadence: n/a
- requires_by_egress: false
- **status: skip** — сезонный каток, сетка на странице = зима

## Sources

- https://silichy.by/aktualnoe-vremya-raboti
- opening posts: https://silichy.by/vse-na-led-3-dekabrya-otkrivaem-katok

## Finding (2026-09-05)

«Актуальное время работы» всё ещё печатает график **«С 14 декабря»** (будни 18.00/19.30/21.00, выходные с 9.00, сеанс 60 мин). Capture day — 5 сентября: это прошлый сезон, не текущее МК. Не публиковать декабрьские часы как сентябрь.

V1: нет адаптера. Ждать пост открытия сезона, затем weekly HTML с silichy.by.

## Fixture

`data/fixtures/silichi-rgc/` — `aktualnoe-vremya-raboti.html` + `expected.json` (`sessions: []`).
