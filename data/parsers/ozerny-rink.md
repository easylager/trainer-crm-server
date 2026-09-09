# Parser spec: Крытый каток «Озерный» — SKIP (дубль Бреста)

- arena_id: 39
- city: Озерный (prod)
- parser_key: null
- cadence: —
- requires_by_egress: false
- status: skip

## Verify (2026-09-06)

Prod (`by-arenas-prod.csv`): «Минская обл., п. Озерный, ул. Московская, 151», coords **52.0934, 23.7577**.

Это координаты **Бреста**, не Минской области (~1.3 км от id=22, 52.0927, 23.7385).

hockey.by/icearenas:

- Брест ЛДС: `224023, г. Брест, ул. Московская, 151А`
- «Озёрный / Крытый каток»: `223213, Минская обл., п. Озерный, ул. Московская, 151` — тот же street pattern, другой индекс. Отдельного сайта МК нет.

Вывод: карточка id=39 — **геокод/каталожный дубль Брестского ЛДС**, не второй каток для ingest. Слоты МК брать только с id=22.

## How to extract (reverse)

Не извлекать. Не копировать слоты Бреста на id=39.

## Canonical example

Слотов нет. `expected.json` → `sessions: []`.

## Fixture

`.ai/data/fixtures/ozerny-rink/expected.json` (пусто).

## Blockers / notes

- skip: duplicate of arena_id=22. Чинить каталог (PLACE/CONTENT), не парсер.
