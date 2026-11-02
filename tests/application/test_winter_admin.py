"""Админ-операции на старте сезона: пачки, отмена, слияние, переименование, 301 (TASK-343)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from src.application import arena_slug_redirects as red
from src.application import winter_admin as wa
from src.application import winter_marks as wm
from tests.application.winter_helpers import NOW, SEASON, make_city, make_client, make_point


async def _state(db, aid):
    return (await db.execute(
        text("SELECT state, admin_confirmed_at, hidden_reason, state_source FROM seasonal_rink_seasons WHERE arena_id=:a AND season=:s"),
        {"a": aid, "s": SEASON})).one()


@pytest.mark.asyncio
async def test_confirm_batch_by_city_and_kind_keeps_ice_state(db_session):
    a = await make_point(db_session, name="A", city="Минск")
    b = await make_point(db_session, name="B", city="Минск", kind="hockey_box")
    c = await make_point(db_session, name="C", city="Гродно")
    await wm.set_state_admin(db_session, a, "flooded", admin_id=1, now=NOW - timedelta(hours=2))
    await db_session.execute(text("UPDATE seasonal_rink_seasons SET admin_confirmed_at=NULL WHERE arena_id=:a"), {"a": a})
    city = await make_city(db_session, "Минск")
    sel = wa.Selection(city_id=city)
    assert await wa.select_ids(db_session, sel, SEASON) == sorted([a, b])
    res = await wa.apply_batch(db_session, "confirm", sel, admin_id=7, now=NOW, expect_count=2)
    assert res.count == 2
    assert (await _state(db_session, a)).state == "flooded" and (await _state(db_session, a)).admin_confirmed_at is not None
    assert (await _state(db_session, c)).admin_confirmed_at is None  # другой город не тронут
    assert await wa.select_ids(db_session, sel, SEASON) == []  # повтор — пусто


@pytest.mark.asyncio
async def test_stale_preview_is_refused(db_session):
    await make_point(db_session, city="Минск")
    city = await make_city(db_session, "Минск")
    with pytest.raises(wa.AdminOpError) as e:
        await wa.apply_batch(db_session, "confirm", wa.Selection(city_id=city), admin_id=1, now=NOW, expect_count=5)
    assert e.value.code == "stale"


@pytest.mark.asyncio
async def test_doubtful_and_dispute_points_are_not_in_bulk(db_session):
    a = await make_point(db_session, name="A")
    d = await make_point(db_session, name="D")
    await db_session.execute(text("UPDATE seasonal_rink_seasons SET doubtful=true WHERE arena_id=:a"), {"a": d})
    assert await wa.select_ids(db_session, wa.Selection(), SEASON) == [a]


@pytest.mark.asyncio
async def test_hide_closes_queue_items_and_undo_restores(db_session):
    a = await make_point(db_session, name="A")
    await db_session.execute(text("INSERT INTO seasonal_moderation_items (kind, arena_id) VALUES ('new_point', :a)"), {"a": a})
    res = await wa.apply_batch(db_session, "hide", wa.Selection(), admin_id=1, now=NOW)
    st = await _state(db_session, a)
    assert st.state == "hidden" and st.hidden_reason == "admin"
    assert (await db_session.execute(text("SELECT status FROM seasonal_moderation_items WHERE arena_id=:a"), {"a": a})).scalar_one() == "done"
    out = await wa.undo_batch(db_session, res.batch_id, now=NOW + timedelta(minutes=5))
    assert out == {"status": "ok", "restored": 1, "skipped": 0}
    st = await _state(db_session, a)
    assert st.state == "waiting" and st.hidden_reason is None
    assert (await db_session.execute(text("SELECT status FROM seasonal_moderation_items WHERE arena_id=:a"), {"a": a})).scalar_one() == "open"
    assert (await wa.undo_batch(db_session, res.batch_id, now=NOW))["status"] == "already"


@pytest.mark.asyncio
async def test_undo_expires_after_ten_minutes_and_skips_rows_changed_since(db_session):
    a = await make_point(db_session, name="A")
    b = await make_point(db_session, name="B")
    r1 = await wa.apply_batch(db_session, "confirm", wa.Selection(), admin_id=1, now=NOW)
    # b после пачки кто-то скрыл руками — отмена его не возвращает
    await wm.set_state_admin(db_session, b, "hidden", admin_id=2, now=NOW + timedelta(minutes=1))
    out = await wa.undo_batch(db_session, r1.batch_id, now=NOW + timedelta(minutes=2))
    assert out["restored"] == 1 and out["skipped"] == 1
    assert (await _state(db_session, a)).admin_confirmed_at is None
    assert (await _state(db_session, b)).state == "hidden"
    r2 = await wa.apply_batch(db_session, "confirm", wa.Selection(), admin_id=1, now=NOW)
    assert (await wa.undo_batch(db_session, r2.batch_id, now=NOW + timedelta(minutes=11)))["status"] == "expired"


@pytest.mark.asyncio
async def test_confirming_candidates_makes_them_visible_and_closes_item(db_session):
    a = await make_point(db_session, name="OSM", state="hidden")
    await db_session.execute(text("UPDATE seasonal_rink_seasons SET hidden_reason='candidate' WHERE arena_id=:a"), {"a": a})
    await db_session.execute(text("INSERT INTO seasonal_moderation_items (kind, arena_id) VALUES ('new_point', :a)"), {"a": a})
    # обычная пачка кандидатов не касается
    assert await wa.select_ids(db_session, wa.Selection(), SEASON) == []
    sel = wa.Selection(scope="candidates")
    res = await wa.apply_batch(db_session, "confirm", sel, admin_id=1, now=NOW)
    st = await _state(db_session, a)
    assert res.count == 1 and st.state == "waiting" and st.hidden_reason is None
    assert (await db_session.execute(text("SELECT status FROM seasonal_moderation_items WHERE arena_id=:a"), {"a": a})).scalar_one() == "done"
    await wa.undo_batch(db_session, res.batch_id, now=NOW)
    assert (await _state(db_session, a)).state == "hidden"


@pytest.mark.asyncio
async def test_season_overview_counts_by_city(db_session):
    await make_point(db_session, name="A", city="Минск")
    await make_point(db_session, name="B", city="Минск", kind="hockey_box")
    await make_point(db_session, name="C", city="Гродно")
    h = await make_point(db_session, name="H", city="Гродно", state="hidden")
    await db_session.execute(text("UPDATE seasonal_rink_seasons SET hidden_reason='candidate' WHERE arena_id=:a"), {"a": h})
    ov = await wa.season_overview(db_session, NOW)
    by = {c["city"]: c for c in ov["cities"]}
    assert ov["unconfirmed"] == 3 and ov["candidates"] == 1
    assert by["Минск"]["unconfirmed"] == 2 and by["Минск"]["hockey_box"] == 1 and by["Гродно"]["candidates"] == 1


# --- дубли и слияние ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicates_found_by_address_name_and_distance(db_session):
    a = await make_point(db_session, name="Каток Школа 5", lat=53.9000, lon=27.5000)
    b = await make_point(db_session, name="Каток школа 5", lat=53.9100, lon=27.6000)   # то же имя
    c = await make_point(db_session, name="Другой", lat=53.90030, lon=27.50030)          # рядом с a
    d = await make_point(db_session, name="Коробка", kind="hockey_box", lat=53.9000, lon=27.5000)  # другой тип
    # одинаковый адрес у всех из make_point -> a, b, c, d(коробка) по адресу: у d тип другой
    groups = await wa.find_duplicate_groups(db_session, NOW)
    assert len(groups) == 1
    ids = {m.arena_id for m in groups[0].members}
    assert ids == {a, b, c} and d not in ids
    assert groups[0].reasons >= {"address"}


@pytest.mark.asyncio
async def test_keep_candidate_prefers_named_visible_with_activity(db_session):
    a = await make_point(db_session, name="Каток 1")
    b = await make_point(db_session, name="Каток 2")
    await db_session.execute(text("UPDATE seasonal_rinks SET name_source='generated' WHERE arena_id=:a"), {"a": a})
    g = (await wa.find_duplicate_groups(db_session, NOW))[0]
    assert g.keep_candidate().arena_id == b


@pytest.mark.asyncio
async def test_merge_moves_marks_photos_subscriptions_media_and_leaves_301(db_session):
    keep = await make_point(db_session, name="Основной", slug="minsk-katok-1")
    dup = await make_point(db_session, name="Дубль", slug="minsk-katok-2", pin=1)
    cid = await make_city(db_session)
    await make_client(db_session, 501)
    await wm.record_mark(db_session, arena_id=dup, kind="ice", value="flooded", source="telegram", actor="tg:501", telegram_id=501, now=NOW)
    await db_session.execute(
        text("INSERT INTO seasonal_rink_photos (arena_id, author_telegram_id, storage_key) VALUES (:a, 501, 'k1')"), {"a": dup})
    await db_session.execute(
        text("INSERT INTO media (owner_type, owner_id, storage_key, license, attribution) VALUES ('arena', :a, 'g1', 'user', 'x')"), {"a": dup})
    # колокольчики: 10 только на дубле, 11 на обоих
    for tg, arenas in ((10, [dup]), (11, [dup, keep])):
        for ar in arenas:
            await db_session.execute(
                text("INSERT INTO winter_subscriptions (telegram_id, kind, arena_id) VALUES (:t, 'point', :a)"), {"t": tg, "a": ar})
    await db_session.execute(text("INSERT INTO seasonal_rink_signals (arena_id, actor) VALUES (:a, 'tg:1')"), {"a": dup})
    await db_session.execute(text("INSERT INTO seasonal_moderation_items (kind, arena_id) VALUES ('new_point', :a)"), {"a": dup})

    stats = await wa.merge_points(db_session, dup, keep, admin_id=9, now=NOW)
    assert stats["marks"] == 1 and stats["photos"] == 1 and stats["media"] == 1 and stats["subs"] == 1 and stats["subs_deduped"] == 1

    q = lambda sql, **p: db_session.execute(text(sql), p)  # noqa: E731
    assert (await q("SELECT count(*) FROM seasonal_rink_marks WHERE arena_id=:a", a=keep)).scalar_one() == 1
    assert (await q("SELECT count(*) FROM seasonal_rink_photos WHERE arena_id=:a", a=keep)).scalar_one() == 1
    assert (await q("SELECT count(*) FROM media WHERE owner_type='arena' AND owner_id=:a", a=keep)).scalar_one() == 1
    assert sorted((await q("SELECT telegram_id FROM winter_subscriptions WHERE arena_id=:a", a=keep)).scalars().all()) == [10, 11]
    assert (await q("SELECT count(*) FROM winter_subscriptions WHERE arena_id=:a", a=dup)).scalar_one() == 0
    assert (await q("SELECT count(*) FROM seasonal_rink_signals WHERE arena_id=:a", a=dup)).scalar_one() == 0
    row = (await q("SELECT is_active, merged_into_arena_id FROM arenas WHERE id=:a", a=dup)).one()
    assert (row.is_active, row.merged_into_arena_id) == (False, keep)
    assert (await _state(db_session, dup)).state == "hidden"
    assert (await q("SELECT catalog_pin FROM arena_profiles WHERE arena_id=:a", a=keep)).scalar_one() == 1
    assert (await q("SELECT status FROM seasonal_moderation_items WHERE arena_id=:a", a=dup)).scalar_one() == "done"
    assert await red.lookup_redirect(db_session, cid, "minsk-katok-2") == keep
    # слитая точка больше не принимает отметок и не попадает в дубли/пачки
    with pytest.raises(wm.MarkError):
        await wm.record_mark(db_session, arena_id=dup, kind="ice", value="flooded", source="telegram", actor="tg:502", now=NOW)
    assert (await q("SELECT action FROM winter_admin_batches ORDER BY id DESC LIMIT 1")).scalar_one() == "merge"


@pytest.mark.asyncio
async def test_merge_refuses_other_city_same_point_and_repeat(db_session):
    a = await make_point(db_session, city="Минск")
    b = await make_point(db_session, city="Гродно")
    c = await make_point(db_session, city="Минск")
    with pytest.raises(wa.AdminOpError) as e:
        await wa.merge_points(db_session, a, b, admin_id=1, now=NOW)
    assert e.value.code == "other_city"
    with pytest.raises(wa.AdminOpError) as e:
        await wa.merge_points(db_session, a, a, admin_id=1, now=NOW)
    assert e.value.code == "same"
    await wa.merge_points(db_session, a, c, admin_id=1, now=NOW)
    with pytest.raises(wa.AdminOpError) as e:
        await wa.merge_points(db_session, a, c, admin_id=1, now=NOW)
    assert e.value.code == "already_merged"


@pytest.mark.asyncio
async def test_chain_merge_repoints_old_redirects(db_session):
    a = await make_point(db_session, slug="s-a")
    b = await make_point(db_session, slug="s-b")
    c = await make_point(db_session, slug="s-c")
    cid = await make_city(db_session)
    await wa.merge_points(db_session, a, b, admin_id=1, now=NOW)
    await wa.merge_points(db_session, b, c, admin_id=1, now=NOW)
    assert await red.lookup_redirect(db_session, cid, "s-a") == c
    assert await red.lookup_redirect(db_session, cid, "s-b") == c


@pytest.mark.asyncio
async def test_merge_recomputes_status_from_moved_marks(db_session):
    keep = await make_point(db_session, name="K")
    dup = await make_point(db_session, name="D")
    await make_client(db_session, 601)
    await wm.record_mark(db_session, arena_id=dup, kind="ice", value="flooded", source="telegram", actor="tg:601", telegram_id=601, now=NOW)
    await wm.record_mark(db_session, arena_id=dup, kind="ice", value="flooded", source="photo", actor="tg:602", telegram_id=602, now=NOW)
    assert (await _state(db_session, dup)).state == "flooded"
    await wa.merge_points(db_session, dup, keep, admin_id=1, now=NOW + timedelta(minutes=1))
    assert (await _state(db_session, keep)).state == "flooded"


# --- переименование и slug --------------------------------------------------------
@pytest.mark.asyncio
async def test_rename_keeps_slug_but_kind_change_moves_it_with_301(db_session):
    a = await make_point(db_session, name="Старое", city="Минск", slug="minsk-katok-77")
    cid = await make_city(db_session, "Минск")
    out = await wa.rename_point(db_session, a, name="  Новое   имя ", admin_id=1, now=NOW)
    assert out["slug"] == "minsk-katok-77" and out["old_slug"] is None
    assert (await db_session.execute(text("SELECT name FROM arenas WHERE id=:a"), {"a": a})).scalar_one() == "Новое имя"
    assert (await db_session.execute(text("SELECT name_source FROM seasonal_rinks WHERE arena_id=:a"), {"a": a})).scalar_one() == "admin"
    out = await wa.rename_point(db_session, a, kind="hockey_box", admin_id=1, now=NOW)
    assert out["old_slug"] == "minsk-katok-77" and out["slug"] == f"minsk-korobka-{a}"
    assert await red.lookup_redirect(db_session, cid, "minsk-katok-77") == a
    # вернули тип — старый адрес снова живой, редирект с него не нужен
    await wa.rename_point(db_session, a, kind="rink", admin_id=1, now=NOW)
    slug = (await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id=:a"), {"a": a})).scalar_one()
    assert slug == f"minsk-katok-{a}" and await red.lookup_redirect(db_session, cid, slug) is None
    assert await red.lookup_redirect(db_session, cid, f"minsk-korobka-{a}") == a


@pytest.mark.asyncio
async def test_change_slug_refuses_taken(db_session):
    a = await make_point(db_session, slug="one")
    await make_point(db_session, slug="two")
    with pytest.raises(red.SlugError) as e:
        await red.change_slug(db_session, a, "two")
    assert e.value.code == "taken"
