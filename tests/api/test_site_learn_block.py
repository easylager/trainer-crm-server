"""TASK-354: единый блок «Учиться с тренером» на сайте — город, «Покататься», каток, «С клюшкой»."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from src.application.site_learn_block import learn_block, render_learn_block
from tests.api.test_public_arenas import _insert_arena
from tests.api.test_public_place_page import _add_future_session, _place
from tests.api.test_site_trainer_catalog import _city, _tab


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")


def _block(html: str) -> str:
    m = re.search(r'<section class="b-sec b-learn-sec" id="learn">(.*?)</section>', html, re.S)
    assert m, "нет блока «Учиться с тренером»"
    return m.group(1).replace("\u00a0", " ")


def _plain(text_: str) -> str:
    return text_.replace("\u00a0", " ")


def _line(block: str) -> str:
    m = re.search(r'<p class="b-learn__line">(.*?)</p>', block, re.S)
    assert m, "нет строки блока"
    return m.group(1).replace("\u00a0", " ")


def _go(block: str) -> str:
    m = re.search(r'<a class="b-learn__go" href="([^"]*)"', block)
    assert m
    return m.group(1).replace("&amp;", "&")


async def _extra_arena(db_session, city_id: int) -> dict:
    """Ещё один каток города без тренеров."""
    arena_id = await _insert_arena(db_session, city_id, name=f"Пустой каток {uuid.uuid4().hex[:4]}")
    slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
    ).scalar_one()
    city_name = (await db_session.execute(text("SELECT name FROM cities WHERE id = :id"), {"id": city_id})).scalar_one()
    await db_session.commit()
    return {"arena_id": arena_id, "path": f"/p/{city_slug(city_name)}/{slug}"}


async def _arena_path(db_session, arena_id: int, city_name: str) -> str:
    slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
    ).scalar_one()
    return f"/p/{city_slug(city_name)}/{slug}"


# ── чистая функция ───────────────────────────────────────────────────


def _trainer(i: int, *, photo: str | None = None, price: int | None = 4500, arenas=(), win=None, dirs=("zero",)):
    svc = {"service_id": 1, "currency_code": "BYN", "price_cents": price, "price_tiers": []}
    return {
        "id": i,
        "order": i,
        "name": f"Тренер {i}",
        "initial": "Т",
        "photo_url": photo,
        "path": f"/t/{i}",
        "arenas": [{"id": a, "name": f"К{a}", "city_name": "Минск", "slug": None} for a in arenas],
        "services_by_dir": {d: [svc] for d in dirs},
        "windows": [win] if win else [],
        "can_book": bool(win),
    }


def _data(trainers) -> dict:
    return {"city": {"id": 1, "name": "Минск"}, "trainers": trainers, "arenas": {}}


def test_skate_line_numbers_and_words() -> None:
    four = learn_block(_data([_trainer(i) for i in range(4)]), "skate")
    assert _plain(four.line) == "Первый раз на льду? Четыре тренера учат с нуля — детей и взрослых. От 45 BYN."
    assert four.href == "/c/minsk/trenery/s-nulya" and four.count == 4 and not four.chips
    one = learn_block(_data([_trainer(1)]), "skate")
    assert _plain(one.line).startswith("Первый раз на льду? Один тренер учит с нуля")
    many = learn_block(_data([_trainer(i) for i in range(21)]), "skate")
    assert "21 тренер учит с нуля" in _plain(many.line)
    five = learn_block(_data([_trainer(i) for i in range(5)]), "skate")
    assert "5 тренеров учат с нуля" in _plain(five.line)
    # Нет цены — без «От …»; нет тренеров направления — нет блока.
    assert learn_block(_data([_trainer(1, price=None, arenas=(7,))]), "skate").line.endswith("взрослых.")
    assert learn_block(_data([_trainer(1, dirs=("fig",))]), "skate") is None
    assert learn_block(_data([]), "city") is None


def test_city_line_time_only_if_present_and_faces() -> None:
    win = {"day": "сегодня", "time": "17:15", "starts_at": "2026-11-07T17:15:00+03:00", "arena_id": None}
    later = {"day": "сб", "time": "10:00", "starts_at": "2026-11-09T10:00:00+03:00", "arena_id": None}
    rows = [_trainer(i, photo=f"/p{i}.jpg" if i % 2 else None) for i in range(1, 6)]
    rows[3]["windows"], rows[4]["windows"] = [later], [win]
    b = learn_block(_data(rows), "city")
    assert _plain(b.line) == "От 45 BYN за занятие. Ближайшее свободное время — сегодня, 17:15."
    assert len(b.faces) == 4 and {f[0] for f in b.faces} == {"/p5.jpg", "/p1.jpg", None}
    assert b.chips == ()  # одно направление — чипы не нужны
    no_win = learn_block(_data([_trainer(1)]), "city")
    assert "Ближайшее" not in no_win.line and _plain(no_win.line) == "От 45 BYN за занятие."
    # Нет ни цены, ни окна — строки нет вовсе, ничего не выдумываем.
    assert learn_block(_data([_trainer(1, price=None, arenas=(1,))]), "city").line == ""
    html = render_learn_block(b)
    assert "b-learn__mono" in html and "<img" in html and "5 тренеров" in _plain(html) and "Выбрать тренера" in html


def test_arena_lines() -> None:
    win = {"day": "завтра", "time": "09:00", "starts_at": "2026-11-08T09:00:00+03:00", "arena_id": 7}
    rows = [_trainer(1, arenas=(7,), win=win), _trainer(2, arenas=(7, 8)), _trainer(3, arenas=(8,))]
    data = {**_data(rows), "arenas": {7: {}, 8: {}}}
    two = learn_block(data, "arena", arena_id=7)
    assert _plain(two.line) == "На этом катке занимаются 2 тренера. Ближайшее свободное время — завтра, 09:00."
    assert two.href == "/c/minsk/trenery?arena=7" and two.count == 2
    one = learn_block(data, "arena", arena_id=8)
    assert _plain(one.line) == "На этом катке занимаются 2 тренера."
    assert _plain(learn_block(_data([_trainer(1, arenas=(7,))]), "arena", arena_id=7).line).startswith("На этом катке занимается 1 тренер.")
    none = learn_block(data, "arena", arena_id=99)
    assert _plain(none.line) == "На этом катке тренеров пока нет. В Минске — 3, от 45 BYN за занятие."
    assert none.href == "/c/minsk/trenery" and none.count == 3


# ── страницы ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_city_page_block_numbers_match_catalog_and_old_list_is_gone(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        await _add_future_session(db_session, c["arena_id"], days_ahead=1, starts_at_local="19:30")
        html = (await client.get(f"/c/{c['slug']}")).text
        catalog = (await client.get(f"/c/{c['slug']}/trenery")).text
    block = _block(html)
    base = f"/c/{c['slug']}/trenery"
    assert "Учиться с тренером" in block and "Выбрать тренера" in block and _go(block) == base
    # Цифры — те же, что в каталоге: «2 тренера», «от 45 BYN», вкладки с числами.
    assert "2 тренера" in _plain(block) and _tab(catalog, "Все") == "2"
    assert "от <b>45 BYN</b> за занятие" in _plain(catalog) and _line(block).startswith("От 45 BYN за занятие.")
    assert re.search(r"Ближайшее свободное время — [^.]+, \d\d:\d\d\.$", _line(block))
    assert "окно" not in block.lower()
    # Чипы — только вкладки с ненулевыми числами; ведут на направление.
    chips = re.findall(r'<a href="([^"]*)">([^<]*)</a>', re.search(r'<nav class="b-learn__chips".*?</nav>', block, re.S).group(0))
    assert chips == [(f"{base}/s-nulya", "С нуля"), (f"{base}/uzhe-katayus", "Уже катаюсь"), (f"{base}/s-klyushkoy", "С клюшкой")]
    assert "Фигурное" not in block
    # Блок ведёт только в каталог — не в Telegram.
    assert "t.me" not in block and "startapp" not in block and "tg-out" not in block
    # Старый нижний список «Тренеры» и строка «Тренеры · N» ушли; вход для тренера остался.
    assert 'id="trainers"' not in html and "b-row--coach" not in html and "Все тренеры" not in html
    assert 'class="b-coach' in html and "/trainers?utm_source=glide&amp;utm_medium=city_hub" in html
    assert html.count('id="learn"') == 1


@pytest.mark.asyncio
async def test_city_page_block_goes_right_after_upcoming_ice(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        await _add_future_session(db_session, c["arena_id"], days_ahead=1, starts_at_local="19:30")
        html = (await client.get(f"/c/{c['slug']}")).text
    assert html.index('id="learn"') < html.index('class="b-coach')
    if "Чем займёмся?" in html:
        routes = html[html.index("Чем займёмся?") :]
        assert html.index('id="learn"') < html.index("Чем займёмся?")
        # Пункт меню — не второй блок; «Тренеры · N» нет.
        assert f'href="/c/{c["slug"]}/trenery"' in routes and "Учиться с тренером" in routes


@pytest.mark.asyncio
async def test_city_without_trainers_has_no_block_or_menu_row_only_coach_entry(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await _add_future_session(db_session, place["arena_id"], days_ahead=1, starts_at_local="19:30")
    slug = city_slug(place["city_name"])
    async with _client() as client:
        city = (await client.get(f"/c/{slug}")).text
        rink = (await client.get(place["path"])).text
        skate = (await client.get(f"/c/{slug}?t=ice")).text
        ohm = (await client.get(f"/c/{slug}?kind=ohm")).text
    for page in (city, rink, skate, ohm):
        assert 'id="learn"' not in page and "Учиться с тренером" not in page and "Выбрать тренера" not in page
    assert 'class="b-coach' in city and "/trenery" not in city
    assert "Станьте первым тренером на странице этого катка" in rink


@pytest.mark.asyncio
async def test_skate_and_hockey_pages(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        slug = c["slug"]
        skate = (await client.get(f"/c/{slug}?t=ice")).text
        ohm = (await client.get(f"/c/{slug}?kind=ohm")).text
        rental = (await client.get(f"/c/{slug}?svc=rental")).text
        centers = (await client.get(f"/c/{slug}?kind=ohm&seg=centers")).text
        shops = (await client.get(f"/c/{slug}?t=shop")).text
    base = f"/c/{slug}/trenery"
    s = _block(skate)
    assert _line(s) == "Первый раз на льду? Два тренера учат с нуля — детей и взрослых. От 45 BYN."
    assert _go(s) == f"{base}/s-nulya" and "b-learn__chips" not in s
    h = _block(ohm)
    assert _line(h) == "Хоккейное катание: стойка, ход и торможение. 1 тренер, от 50 BYN."
    assert _go(h) == f"{base}/s-klyushkoy" and "b-learn__chips" not in h and "2 тренера" not in h
    for page in (rental, centers, shops):
        assert 'id="learn"' not in page
    # Блок внизу списка, после карточек.
    assert skate.index('id="learn"') > skate.index("data-glide-session-list-root")


@pytest.mark.asyncio
async def test_hockey_page_without_hockey_trainers_has_no_block(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        await db_session.execute(text("DELETE FROM trainer_services WHERE service_id IN (4, 6)"))
        await db_session.commit()
        ohm = (await client.get(f"/c/{c['slug']}?kind=ohm")).text
        skate = (await client.get(f"/c/{c['slug']}?t=ice")).text
    assert 'id="learn"' not in ohm and 'id="learn"' in skate


@pytest.mark.asyncio
async def test_rink_page_block_with_and_without_trainers(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        await _add_future_session(db_session, c["arena_id"], days_ahead=1, starts_at_local="19:30")
        empty = await _extra_arena(db_session, c["city_id"])
        other_path = await _arena_path(db_session, c["other_arena"], c["city_name"])
        with_trainers = (await client.get(c["path"])).text
        one_trainer = (await client.get(other_path)).text
        no_trainers = (await client.get(empty["path"])).text
    base = f"/c/{c['slug']}/trenery"
    b = _block(with_trainers)
    assert _line(b).startswith("На этом катке занимаются 2 тренера.")
    assert re.search(r"Ближайшее свободное время — [^.]+, \d\d:\d\d\.$", _line(b))
    assert _go(b) == f"{base}?arena={c['arena_id']}" and "b-learn__chips" not in b
    # После расписания, не перебивая выбор сеанса; старый список тренеров ушёл.
    assert with_trainers.index('id="schedule"') < with_trainers.index('id="learn"')
    assert "b-row--coach" not in with_trainers and c["names"]["A"] not in with_trainers
    assert "Здесь работают" not in with_trainers
    # Один тренер на катке; окна у него нет — строки про время нет.
    o = _block(one_trainer)
    assert _line(o) == "На этом катке занимается 1 тренер." and _go(o) == f"{base}?arena={c['other_arena']}"
    # Каток без тренеров — строка про город, цель — весь город.
    n = _block(no_trainers)
    assert re.fullmatch(r"На этом катке тренеров пока нет\. В [^—]+ — 2, от 45 BYN за занятие\.", _line(n))
    assert _go(n) == base and "t.me" not in n and "startapp" not in n


@pytest.mark.asyncio
async def test_rink_in_city_without_trainers_and_shop_have_no_block(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    shop = await _place(db_session, venue_type="shop")
    async with _client() as client:
        assert 'id="learn"' not in (await client.get(place["path"])).text
        assert 'id="learn"' not in (await client.get(shop["path"])).text
