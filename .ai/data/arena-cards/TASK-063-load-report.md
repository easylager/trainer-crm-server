# TASK-063 load report — Minsk MK cards

- mode: dry-run
- generated_at: 2026-09-06T09:49:15+00:00
- wall_ms: 110.7
- source_id for manual slots: `etalon_073`
- media: official operator frames would-upload / upload on --apply (verbal OK 2026-09-06; Google/stock never; grant notes do not block)

| arena_id | slug | profile | photos | sessions | parse_ms | notes |
|---|---|---|---|---|---|---|
| 6 | chizhovka | dry-run published arena_id=6 | upload=3 | would seed 11 slots (2026-08-31…2026-09-06) | 0.4 |  |
| 7 | minsk-diamond | dry-run published arena_id=7 | skip=1, upload=2 | would seed 44 slots (2026-09-05…2026-09-11) | 0.3 |  |
| 8 | minsk-junost | dry-run published arena_id=8 | skip=3 | 403-only / BY-egress — skip | 0.2 | junost.by origin 403 (needs BY-egress) |
| 5 | ledby | dry-run published arena_id=5 | upload=6 | would seed 7 slots (2026-08-31…2026-09-06) | 0.3 |  |
| 4 | minsk-ledlife | dry-run published arena_id=4 | skip=3 | 403-only / BY-egress — skip | 0.1 | ledlife.by origin 403 (needs BY-egress) |
| 2 | minskarena | dry-run published arena_id=2 | skip=1 | would seed 2 slots (2026-09-06…2026-09-12) | 0.2 |  |
| 3 | zamok | dry-run published arena_id=3 | skip=3, upload=6 | would seed 91 slots (2026-09-05…2026-09-11) | 0.4 |  |

## Photo decisions

### chizhovka (arena_id=6)
- `https://chizhovka-arena.by/wp-content/uploads/2021/02/disko11.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://chizhovka-arena.by/wp-content/uploads/2020/10/st_block_row_settings_125741_bg_xwext2oh-scaled-e1602184961320.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://chizhovka-arena.by/wp-content/uploads/2026/08/parkovka-1-300x225.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))

### minsk-diamond (arena_id=7)
- `photos/minsk-diamond/bannerled.png` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://diamondcity.by/d/photo_5386312898617402150_y_1.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://www.instagram.com/diamondcity.by/` → **skip** (instagram/social — never scrape)

### minsk-junost (arena_id=8)
- `https://junost.by/foto/` → **skip** (origin 403 — no file)
- `https://www.instagram.com/junost.by/` → **skip** (instagram/social — never scrape)
- `—` → **skip** (no photo / waiting)

### ledby (arena_id=5)
- `http://led.by/wp-content/gallery/panorama/ice-rink.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `http://led.by/wp-content/gallery/panorama/img_2409.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `http://led.by/wp-content/gallery/panorama/img_2407.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `http://led.by/wp-content/uploads/2011/10/MK.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `http://led.by/wp-content/uploads/2012/12/mass_sm.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `http://led.by/wp-content/gallery/mass/00039.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))

### minsk-ledlife (arena_id=4)
- `https://ledlife.by/foto/` → **skip** (origin 403 — no file)
- `https://www.instagram.com/led_life.by/` → **skip** (instagram/social — never scrape)
- `—` → **skip** (no photo / waiting)

### minskarena (arena_id=2)
- `—` → **skip** (no photo / waiting)

### zamok (arena_id=3)
- `https://tczamok.by/files/entertainments/entertainment/2/katok-meta.jpg` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://tczamok.by/files/resized/entertainment-2/1920x665-katok-new-main.png` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://tczamok.by/files/resized/entertainment/536x320-katok-katok-v2.png` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://tczamok.by/files/resized/entertainment/536x320-katok-konki.png` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://tczamok.by/files/resized/entertainment-2/x520-kassi-katok.png` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://tczamok.by/files/resized/entertainment-2/x520-rasdevalki.png` → **upload** (official operator source — presentation (verbal OK 2026-09-06))
- `https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-3.jpg` → **skip** (arena media limit 6)
- `https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-4.jpg` → **skip** (arena media limit 6)
- `https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-5.jpg` → **skip** (arena media limit 6)

## AC-003 timing

- parser wall-clock mean: **0.3 ms** per dossier (7 arenas; script, not research).
- Estimated operator time from a *ready* TASK-073 dossier (read card, dry-run, confirm): **2–4 minutes per arena**. First-pass research is TASK-073, not this loader.
- Full batch dry-run wall: **0.11 s** for 7 arenas.

## Blockers

- junost.by / ledlife.by: origin **403** without BY-egress — hours/phone/amenities stay unknown where the dossier said so; sessions not invented.
- Fixture `expected.json` files live on the SPEC lane; if absent here, session seed is skipped until those files are on the train.

