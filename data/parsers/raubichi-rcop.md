# Parser spec: РЦОП Раубичи

- arena_id: 15
- arena_slug: raubichi-rcop
- city: Раубичи
- parser_key: raubichi_html_v1
- cadence: daily (seed script)
- requires_by_egress: false

## Sources

- https://www.rau.by/skates/

## Extraction

После заголовка «Расписание массовых катаний:» на странице идут центрированные `<h5 class="wb-stl-custom135">`:
дата `DD.MM.YYYY`, затем строки `HH:MM` (несколько сеансов в день). Длительность сеанса — 45 минут (конфиг).

Если после заголовка только фраза «Массовые катания не проводятся» без дат — `sessions: []` (см. `skates-closed.html`).

Цены на той же странице в `<h5 class="wb-stl-custom22">`: взрослый / детский / прокат коньков (руб с запятой).

## Fixture

`data/fixtures/raubichi-rcop/` — `skates.html` (live snapshot), `skates-closed.html` (empty era), `expected.json`.
