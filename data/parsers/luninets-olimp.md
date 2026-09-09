# Parser spec (skip): СК Олимп-2011 (Лунинец)

- arena_id: 40
- city: Лунинец
- parser_key: null
- cadence: n/a
- requires_by_egress: false
- **status: skip** — сайт школы не ответил, публичной сетки МК нет

## Sources tried (2026-09-05)

- http://dussch.luninec.edu.by/ru/main.aspx — **timeout** (0 bytes / 25s)
- Каталоги (masterskating.ru, hockey.by junior schools) — не SoT слотов

## Finding

Крытый каток при ДЮСШ есть; массовые катания упоминаются в справочниках, но живого HTML/JSON расписания с этого egress нет. Не выдумывать 45-мин сетку и не брать устаревшие 1,65/2,45 BYN из агрегаторов.

## Fixture

`.ai/data/fixtures/luninets-olimp/expected.json` — `sessions: []`, `fetch_timeout: true`.
