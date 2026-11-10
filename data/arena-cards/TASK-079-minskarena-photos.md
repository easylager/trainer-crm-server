# TASK-079 — Минск-Арена фото на стенде

- generated_at: 2026-09-06T14:03:00+00:00
- stand: uvicorn `:8000` worktree **task-076**, Postgres `localhost:5432/trainer_crm`
- apply: `scripts/load_minsk_arena_cards.py --apply --allow-local-dev-db --no-seed-sessions --only-arena-ids 2`
- `LOCAL_STORAGE_PATH` = task-076 `uploads/` (тот же процесс, что Mini App)
- ingest / junost / ledlife / slug `manezh`: не трогали

## Что загружено (operator)

| # | source_url | кадр |
|---|---|---|
| 1 | https://abws.minskarena.by/uploads/objects/1UcVhaw8J.jpg | ночной фасад «Арена» (ABWS object id=1) — hero |
| 2 | https://minskarena.by/img/object-bg.jpg | аэрофото комплекса, `/object.html` |
| 3 | https://abws.minskarena.by/uploads/objects/5D75EknaB.jpg | фасад «Конькобежный стадион» (ABWS object id=4) |

Не грузили: `slider_pic.jpg` (концерт), `pic_event_3.jpg` (шоу), SVG-лого, графический баннер МК, Instagram.

Профиль: `parking=true`, `cafe=true` из именованных объектов ABWS. Прокат/заточка/часы МК — по-прежнему unknown.

## Verify

```text
GET /api/public/ice/arenas?intent=skate&city_id=2
# id=2 thumb = /api/public/photos/arenas/2/ddbf00ed6e1a4b5ab25779fbe5499414_thumb.jpg  → 200 image/jpeg

GET /api/public/arenas/2
# hero variants thumb/card/hero; gallery=3; amenities {cafe, parking}
```

Skate list: **5/5** арен с thumb (раньше 4/5).
