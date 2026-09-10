# Parser spec: ГУ СДЮШОР / ДЮСШ №2 (Пружаны) — SKIP

- arena_id: 27
- city: Пружаны
- parser_key: null
- cadence: —
- requires_by_egress: false
- status: skip

Школа (ДЮСШ №2, ул. Заводская, 15). Платное «физкультурно-оздоровительное катание» населению есть, но **сетки МК в HTML нет**.

## Sources

- https://www.pruzhany.brest-region.gov.by/ru/sport-ru/view/2013-07-15-06-52-27-2000001505
  — «Массовое катание проводится ежедневно, кроме понедельника. График … тел: 8(01632) 3-54-14»
- visitpruzhany.by — то же + Instagram/VK, без таблицы слотов
- hockey.by: pruzhany.dysh2@mail.ru

## How to extract (reverse)

Не извлекать. Только телефон / соцсети. Не МК-фид.

## Canonical example

Слотов нет. `expected.json` → `sessions: []`.

## Fixture

`.ai/data/fixtures/pruzhany-sdyushor/` — `sport.html` (муниципальная страница) + `expected.json` (пусто).

## Blockers / notes

- skip / not MK feed: школа + график по телефону. Не включать в ingest V1.
