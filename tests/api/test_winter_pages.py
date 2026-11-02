"""Сайт: «Зимой в <городе>» и страница зимней точки (TASK-343, волна 2): HTML, SEO, коды ответов, sitemap."""
from __future__ import annotations

import json
import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.deps import get_session
from src.application import winter_public
from src.application.ice_city_day import invalidate_public_city_cache
from tests.application.winter_helpers import NOW, make_point

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"
CITY = "Минск"
WEEK = {"weekly": {k: [["07:00", "23:00"]] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "1")
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "x" * 40)
    monkeypatch.setenv("YANDEX_STATIC_API_KEY", "k-test")
    monkeypatch.setenv("YANDEX_MAPS_JS_API_KEY", "js-key")
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glideclub.test")
    invalidate_public_city_cache()
    yield
    invalidate_public_city_cache()


@pytest.fixture
async def client(db_session, app_use_test_db):
    async def _s():
        yield db_session

    app.dependency_overrides[get_session] = _s
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


_n = [0]


async def point(db, **kw):
    _n[0] += 1
    kw.setdefault("city", CITY)
    kw.setdefault("slug", f"minsk-{'korobka' if kw.get('kind') == 'hockey_box' else 'katok'}-{9000 + _n[0]}")
    return await make_point(db, **kw)


async def slug_of(db, aid):
    return (await db.execute(text("SELECT slug FROM arena_profiles WHERE arena_id=:a"), {"a": aid})).scalar_one()


