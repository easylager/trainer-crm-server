# Parser spec (skip): Ледовая площадка ГУ СДЮШОР (Жодино)

- arena_id: 20
- city: Жодино
- parser_key: zhodino_html_v1
- cadence: weekly
- requires_by_egress: false
- **status: skip / empty** — сезон закрыт, ремонт

Punycode-сайт: https://www.xn----8sbkhlnbugdd1c.xn--90ais/ (ледоваяплощадка.бел).

## Sources

- schedule: https://www.xn----8sbkhlnbugdd1c.xn--90ais/расписание-2/
- prices: https://www.xn----8sbkhlnbugdd1c.xn--90ais/цены/

## Finding (2026-09-05)

На расписании: «в связи с окончанием сезона … завершает свою работу». Времен нет. Прайс живой: МК 6,00 / дет до 14 5,00; прокат 4,50 / 3,50; сеанс 45 мин. Это каталог на reopen, не слоты.

Не публиковать школу СДЮШОР как МК и не строить сетку. Когда появится таблица сеансов — `public_skate`, 600/500/450 (взр. пара проката).

## Fixture

`.ai/data/fixtures/zhodino-sdyushor/` — `raspisanie.html`, `ceny.html` + `expected.json` (`sessions: []`).
