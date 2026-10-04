# TASK-063 load report — Minsk MK cards

- mode: apply
- generated_at: 2026-10-04T00:55:10+00:00
- wall_ms: 2029.6
- source_id for manual slots: `etalon_073`
- media: official operator frames would-upload / upload on --apply (verbal OK 2026-09-06; Google/stock never; grant notes do not block)

| arena_id | slug | profile | photos | sessions | parse_ms | notes |
|---|---|---|---|---|---|---|
| 11 | grodno-neman | published upsert arena_id=11 | upload=1 | 0 seeded; sessions disabled | 0.5 |  |

## Photo decisions

### grodno-neman (arena_id=11)
- `photos/arena-11/hero.webp` → **upload** (official operator source — presentation (verbal OK 2026-09-06))

## AC-003 timing

- parser wall-clock mean: **0.5 ms** per dossier (1 arenas; script, not research).
- Estimated operator time from a *ready* TASK-073 dossier (read card, dry-run, confirm): **2–4 minutes per arena**. First-pass research is TASK-073, not this loader.
- Full batch dry-run wall: **2.03 s** for 1 arenas.

## Blockers

- junost.by / ledlife.by: origin **403** without BY-egress — hours/phone/amenities stay unknown where the dossier said so; sessions not invented.
- Fixture `expected.json` files live on the SPEC lane; if absent here, session seed is skipped until those files are on the train.

