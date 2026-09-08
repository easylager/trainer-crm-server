# Parser spec (skip): СРЦ Молодечно / Олимпик-2011

- arena_id: 18
- city: Молодечно
- parser_key: molodechno_src_html_v1
- cadence: weekly
- requires_by_egress: false
- **status: skip / empty** — лёд закрыт с 1 мая 2026

## Sources

- https://src.by/WDKL/ледовая-арена
- job.config: `{ "url": "https://src.by/WDKL/%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0", "timezone": "Europe/Minsk" }`

## Finding (2026-09-05)

Страница живая, прайс есть (свободное катание 45 мин: взр 8.00 / дет до 14 7.00). Строка **«Остановочный период ледовой арены с 1 мая 2026 г.»**; блок «Сеансы массового катания:» без интервалов. Проката в таблице нет.

Не выдумывать сетку. Когда снимут остановочный период — парсить сеансы с той же страницы, цены ×100 → 800/700, rental null пока не появится сумма.

## Fixture

`data/fixtures/molodechno-src/` — `ledovaya-arena.html` + `expected.json` (`sessions: []`).
