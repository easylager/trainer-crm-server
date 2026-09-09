# Parser spec (skip): РЦОП Раубичи

- arena_id: 15
- city: Раубичи
- parser_key: raubichi_html_v1
- cadence: weekly
- requires_by_egress: false
- **status: skip / empty** — «Массовые катания не проводятся»

## Sources

- https://www.rau.by/skates/

## Finding (2026-09-05)

Явная фраза: «Расписание массовых катаний: Массовые катания не проводятся.» Прейскурант на той же странице: взр 7,00 / дет 5,00 / прокат 5,00 — не слоты.

Не материализовать сетку. Когда фраза снимется — weekly HTML, 700/500/500.

## Fixture

`.ai/data/fixtures/raubichi-rcop/` — `skates.html` + `expected.json` (`sessions: []`).
