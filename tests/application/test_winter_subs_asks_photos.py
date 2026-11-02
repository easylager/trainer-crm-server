"""Подписки, рассылка, вопрос «Были?», фото (TASK-343: N*, Q*, F*)."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application import winter_asks as wa
from src.application import winter_marks as wm
from src.application import winter_photos as wp
from src.application import winter_subscriptions as wsub
from tests.application.winter_helpers import NOW, make_client, make_point

DAY = datetime(2026, 12, 10, 9, 0, tzinfo=timezone.utc)  # 12:00 Минск


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "1")


async def flood(db, aid, now=DAY - timedelta(minutes=10)):
    await wm.set_state_admin(db, aid, "flooded", admin_id=1, now=now)


class Sink:
    def __init__(self, result="ok"):
        self.sent, self.result, self.buttons = [], result, []

    async def __call__(self, tg, text_, buttons, ids):
        self.sent.append((tg, text_, ids))
        self.buttons = buttons
        return self.result


@pytest.mark.asyncio
async def test_near_without_location_is_refused_and_radius_clamped(db_session):
    with pytest.raises(wsub.SubscriptionError):
        await wsub.subscribe_near(db_session, 1, None, None)
    assert (await wsub.subscribe_near(db_session, 1, 53.9, 27.5, 99999))["radius_m"] == 5000


@pytest.mark.asyncio
async def test_near_and_point_dedupe_one_message_and_daily_cap(db_session):
    a = await make_point(db_session, name="A", lat=53.9, lon=27.56)
    b = await make_point(db_session, name="B", lat=53.9005, lon=27.5605)
    far = await make_point(db_session, name="Far", lat=54.5, lon=28.0)
    await wsub.subscribe_near(db_session, 10, 53.9, 27.56)
    await wsub.subscribe_point(db_session, 10, a)
    await wsub.subscribe_near(db_session, 11, 53.9, 27.56)
    for p in (a, b, far):
        await flood(db_session, p)
    assert await wsub.fan_out_events(db_session, DAY) == 4  # 10: a(point)+b(near); 11: a+b; far не попал
    sink = Sink()
    stats = await wsub.deliver_pending(db_session, DAY, sink)
    assert stats["sent"] == 2 and len(sink.sent) == 2  # одно сообщение-сводка на человека
    assert all(len(ids) == 2 for _, _, ids in sink.sent)
    # второй повод в тот же день: обычный подписчик ждёт, колокольчик обходит лимит
    c = await make_point(db_session, name="C", lat=53.9, lon=27.5602)
    await wsub.subscribe_point(db_session, 10, c)
    await flood(db_session, c, DAY + timedelta(minutes=1))
    later = DAY + timedelta(minutes=30)
    await wsub.fan_out_events(db_session, later)
    sink2 = Sink()
    stats = await wsub.deliver_pending(db_session, later, sink2)
    assert [s[0] for s in sink2.sent] == [10] and stats["held"] == 1


@pytest.mark.asyncio
async def test_event_younger_than_5_minutes_is_coalesced_and_no_flood_no_mail(db_session):
    a = await make_point(db_session, lat=53.9, lon=27.56)
    await wsub.subscribe_point(db_session, 5, a)
    await flood(db_session, a, DAY - timedelta(minutes=2))
    assert await wsub.fan_out_events(db_session, DAY) == 0
    # откатилась до рассылки
    await db_session.execute(text("UPDATE seasonal_rink_seasons SET state='waiting' WHERE arena_id=:a"), {"a": a})
    assert await wsub.fan_out_events(db_session, DAY + timedelta(minutes=10)) == 0
    assert (await wsub.deliver_pending(db_session, DAY + timedelta(minutes=10), Sink()))["sent"] == 0


@pytest.mark.asyncio
async def test_imprecise_point_never_in_radius_but_bell_works(db_session):
    a = await make_point(db_session, precision="city", lat=53.9, lon=27.56)
    await wsub.subscribe_near(db_session, 1, 53.9, 27.56)
    await wsub.subscribe_point(db_session, 2, a)
    await flood(db_session, a)
    assert await wsub.fan_out_events(db_session, DAY) == 1


@pytest.mark.asyncio
async def test_dead_chat_deactivates_and_unsubscribe_is_idempotent(db_session):
    a = await make_point(db_session)
    await wsub.subscribe_point(db_session, 3, a)
    await flood(db_session, a)
    await wsub.fan_out_events(db_session, DAY)
    stats = await wsub.deliver_pending(db_session, DAY, Sink("dead"))
    assert stats["dead"] == 1 and await wsub.list_subscriptions(db_session, 3) == []
    await wsub.subscribe_point(db_session, 3, a)
    assert await wsub.unsubscribe(db_session, 3) == 1
    assert await wsub.unsubscribe(db_session, 3) == 0


@pytest.mark.asyncio
async def test_kill_switch_and_quiet_hours(db_session, monkeypatch):
    a = await make_point(db_session)
    await wsub.subscribe_point(db_session, 4, a)
    await flood(db_session, a)
    await wsub.fan_out_events(db_session, DAY)
    night = datetime(2026, 12, 10, 1, 0, tzinfo=timezone.utc)  # 04:00 Минск
    assert (await wsub.deliver_pending(db_session, night, Sink()))["sent"] == 0
    monkeypatch.setenv("WINTER_BROADCAST_ENABLED", "0")
    assert (await wsub.deliver_pending(db_session, DAY, Sink()))["sent"] == 0
    monkeypatch.setenv("WINTER_BROADCAST_ENABLED", "1")
    assert (await wsub.deliver_pending(db_session, DAY, Sink()))["sent"] == 1


@pytest.mark.asyncio
async def test_ask_only_after_route_window_gap_and_pause(db_session):
    a = await make_point(db_session)
    now = datetime(2026, 12, 10, 21, 0, tzinfo=timezone.utc)  # 00:00 Минск
    assert await wa.schedule_ask(db_session, 7, a, now)
    assert not await wa.schedule_ask(db_session, 7, a, now)  # одна на точку
    due = (await db_session.execute(text("SELECT due_at FROM winter_asks WHERE telegram_id=7"))).scalar_one()
    assert due.astimezone(wa.MINSK).hour == 10  # ночью не будим
    assert await wa.due_asks(db_session, now + timedelta(hours=1)) == []  # ещё рано
    got = await wa.due_asks(db_session, due)
    assert len(got) == 1
    # игнор дважды подряд -> пауза 14 дней
    b = await make_point(db_session, name="B")
    await db_session.execute(text("UPDATE winter_user_prefs SET last_ask_at=NULL WHERE telegram_id=7"))
    await wa.schedule_ask(db_session, 7, b, due + timedelta(days=4))  # pending-вопроса нет (прошлый asked) -> можно
    await wa.expire_ignored(db_session, due + timedelta(days=3))
    c = await make_point(db_session, name="C")
    await wa.schedule_ask(db_session, 7, c, due + timedelta(days=4))
    await db_session.execute(text("UPDATE winter_asks SET status='asked', asked_at=:t WHERE telegram_id=7 AND status='pending'"), {"t": due})
    await wa.expire_ignored(db_session, due + timedelta(days=5))
    paused = (await db_session.execute(text("SELECT paused_until FROM winter_user_prefs WHERE telegram_id=7"))).scalar_one()
    assert paused is not None


@pytest.mark.asyncio
async def test_ask_answers_weight_half_not_been_and_stop(db_session):
    a = await make_point(db_session)
    await wa.schedule_ask(db_session, 8, a, NOW)
    ask = (await db_session.execute(text("SELECT id FROM winter_asks WHERE telegram_id=8"))).scalar_one()
    assert await wa.answer_ask(db_session, ask, 8, "flooded", NOW + timedelta(days=1)) == "ok"
    w = (await db_session.execute(text("SELECT weight FROM seasonal_rink_marks WHERE actor='tg:8'"))).scalar_one()
    assert w == 0.5
    assert await wa.answer_ask(db_session, ask, 8, "flooded", NOW) == "already"
    b = await make_point(db_session, name="B")
    await wa.schedule_ask(db_session, 8, b, NOW)
    ask2 = (await db_session.execute(text("SELECT id FROM winter_asks WHERE arena_id=:a"), {"a": b})).scalar_one()
    assert await wa.answer_ask(db_session, ask2, 8, "not_been", NOW) == "not_been"
    assert not await wa.schedule_ask(db_session, 8, b, NOW)  # по этой точке больше не спросим
    assert await wa.answer_ask(db_session, ask2, 8, "stop", NOW) == "stopped"
    c = await make_point(db_session, name="C")
    assert not await wa.schedule_ask(db_session, 8, c, NOW)


def _jpeg(color=(10, 120, 200), size=(40, 30), exif=True):
    from PIL import Image

    img = Image.new("RGB", size, color)
    for x in range(size[0]):
        img.putpixel((x, x % size[1]), (255 - x, x * 3 % 255, 7))
    buf = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "TestCam"
        ex[0x8825] = {1: "N"}
        img.save(buf, "JPEG", exif=ex)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


def test_sanitize_strips_exif_and_rejects_junk():
    from PIL import Image

    raw = _jpeg()
    assert Image.open(io.BytesIO(raw)).getexif()
    clean = wp.sanitize_image(raw)
    assert not Image.open(io.BytesIO(clean)).getexif()
    with pytest.raises(wp.PhotoError) as e:
        wp.sanitize_image(b"GIF89a-not-really")
    assert e.value.code == "not_image"
    with pytest.raises(wp.PhotoError) as e:
        wp.sanitize_image(b"0" * (wp.MAX_BYTES + 1))
    assert e.value.code == "too_large"


@pytest.fixture
def fake_s3(monkeypatch):
    store = {}

    def up(arena_id, body, ct):
        key = f"winter-photos/{arena_id}/{len(store)}"
        store[key] = body
        return {"storage_key": key, "variants": {"card": key}, "width": 1, "height": 1}

    monkeypatch.setattr(wp.s3, "upload_winter_photo", up)
    monkeypatch.setattr(wp.s3, "get_file", lambda key, allowed_prefixes=(): (store[key], "image/jpeg") if key in store else None)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(wp, "_publish_to_arena_media", noop)
    return store


@pytest.mark.asyncio
async def test_photo_needs_session_dedupes_limits_and_goes_to_admin(db_session, fake_s3):
    a = await make_point(db_session)
    with pytest.raises(wp.PhotoError) as e:
        await wp.add_photo(db_session, 20, _jpeg(), NOW)
    assert e.value.code == "no_session"
    assert await wp.begin_session(db_session, 20, a, NOW)
    pid = await wp.add_photo(db_session, 20, _jpeg(), NOW)
    with pytest.raises(wp.PhotoError) as e:
        await wp.add_photo(db_session, 20, _jpeg(), NOW)  # тот же кадр
    assert e.value.code == "duplicate"
    for i in range(2):
        await wp.add_photo(db_session, 20, _jpeg(color=(i * 50, 5, 5), size=(41 + i, 30)), NOW)
    with pytest.raises(wp.PhotoError) as e:
        await wp.add_photo(db_session, 20, _jpeg(color=(1, 99, 3), size=(50, 33)), NOW)
    assert e.value.code == "limit"
    with pytest.raises(wp.PhotoError):  # сессия 30 мин истекла
        await wp.add_photo(db_session, 20, _jpeg(color=(9, 9, 9), size=(60, 20)), NOW + timedelta(minutes=31))
    q = (await db_session.execute(text("SELECT count(*) FROM seasonal_moderation_items WHERE kind='photo_first' AND status='open'"))).scalar_one()
    assert q == 3
    pub = (await db_session.execute(text("SELECT published, blurred FROM seasonal_rink_photos WHERE id=:p"), {"p": pid})).one()
    assert tuple(pub) == (False, False)  # молчание админа ничего не публикует


@pytest.mark.asyncio
async def test_photo_claim_weighs_half_until_accept_then_two(db_session, fake_s3):
    a = await make_point(db_session)
    await wp.begin_session(db_session, 21, a, NOW)
    pid = await wp.add_photo(db_session, 21, _jpeg(), NOW)
    assert await wp.set_ice_claim(db_session, pid, 21, True, NOW)
    st = (await db_session.execute(text("SELECT state FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": a})).scalar_one()
    assert st == "waiting"
    assert await wp.decide(db_session, pid, "accept", 1, NOW) == "accepted"
    assert await wp.decide(db_session, pid, "accept", 1, NOW) == "already"
    st = (await db_session.execute(text("SELECT state, pending_confirm FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": a})).one()
    assert tuple(st) == ("waiting", True)  # 2 балла фото набраны, но «залит» ставит только админ


@pytest.mark.asyncio
async def test_photo_reject_and_wrong_place_remove_the_mark(db_session, fake_s3):
    a = await make_point(db_session)
    await wp.begin_session(db_session, 22, a, NOW)
    pid = await wp.add_photo(db_session, 22, _jpeg(), NOW)
    await wp.set_ice_claim(db_session, pid, 22, True, NOW)
    assert await wp.decide(db_session, pid, "wrong_place", 1, NOW) == "wrong_place"
    assert (await db_session.execute(text("SELECT count(*) FROM seasonal_rink_marks WHERE photo_id=:p"), {"p": pid})).scalar_one() == 0


@pytest.mark.asyncio
async def test_photo_reports_hide_and_ban(db_session, fake_s3):
    a = await make_point(db_session)
    await wp.begin_session(db_session, 23, a, NOW)
    pid = await wp.add_photo(db_session, 23, _jpeg(), NOW)
    await wp.decide(db_session, pid, "accept", 1, NOW)
    await wp.report_photo(db_session, pid, "site:a")
    await wp.report_photo(db_session, pid, "site:a")  # тот же человек
    assert (await db_session.execute(text("SELECT published FROM seasonal_rink_photos WHERE id=:p"), {"p": pid})).scalar_one() is True
    await wp.report_photo(db_session, pid, "site:b")
    assert (await db_session.execute(text("SELECT published FROM seasonal_rink_photos WHERE id=:p"), {"p": pid})).scalar_one() is False
    await wp.ban_author(db_session, 23)
    assert not await wp.begin_session(db_session, 23, a, NOW)


@pytest.mark.asyncio
async def test_queue_health_alarm(db_session, fake_s3):
    a = await make_point(db_session)
    await wp.begin_session(db_session, 24, a, NOW)
    await wp.add_photo(db_session, 24, _jpeg(), NOW)
    assert (await wp.queue_health(db_session, NOW + timedelta(hours=1)))["alarm"] is False
    assert (await wp.queue_health(db_session, NOW + timedelta(hours=25)))["alarm"] is True


# --- текст и кнопки сообщения «залили» -------------------------------------------------
from datetime import timezone as _tz  # noqa: E402

_NOW = datetime(2026, 12, 10, 18, 50, tzinfo=_tz(timedelta(hours=3)))
_AT = datetime(2026, 12, 10, 18, 40, tzinfo=_tz(timedelta(hours=3)))
_P = {"id": 1, "name": "Каток, Парк Горького", "district": "Центр", "flooded_at": _AT,
      "meta": "Прошлой зимой: ежедневно 07:00–23:00 · бесплатно",
      "route_url": "https://yandex.ru/maps/?rtext=~1,2&rtt=auto", "page_url": "https://x.by/p/minsk/a"}


def test_compose_single_full():
    text_, rows = wsub.compose_flood_message([_P], _NOW)
    assert text_ == "Каток, Парк Горького — лёд залит\nПодтвердили сегодня в 18:40.\nПрошлой зимой: ежедневно 07:00–23:00 · бесплатно"
    assert rows == [[("Маршрут", _P["route_url"]), ("Открыть точку", _P["page_url"])]]


def test_compose_single_without_meta_and_urls():
    text_, rows = wsub.compose_flood_message([{**_P, "meta": "", "route_url": None, "page_url": None}], _NOW)
    assert text_.splitlines() == ["Каток, Парк Горького — лёд залит", "Подтвердили сегодня в 18:40."]
    assert rows == []
    _, rows = wsub.compose_flood_message([{**_P, "page_url": None}], _NOW)
    assert rows == [[("Маршрут", _P["route_url"])]]


def test_compose_time_formats():
    day = lambda d: _AT - timedelta(days=d)  # noqa: E731
    assert wsub.confirmed_phrase([day(0)], _NOW) == "Подтвердили сегодня в 18:40."
    assert wsub.confirmed_phrase([day(1)], _NOW) == "Подтвердили вчера в 18:40."
    assert wsub.confirmed_phrase([day(3)], _NOW) == "Подтвердили 7 декабря в 18:40."
    assert wsub.confirmed_phrase([day(1), day(0)], _NOW) == "Подтвердили сегодня."  # разные сутки
    assert wsub.confirmed_phrase([None], _NOW) == ""
    # UTC-момент пересекает полночь по Минску
    late = datetime(2026, 12, 9, 22, 30, tzinfo=_tz.utc)  # 01:30 10 декабря по Минску
    assert wsub.confirmed_phrase([late], _NOW) == "Подтвердили сегодня в 01:30."


def test_compose_multi():
    pts = [{**_P, "id": i, "name": n, "page_url": f"https://x.by/p/minsk/{i}"} for i, n in
           enumerate(["Каток, Парк Горького", "Коробка, Двор очень длинного названия номер семь", "Лидский"])]
    pts[2]["district"] = None
    text_, rows = wsub.compose_flood_message(pts, _NOW)
    assert text_ == ("Лёд залит на 3 точках рядом:\n— Каток, Парк Горького (Центр)\n"
                     "— Коробка, Двор очень длинного названия номер семь (Центр)\n— Лидский\nПодтвердили сегодня в 18:40.")
    assert [r[0][0] for r in rows] == ["Парк Горького", "Двор очень длинного названия…", "Лидский"]
    assert all(len(r) == 1 for r in rows)
    many, rows = wsub.compose_flood_message([{**_P, "id": i} for i in range(10)], _NOW)
    assert many.count("\n— ") == 8 and len(rows) == 8


@pytest.mark.asyncio
async def test_delivery_builds_buttons_from_site_data(db_session, monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    a = await make_point(db_session, name="Каток тест", lat=53.9, lon=27.56, hours={"weekly": {"mon": [["07:00", "23:00"]]}})
    await wsub.subscribe_point(db_session, 21, a)
    await flood(db_session, a)
    await wsub.fan_out_events(db_session, DAY)
    sink = Sink()
    await wsub.deliver_pending(db_session, DAY, sink)
    body = sink.sent[0][1]
    assert body.startswith("Каток тест — лёд залит\nПодтвердили сегодня в ")
    labels = [(label, u) for row in sink.buttons for label, u in row]
    assert labels[0][0] == "Маршрут" and labels[0][1].startswith("https://yandex.ru/maps/")
    assert labels[1][0] == "Открыть точку" and labels[1][1].startswith("https://glide.example/p/")


@pytest.mark.asyncio
async def test_delivery_without_public_base_has_no_page_button(db_session, monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "http://localhost:8000")
    a = await make_point(db_session, name="Каток тест", lat=53.9, lon=27.56)
    await wsub.subscribe_point(db_session, 22, a)
    await flood(db_session, a)
    await wsub.fan_out_events(db_session, DAY)
    sink = Sink()
    await wsub.deliver_pending(db_session, DAY, sink)
    assert [label for row in sink.buttons for label, _ in row] == ["Маршрут"]