def data_of(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="w-data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


@pytest.mark.asyncio
async def test_flag_off_pages_are_404(client, db_session, monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "0")
    invalidate_public_city_cache()
    aid = await point(db_session)
    slug = await slug_of(db_session, aid)
    assert (await client.get("/c/minsk/zimoy")).status_code == 404
    r = await client.get(f"/p/minsk/{slug}")
    assert r.status_code == 404 or "w-h1" not in r.text  # обычная страница места, не зимняя


@pytest.mark.asyncio
async def test_city_page_lists_sorted_with_honest_copy(on, client, db_session):
    await point(db_session, name="Ждём", state="waiting", hours=WEEK)
    await point(db_session, name="Залит", state="flooded", state_source="engine")
    await point(db_session, name="Закреплённая", pin=1)
    await point(db_session, name="Неточная", precision="city", lat=None, lon=None)
    await point(db_session, name="Скрытая", state="hidden")
    r = await client.get("/c/minsk/zimoy")
    assert r.status_code == 200
    html = r.text
    assert "Зимой в Минске" in html
    names = re.findall(r'<span class="w-card__name">([^<]+)</span>', html)
    assert names[:2] == ["Закреплённая", "Залит"] and "Скрытая" not in names
    assert "Прошлой зимой: " in html and "зимой 2025/26" not in html
    assert "открыто сейчас" not in html.lower() and "круглосуточно" not in html.lower()
    # неточная точка: честная подпись, без расстояния и координат в данных страницы
    assert "адрес примерный" in html and "точку уточняем" not in html
    bad = [p for p in data_of(html)["points"] if p["name"] == "Неточная"][0]
    assert bad["lat"] is None and bad["map_allowed"] is False
    assert "index, follow" in html and 'rel="canonical" href="https://glideclub.test/c/minsk/zimoy"' in html
    assert "ItemList" in html
    assert "Ждать" not in html  # кнопка подписки «рядом» называется «Подписаться» (если бот настроен)


@pytest.mark.asyncio
async def test_city_page_zero_flooded_is_start_of_season_not_a_dead_counter(on, client, db_session):
    await point(db_session, name="Первая")
    html = (await client.get("/c/minsk/zimoy")).text
    assert "Сезон открывается: ждём первую заливку" in html
    assert "залиты 0" not in html


@pytest.mark.asyncio
async def test_city_page_without_points_is_noindex_and_offers_suggest(on, client, db_session):
    await point(db_session, state="hidden")
    html = (await client.get("/c/minsk/zimoy")).text
    assert "noindex" in html and "/suggest?city=" in html


@pytest.mark.asyncio
async def test_numeric_city_ref_redirects_to_slug(on, client, db_session):
    aid = await point(db_session)
    cid = (await db_session.execute(text("SELECT city_id FROM arenas WHERE id=:a"), {"a": aid})).scalar_one()
    r = await client.get(f"/c/{cid}/zimoy")
    assert r.status_code == 301 and r.headers["location"] == "/c/minsk/zimoy"


@pytest.mark.asyncio
async def test_point_page_with_map_has_yandex_link_and_no_token_or_status_in_og(on, client, db_session):
    aid = await point(db_session, name="Коробка у школы № 54", kind="hockey_box", hours=WEEK, paid=False)
    slug = await slug_of(db_session, aid)
    r = await client.get(f"/p/minsk/{slug}")
    assert r.status_code == 200
    html = r.text
    assert "Хоккейная коробка" in html and "Коробка у школы № 54" in html
    assert "static-maps.yandex.ru/v1" in html and "Открыть в Картах" in html and "yandex.ru/maps/?pt=" in html
    assert "w-map-fb" in html  # запасная плашка на случай недоступного Яндекса
    assert "ПРОШЛОЙ ЗИМОЙ · 2025/26" in html and "Ежедневно" in html
    assert "зимой 2025/26" not in html and "таблица сезона" not in html
    assert "mark_token" not in html and not re.search(r"\d{10}\.[0-9a-f]{32}", html)
    og = re.search(r'property="og:description" content="([^"]*)"', html).group(1)
    assert "Ждём заливку" not in og and "Залит" not in og
    assert re.search(r'rel="canonical" href="https://glideclub.test/p/minsk/' + slug, html)
    assert "index, follow" in html and "openingHours" not in html
    assert "Ждём заливку" in html and "Сезон 2026/27" not in html
    assert "Уже залит" in html and "Ещё не залит" in html and "Не зальют" not in html
    assert "Ещё про людей и хоккей" not in html and "цена" not in html.split('w-kindbadge">')[1].split("</span>")[0].lower()
    assert r.headers["cache-control"].startswith("private")


@pytest.mark.asyncio
async def test_imprecise_point_page_has_no_map_no_distance_and_is_noindex(on, client, db_session):
    aid = await point(db_session, precision="city", lat=None, lon=None)
    slug = await slug_of(db_session, aid)
    html = (await client.get(f"/p/minsk/{slug}")).text
    assert "Точку на карте уточняем" in html
    assert "static-maps" not in html and "Открыть в Картах" not in html
    assert "noindex" in html


@pytest.mark.asyncio
async def test_doubtful_point_is_visible_with_banner_and_noindex(on, client, db_session):
    aid = await point(db_session)
    await db_session.execute(text("UPDATE seasonal_rink_seasons SET doubtful = true WHERE arena_id = :a"), {"a": aid})
    slug = await slug_of(db_session, aid)
    r = await client.get(f"/p/minsk/{slug}")
    assert r.status_code == 200
    assert "Возможно, точки больше нет" in r.text and "noindex" in r.text
    assert "data-w-open-sheet" not in r.text  # на спорной точке отметок не собираем


@pytest.mark.asyncio
async def test_hidden_point_is_410_with_explanation_and_exit(on, client, db_session):
    aid = await point(db_session, name="Старая коробка", state="hidden")
    slug = await slug_of(db_session, aid)
    r = await client.get(f"/p/minsk/{slug}")
    assert r.status_code == 410
    assert "больше нет в зимнем каталоге" in r.text and "/c/minsk/zimoy" in r.text and "noindex" in r.text


@pytest.mark.asyncio
async def test_old_slug_and_wrong_city_redirect_to_canonical(on, client, db_session):
    aid = await point(db_session)
    slug = await slug_of(db_session, aid)
    r = await client.get(f"/p/minsk/{slug}?x=1")
    assert r.status_code == 200
    cid = (await db_session.execute(text("SELECT city_id FROM arenas WHERE id=:a"), {"a": aid})).scalar_one()
    r2 = await client.get(f"/p/{cid}/{slug}")
    assert r2.status_code in (301, 404)


@pytest.mark.asyncio
async def test_nemiga_style_pinned_arena_keeps_its_regular_page(on, client, db_session):
    aid = await point(db_session, name="Каток на Немиге", pin=1, slug="katok-na-nemige-u-dvortsa-sporta")
    assert (await winter_public.lookup_any(db_session, aid))["own_page"] is False
    html = (await client.get("/p/minsk/katok-na-nemige-u-dvortsa-sporta")).text
    assert 'data-w-page="point"' not in html


@pytest.mark.asyncio
async def test_sitemap_has_indexable_winter_pages_only(on, client, db_session):
    good = await point(db_session, name="Хорошая", hours=WEEK, paid=False)
    vague = await point(db_session, name="Размытая", precision="city", lat=None, lon=None)
    hidden = await point(db_session, name="Скрытая", state="hidden", hours=WEEK)
    r = await client.get("/sitemap.xml")
    xml = r.text
    assert "/c/minsk/zimoy" in xml
    assert await slug_of(db_session, good) in xml
    assert await slug_of(db_session, vague) not in xml
    assert await slug_of(db_session, hidden) not in xml


@pytest.mark.asyncio
async def test_sitemap_without_flag_has_no_winter_urls(client, db_session, monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "0")
    invalidate_public_city_cache()
    aid = await point(db_session, hours=WEEK)
    xml = (await client.get("/sitemap.xml")).text
    assert "zimoy" not in xml and await slug_of(db_session, aid) not in xml


def test_indexable_rule_needs_precise_address_and_three_facts():
    base = {"map_allowed": True, "address": "ул. Тестовая 1", "kind": "rink", "is_paid": False, "doubtful": False,
            "phone": None, "hours": {"known": False}}
    assert winter_public.is_indexable(base)
    assert not winter_public.is_indexable({**base, "map_allowed": False})
    assert not winter_public.is_indexable({**base, "doubtful": True})
    assert not winter_public.is_indexable({**base, "is_paid": None, "address": ""})
    assert winter_public.is_indexable({**base, "is_paid": None, "phone": "+375291112233"})


@pytest.mark.asyncio
async def test_city_hub_has_winter_tile_only_with_flag_and_points(on, client, db_session, monkeypatch):
    await point(db_session, name="Первая")
    await point(db_session, name="Залитая", state="flooded", state_source="engine")
    html = (await client.get("/c/minsk")).text
    assert 'href="/c/minsk/zimoy"' in html and "залиты 1" in html
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "0")
    assert "/c/minsk/zimoy" not in (await client.get("/c/minsk")).text


