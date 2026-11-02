# Parser spec: Ледовая площадка ГУ СДЮШОР (Жодино)

- arena_id: 20
- arena_slug: zhodino-sdyushor
- city: Жодино
- parser_key: zhodino_sdyushor_v1 (`ZhodinoSdyushorParser`, `src/ingestion/adapters_regional_batch_d.py`)
- cadence: daily
- requires_by_egress: true — сайт отвечает только с белорусского IP; гоняется `scripts/by_ingest.sh`
- status: live (с 2026-11-02)

Punycode-сайт: https://www.xn----8sbkhlnbugdd1c.xn--90ais/ (ледоваяплощадка.бел).

## Sources

- schedule: https://www.xn----8sbkhlnbugdd1c.xn--90ais/расписание-2/
- prices: https://www.xn----8sbkhlnbugdd1c.xn--90ais/цены/

## Разметка (2026-11-02)

На странице расписания — по одной `<table>` на неделю (текущая и прошлая), шапка
«Понедельник 02.11.2026 г.» … «Воскресенье 08.11.2026 г.», в ячейках — время начала сеанса МК
(«18.00», «21.15»), пустые ячейки — сеансов нет. Разметка тела битая (нет `</tr>`): ячейки после шапки
читаются одним потоком, колонка = индекс % 7. Ещё две таблицы — легенда («- сеансы массовых катаний»)
и «Дата / Время работы» (без дат в шапке) — пропускаются.

Цены (/цены/): МК взр. 6,50 / дет. до 14 5,50; прокат 4,90 (взрослая пара). «1 сеанс: 45 минут.» —
длительность берётся оттуда, иначе `default_duration_minutes` = 45.

## Fixture

`data/fixtures/zhodino-sdyushor/` — `raspisanie.html`, `ceny.html` (снято 2026-11-02) + `expected.json`.
