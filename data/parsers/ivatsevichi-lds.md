# Parser spec: Ледовая арена (Ивацевичи) — SKIP V1

- arena_id: 28
- city: Ивацевичи
- parser_key: null
- cadence: —
- requires_by_egress: false
- status: skip (Instagram, не V1)

СДЮШОР. МК «в свободное от тренировок время». Расписание в Instagram `@led_arena_basseyn`. Сайт `sdusshor.ivacevichi.edu.by` на прогоне 2026-09-06 — timeout.

## Sources

- hockey.by: Ивацевичи, ул. Ленина, 74 (в prod адрес «Спортивная 3» — расхождение каталога, не парсить)
- тел. +375 164 59-00-53
- Instagram `@led_arena_basseyn` — единственная живая сетка

## How to extract (reverse)

Не извлекать в V1. То же, что Берёза: нет стабильного публичного HTML. Graph API только если каток отдаст Business-токен; неофициальный scrape не кладём в воркер.

## Canonical example

`expected.json` → `sessions: []`.

## Fixture

`.ai/data/fixtures/ivatsevichi-lds/expected.json` (пусто).

## Blockers / notes

- Источник известен (IG). Не «не нашли сайт» — нашли соцсеть. Парсер V1 не пишем.