@pytest.mark.asyncio
async def test_miniapp_season_facet_counts_winter_points_only_with_flag(on, client, db_session, monkeypatch):
    aid = await point(db_session, name="Коробка")
    await point(db_session, name="Скрытая", state="hidden")
    cid = (await db_session.execute(text("SELECT city_id FROM arenas WHERE id=:a"), {"a": aid})).scalar_one()
    f = (await client.get("/api/public/ice/arenas", params={"city_id": cid})).json()["season_facet"]
    assert f["winter_points"] == 1 and f["count"] >= 1
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "0")
    f2 = (await client.get("/api/public/ice/arenas", params={"city_id": cid})).json()["season_facet"]
    assert "winter_points" not in f2


def test_live_tags_carry_mark_time_for_js():
    from src.application import winter_page as wp

    html = wp._tags_html({"crowd": "few", "crowd_at": "2026-12-10T11:20:00+00:00", "hockey": "free", "hockey_at": None})
    assert 'data-w-live-at="2026-12-10T11:20:00+00:00"' in html and 'data-w-live-label="Мало людей"' in html
    assert "Хоккея нет</span>" in html and html.count("data-w-live-at") == 1


def test_point_page_route_is_yandex_only_and_gone_goes_to_bot():
    from src.application import winter_page as wp

    item = {"route_url": "https://yandex.ru/maps/?rtext=~1,2", "lat": 53.9, "lon": 27.5, "address": "ул. Ленина, 1", "city": "Минск"}
    html = wp._routes(item)
    assert "Яндекс Карты" in html and "google" not in html.lower()
    link = wp._gone_link({"gone": "https://t.me/bot?start=wgone_7"})
    assert "Точки больше нет? Сообщить" in link and "t.me/bot?start=wgone_7" in link
    assert wp._gone_link({}) == ""


