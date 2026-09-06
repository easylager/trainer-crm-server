# Parser spec: Ледовая арена (Берёза) — SKIP V1

- arena_id: 26
- city: Береза
- parser_key: null
- cadence: —
- requires_by_egress: false
- status: skip (Instagram, не V1)

## Sources

- hockey.by catalog: Берёза, ул. 17 Сентября, 39, тел. +375 164 34-46-76 / 34-55-46
- **расписание МК — еженедельное фото в Instagram** (официальный аккаунт катка). HTML/JSON сетки нет.

## How to extract (reverse)

Не извлекать в V1. Instagram не fetch-плоскость ingestion: логин/Graph API, ToS, посты-картинки (ещё и OCR), ломается без предупреждения.

## Canonical example

`expected.json` → `sessions: []`.

## Fixture

`.ai/data/fixtures/bereza-lds/expected.json` (пусто).

## Blockers / notes

- Источник **есть** (Instagram), это не «катка нет». Адаптер не пишем, пока не появится HTML/фото на своём сайте как у Шклова.
- Не путать с парсингом чужих IG-аккаунтов через неофициальные API.
