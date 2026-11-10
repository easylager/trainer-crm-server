# TASK-077 stand report — local train (Минск, intent=skate)

- generated_at: 2026-09-06T12:40:00+00:00
- stand: local Postgres `trainer_crm` on localhost:5432 (host classified local; not cloud/prod)
- alembic: already `0198_ice_scrape_runs` (0192–0198 present)
- apply: **ran** — `scripts/load_minsk_arena_cards.py --apply --allow-local-dev-db --no-seed-sessions --only-arena-ids 2,3,5,6,7`
- ingest: `scripts/run_ice_ingest_once.py` (enabled Minsk MK keys only; junost/ledlife jobs left disabled)
- verify: `GET http://127.0.0.1:8000/api/public/ice/arenas?intent=skate&city_id=2` → **200**, **5 items**, all with live session line
- photos: local `LOCAL_STORAGE_PATH=./uploads` (S3 keys/bucket unset). Tunnel `cloudflared → 127.0.0.1:8000` was already up; API for this check is the worktree uvicorn on :8000

## Skate list (AC-001)

`city_id=2` (Минск). Filter unchanged (`intent=skate` → future `public_skate|open_ice` only).

| arena_id | name | live_line | thumb |
|---|---|---|---|
| 3 | ТЦ Замок | Сегодня 15:15 · 11 BYN · ещё 85 сеансов | yes |
| 5 | Ледовый дворец спорта Минской области | Сегодня 19:00 · 10 BYN · ещё 5 сеансов | yes |
| 6 | Чижовка-арена | Сегодня 17:30 · 10 BYN · ещё 9 сеансов | yes |
| 7 | ТЦ DiaMond city | Сегодня 15:30 · 12 BYN · ещё 34 сеанса | yes |
| 2 | Минск Арена | Сегодня 17:00 · 8.50 BYN · ещё 1 сеанс | **skip** (see below) |

Count with non-empty live line: **5** (≥3). Thumb GET (Замок) → 200 `image/jpeg`. Card `hero.variants` = thumb/card/hero.

## Arena → photo → slots (AC-004)

| arena_id | slug (dossier) | photo | slots | notes |
|---|---|---|---|---|
| 3 | zamok | **yes** — 4 published operator frames from tczamok.by (would-upload 6; 2 PNGs failed fetch; extras skipped by media cap 6) | **yes** — 86 future. Live `zamok_html_v1` ingest **error** (SSL record-layer to tczamok.by). Empty/error must not wipe future slots; prior horizon kept (through 2026-09-12) | |
| 2 | minskarena | **skip** — no mass-skating ice/facade still on minskarena.by. Homepage/services have UI icons, sponsor/logo, concert `slider_pic.jpg` (packed crowd, no ice), show still `pic_event_3.jpg`. JSON-LD logo is SVG. Not used as MK hero. | **yes** — live `minskarena_saleframe_v1` ok, 2 slots 2026-09-06 17:00 and 19:00 | |
| 6 | chizhovka | **yes** — 3 published from chizhovka-arena.by | **yes** — live ingest 10 published; 10 future through 2026-09-09 | |
| 7 | minsk-diamond | **yes** — 2 published (operator `diamondcity.by` banner + photo; Instagram profile skipped) | **yes** — live ingest 35 published; 35 future through 2026-09-11 | |
| 5 | ledby | **yes** — 6 published from led.by | **yes** — live ingest 6 published; 6 future through 2026-09-13 | |
| 8 | minsk-junost | **skip** — origin 403 / needs BY-egress. No arena_id 8 in this local DB. Job not created/enabled. | **no** — not invented | |
| 4 | minsk-ledlife | **skip** — origin 403 / needs BY-egress. Job `ledlife_origin_html_v1` remains `is_enabled=false`. **Not applied:** local arena_id 4 is «Манеж» (city_id=3), not СДЮШОР/ledlife. Loader `--only-arena-ids` avoided overwriting that row. | **no** — BY job stays off | |

## What was not done

- Did not enable `requires_by_egress` jobs (junost/ledlife).
- Did not write production/cloud DB (loader + ingest host guards).
- Did not change Ice tab UI (`ice-tab.*` / `arena-card.*`).
- Did not scrape Instagram/Google/stock.
- Fixture etalon seed skipped (`--no-seed-sessions`); live ingest used instead so dates stay future. Zamok live fetch failed SSL; existing future rows kept.

## Script change

`scripts/load_minsk_arena_cards.py`: `--only-arena-ids` so a local DB whose id 4 is not ledlife is not overwritten. Prod-refuse tests unchanged and green.

## Test commands

```text
# refuse-prod (trainer_crm_test DSN, not printed)
pytest tests/ops/test_load_minsk_arena_cards.py tests/ingestion/test_run_ice_ingest_once.py -q
# → 16 passed

# apply (this stand)
PYTHONPATH=. python scripts/load_minsk_arena_cards.py --apply --allow-local-dev-db --no-seed-sessions --only-arena-ids 2,3,5,6,7 --no-report

# ingest (this stand)
PYTHONPATH=. python scripts/run_ice_ingest_once.py
# minskarena/chizhovka/diamond/ledby status=ok; zamok_html_v1 status=error (SSL)

# skate list
curl -sS 'http://127.0.0.1:8000/api/public/ice/arenas?intent=skate&city_id=2'
# → total=5, 4 thumbs, all live.kind=session
```