def test_phones_on_winter_page_use_the_common_display_format():
    from src.application import winter_page as wp
    from src.shared.winter_text import phone_links

    assert phone_links("+375173647551") == [("+375 17 364-75-51", "+375173647551")]
    assert [d for d, _ in phone_links("+375291112233, +375173647551")] == ["+375 29 111-22-33", "+375 17 364-75-51"]
    html = wp._known({"phone": "+375173647551", "phone_shared": False})
    assert "+375 17 364-75-51" in html and 'href="tel:+375173647551"' in html


# --- тексты (чистые функции, без БД) ------------------------------------------------------------
def _item(**over):
    base = {
        "id": 1, "name": "Каток, ул. Плеханова, 70", "kind": "rink", "state": "waiting", "is_paid": False, "phone": None,
        "hours": {"known": True, "summary": "Ежедневно 07:00–23:00", "label": "зимой 2025/26", "season": "2025/26"},
    }
    base.update(over)
    return base


def test_card_meta_prefixes_last_winter_and_drops_unknowns():
    from src.application import winter_page as wp

    assert wp.card_meta(_item()) == "Прошлой зимой: ежедневно 07:00–23:00 · бесплатно"
    unknown = _item(is_paid=None, hours={"known": False, "season": "2025/26"})
    assert wp.card_meta(unknown) == ""
    assert wp.card_meta({**unknown, "phone": "+375 17 000-00-00"}) == "Часы уточняйте по телефону"
    assert wp.card_meta(_item(locating=True)).endswith(" · адрес примерный")


def test_card_title_drops_kind_prefix_only():
    from src.application import winter_page as wp

    assert wp.card_title(_item()) == "ул. Плеханова, 70"
    assert wp.card_title(_item(name="Коробка, пр. Рокоссовского, 128")) == "пр. Рокоссовского, 128"
    assert wp.card_title(_item(name="Каток Юность")) == "Каток Юность"


def test_checked_line_dates_and_dispute_note():
    from datetime import datetime, timezone

    from src.application import winter_page as wp

    now = datetime(2026, 12, 10, 12, tzinfo=timezone.utc)
    flooded = _item(state="flooded", checked_by="admin", state_at="2026-11-02T10:00:00+00:00")
    assert wp.checked_line(flooded, now) == "Заливку подтвердили 2 ноября"
    assert wp.checked_line({**flooded, "state": "stale"}, now) == "Проверено 2 ноября"
    assert wp.checked_line({**flooded, "state_at": "2025-11-02T10:00:00+00:00", "state": "closed"}, now) == "Проверено 2 ноября 2025"
    assert wp.dispute_note({**flooded, "dispute": True}) == "Есть отметки «не залит» · проверяем"
    assert wp.dispute_note({**flooded, "dispute": True, "state": "waiting"}) == ""


def test_live_tags_carry_age_and_expire_after_two_hours():
    from datetime import datetime, timezone

    from src.application import winter_page as wp

    now = datetime(2026, 12, 10, 12, tzinfo=timezone.utc)
    html = wp._tags_html(
        _item(state="flooded", crowd="few", crowd_at="2026-12-10T11:30:00+00:00", hockey="free", hockey_at="2026-12-10T09:00:00+00:00"),
        now,
    )
    assert "Мало людей · 30 мин назад" in html and "Хоккея нет" not in html


def test_facts_block_splits_last_winter_from_phone_and_source():
    from src.application import winter_page as wp

    html = wp._known(_item(phone="+375 17 000-00-00", source_url="https://www.minsksport.by/x"))
    assert "ПРОШЛОЙ ЗИМОЙ · 2025/26" in html
    assert html.index("Часы") < html.index("Цена") < html.index("Телефон") < html.index("Источник")
    assert "minsksport.by</a></dd>" in html and "таблица сезона" not in html and "зимой 2025/26" not in html
