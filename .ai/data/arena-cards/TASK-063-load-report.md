# TASK-063 load report — Minsk MK cards

- mode: dry-run
- generated_at: 2026-09-05T22:15:53+00:00
- wall_ms: 2.0
- source_id for manual slots: `etalon_073`
- media: no CDN upload in this run (license not granted / нужно разрешение / DiaMond wait)

| arena_id | slug | profile | photos | sessions | parse_ms | notes |
|---|---|---|---|---|---|---|
| 6 | chizhovka | dry-run published arena_id=6 | skip=3 | no expected.json on this train | 0.4 |  |
| 7 | minsk-diamond | dry-run published arena_id=7 | skip=3 | no expected.json on this train | 0.3 |  |
| 8 | minsk-junost | dry-run published arena_id=8 | skip=3 | no expected.json on this train | 0.1 | junost.by origin 403 (needs BY-egress) |
| 5 | ledby | dry-run published arena_id=5 | skip=6 | no expected.json on this train | 0.3 |  |
| 4 | minsk-ledlife | dry-run published arena_id=4 | skip=3 | no expected.json on this train | 0.1 | ledlife.by origin 403 (needs BY-egress) |
| 2 | minskarena | dry-run published arena_id=2 | skip=1 | no expected.json on this train | 0.2 |  |
| 3 | zamok | dry-run published arena_id=3 | skip=9 | no expected.json on this train | 0.3 |  |

## Photo decisions

### chizhovka (arena_id=6)
- `https://chizhovka-arena.by/wp-content/uploads/2021/02/disko11.jpg` → **skip** (нужно разрешение / фото нет)
- `https://chizhovka-arena.by/wp-content/uploads/2020/10/st_block_row_settings_125741_bg_xwext2oh-scaled-e1602184961320.jpg` → **skip** (нужно разрешение / фото нет)
- `https://chizhovka-arena.by/wp-content/uploads/2026/08/parkovka-1-300x225.jpg` → **skip** (нужно разрешение / фото нет)

### minsk-diamond (arena_id=7)
- `photos/minsk-diamond/bannerled.png` → **skip** (DiaMond local PNG is operator-hosted; TASK-073 wait for grant — not published in media)
- `https://diamondcity.by/d/photo_5386312898617402150_y_1.jpg` → **skip** (license named but no transfer-of-rights / CDN upload in this loader)
- `https://www.instagram.com/diamondcity.by/` → **skip** (нужно разрешение / фото нет)

### minsk-junost (arena_id=8)
- `https://junost.by/foto/` → **skip** (нужно разрешение / фото нет)
- `https://www.instagram.com/junost.by/` → **skip** (нужно разрешение / фото нет)
- `—` → **skip** (no photo / waiting)

### ledby (arena_id=5)
- `http://led.by/wp-content/gallery/panorama/ice-rink.jpg` → **skip** (нужно разрешение / фото нет)
- `http://led.by/wp-content/gallery/panorama/img_2409.jpg` → **skip** (нужно разрешение / фото нет)
- `http://led.by/wp-content/gallery/panorama/img_2407.jpg` → **skip** (нужно разрешение / фото нет)
- `http://led.by/wp-content/uploads/2011/10/MK.jpg` → **skip** (нужно разрешение / фото нет)
- `http://led.by/wp-content/uploads/2012/12/mass_sm.jpg` → **skip** (нужно разрешение / фото нет)
- `http://led.by/wp-content/gallery/mass/00039.jpg` → **skip** (нужно разрешение / фото нет)

### minsk-ledlife (arena_id=4)
- `https://ledlife.by/foto/` → **skip** (нужно разрешение / фото нет)
- `https://www.instagram.com/led_life.by/` → **skip** (нужно разрешение / фото нет)
- `—` → **skip** (no photo / waiting)

### minskarena (arena_id=2)
- `—` → **skip** (no photo / waiting)

### zamok (arena_id=3)
- `https://tczamok.by/files/entertainments/entertainment/2/katok-meta.jpg` → **skip** (нужно разрешение / фото нет)
- `https://tczamok.by/files/resized/entertainment-2/1920x665-katok-new-main.png` → **skip** (нужно разрешение / фото нет)
- `https://tczamok.by/files/resized/entertainment/536x320-katok-katok-v2.png` → **skip** (нужно разрешение / фото нет)
- `https://tczamok.by/files/resized/entertainment/536x320-katok-konki.png` → **skip** (нужно разрешение / фото нет)
- `https://tczamok.by/files/resized/entertainment-2/x520-kassi-katok.png` → **skip** (нужно разрешение / фото нет)
- `https://tczamok.by/files/resized/entertainment-2/x520-rasdevalki.png` → **skip** (нужно разрешение / фото нет)
- `https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-3.jpg` → **skip** (нужно разрешение / фото нет)
- `https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-4.jpg` → **skip** (нужно разрешение / фото нет)
- `https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-5.jpg` → **skip** (нужно разрешение / фото нет)

## AC-003 timing

- parser wall-clock mean: **0.2 ms** per dossier (7 arenas; script, not research).
- Estimated operator time from a *ready* TASK-073 dossier (read card, dry-run, confirm): **2–4 minutes per arena**. First-pass research is TASK-073, not this loader.
- Full batch dry-run wall: **0.00 s** for 7 arenas.

## Blockers

- junost.by / ledlife.by: origin **403** without BY-egress — hours/phone/amenities stay unknown where the dossier said so; sessions not invented.
- Fixture `expected.json` files live on the SPEC lane; if absent here, session seed is skipped until those files are on the train.

