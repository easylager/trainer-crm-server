"""TASK-355: каталог тренеров ``/c/{city}/trenery[/{направление}]`` — вкладки, правило показа, фильтр катка."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from src.application.site_trainer_catalog import (
    _price_html,
    booking_url,
    ALL,
    direction_by_slug,
    direction_min_price,
    education_line,
    is_listed,
    min_price_by_direction,
    price_tiers,
    service_direction,
)
from src.application.site_trainer_page import trainer_path
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ONLINE
from tests.api.test_arena_trainer_windows import _slot
from tests.api.test_public_arenas import _insert_arena
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on
from tests.api.test_webapp_client_miniapp_integration import _ensure_trainer_subscription_tier


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")


# ── чистые функции ───────────────────────────────────────────────────


def test_directions_map_public_services_hockey_is_two_services() -> None:
    assert direction_by_slug(None) is ALL and direction_by_slug("") is ALL
    assert direction_by_slug("s-nulya").service_ids == (1,)
    assert direction_by_slug("uzhe-katayus").service_ids == (2,)
    assert direction_by_slug("figurnoe").service_ids == (3,)
    assert direction_by_slug("s-klyushkoy").service_ids == (4, 6)
    assert direction_by_slug("roliki") is None
    assert service_direction({"service_id": 6}) == "hock"
    # Ролики, ОФП/СФП и своя услуга тренера без привязки — не вкладки.
    assert service_direction({"service_id": 5}) is None
    assert service_direction({"service_id": 7}) is None
    assert service_direction({"service_id": 11}) is None
    assert service_direction({"service_id": 11, "direction_service_id": None}) is None
    # TASK-353: админ привязал свою услугу к «Фигурному» — она во вкладке направления.
    assert service_direction({"service_id": 11, "direction_service_id": 3}) == direction_by_slug("figurnoe").key
    assert service_direction({"service_id": 11, "direction_service_id": 5}) is None


def test_catalog_links_carry_site_catalog_source() -> None:
    from src.application.booking_source import source_from_via

    url = booking_url("https://glideclub.by", 7, city_id=1)
    assert "trainer_7_v_k1" in url
    assert source_from_via("k1").code == "site_catalog"


def test_price_tiers_by_tariffs() -> None:
    def svc(*tiers, cents=None):
        return {
            "currency_code": "BYN",
            "price_cents": cents,
            "price_tiers": [{"tier_kind": k, "price_cents": c} for k, c in tiers],
        }

    nb = " "
    assert price_tiers([svc(("child", 4500), ("adult", 5000), ("adult_and_child", 6500))]) == [
        (f"45{nb}BYN", "ребёнок"),
        (f"50{nb}BYN", "взрослый"),
    ]
    assert price_tiers([svc(("child", 5000), ("adult", 5000))]) == [(f"50{nb}BYN", "дети и взрослые")]
    assert price_tiers([svc(cents=5500)]) == [(f"55{nb}BYN", "за занятие")]
    assert price_tiers([svc(), svc(("adult", 5500))]) == [(f"55{nb}BYN", "взрослый")]
    assert price_tiers([svc()]) is None


def test_direction_min_price_takes_group_and_covering_passes() -> None:
    def svc(sid, *tiers, group=None):
        return {
            "service_id": sid,
            "currency_code": "BYN",
            "price_cents": None,
            "group_price_cents": group,
            "price_tiers": [{"tier_kind": k, "price_cents": c} for k, c in tiers],
        }

    zero, hock, better = (
        direction_by_slug("s-nulya"),
        direction_by_slug("s-klyushkoy"),
        direction_by_slug("uzhe-katayus"),
    )
    t = {
        "services_by_dir": {
            "zero": [svc(1, ("child", 4500), ("adult", 5000), group=2500)],
            "hock": [svc(4, ("adult", 5500))],
        },
        "passes": [{"per_session_cents": 4187, "service_ids": (4,)}],
    }
    # Групповая 25 у «С нуля»; абонемент только на «Хоккейное» — у «С клюшкой», не у «С нуля».
    assert direction_min_price(t, zero) == (2500, "BYN")
    assert direction_min_price(t, hock) == (4187, "BYN")
    assert direction_min_price(t, better) is None
    only_hockey_pass = {**t, "services_by_dir": {"zero": [svc(1, ("adult", 5000))], "hock": [svc(4, ("adult", 5500))]}}
    assert direction_min_price(only_hockey_pass, zero) == (5000, "BYN")
    assert direction_min_price(only_hockey_pass, ALL) == (4187, "BYN")
    # Абонемент без услуг — на все услуги тренера.
    every = {
        "services_by_dir": {"zero": [svc(1, ("adult", 5000))]},
        "passes": [{"per_session_cents": 4187, "service_ids": None}],
    }
    assert direction_min_price(every, zero) == (4187, "BYN")
    # Ключи — как у вкладок Mini App.
    assert min_price_by_direction(t) == {
        "all": {"cents": 2500, "currency": "BYN"},
        "s-nulya": {"cents": 2500, "currency": "BYN"},
        "s-klyushkoy": {"cents": 4187, "currency": "BYN"},
    }
    # Правило показа не изменилось: абонемент без цены услуги и без катка в каталог не выводит.
    assert not is_listed({**every, "services_by_dir": {"zero": [svc(1)]}, "arenas": []}, zero)


def test_all_tab_price_says_when_minimum_is_group_or_pass() -> None:
    def svc(*tiers, group=None):
        return {
            "service_id": 1,
            "currency_code": "BYN",
            "price_cents": None,
            "group_price_cents": group,
            "price_tiers": [{"tier_kind": k, "price_cents": c} for k, c in tiers],
        }

    group = {"services_by_dir": {"zero": [svc(("child", 4500), ("adult", 5000), group=3000)]}, "passes": []}
    assert "от 30\xa0BYN <small>в группе</small>" in _price_html(group, ALL)
    by_pass = {
        "services_by_dir": {"zero": [svc(("adult", 5000))]},
        "passes": [{"per_session_cents": 4000, "service_ids": None}],
    }
    assert "от 40\xa0BYN <small>по абонементу</small>" in _price_html(by_pass, ALL)
    single = {"services_by_dir": {"zero": [svc(("child", 4500), ("adult", 5000), group=6000)]}, "passes": []}
    html = _price_html(single, ALL)
    assert "от 45\xa0BYN</div>" in html and "<small>" not in html


def test_education_line_only_known_categories() -> None:
    assert education_line("Высшее профильное") == "Высшее профильное образование"
    assert education_line("Другое") == ""
    assert education_line("Закончил всё что можно") == ""


# ── страницы ─────────────────────────────────────────────────────────


async def _set_services(db_session, tid: int, services: dict[int, list[tuple[str, int]] | None]) -> None:
    """``{service_id: [(tier_kind, cents)] | None}`` — None: услуга без цены."""
    await db_session.execute(text("DELETE FROM trainer_service_price_variants WHERE trainer_id = :t"), {"t": tid})
    await db_session.execute(text("DELETE FROM trainer_services WHERE trainer_id = :t"), {"t": tid})
    for sid, tiers in services.items():
        await db_session.execute(
            text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:t, :s, :p)"),
            {"t": tid, "s": sid, "p": max((c for _k, c in tiers), default=None) if tiers else None},
        )
        for i, (kind, cents) in enumerate(tiers or []):
            await db_session.execute(
                text(
                    "INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind) "
                    "VALUES (:t, :s, :k, :c, :i, :k)"
                ),
                {"t": tid, "s": sid, "k": kind, "c": cents, "i": i},
            )


async def _city(db_session, client) -> dict:
    """Город: A — с нуля + хоккей, цены, абонемент 41,87 только на хоккей, онлайн-запись, окно; B — с нуля + уже катаюсь без цен, но с катками;
    C — фигурное без цены и без катка (не показывается); D — только ролики (не вкладка)."""
    place = await _place(db_session)
    other_arena = await _insert_arena(db_session, place["city_id"], name=f"Второй каток {uuid.uuid4().hex[:4]}")
    names = {}
    ids = {}
    for key in "ABCD":
        first = f"{key}тренер{uuid.uuid4().hex[:4]}"
        ids[key] = await _trainer_on(db_session, client, place, first_name=first)
        names[key] = f"{first} Тренерова"
    await _set_services(
        db_session,
        ids["A"],
        {1: [("child", 4500), ("adult", 5000), ("adult_and_child", 6500)], 4: [("child", 5000), ("adult", 5500)]},
    )
    await _set_services(db_session, ids["B"], {1: None, 2: None})
    await _set_services(db_session, ids["C"], {3: None})
    await _set_services(db_session, ids["D"], {5: [("adult", 4000)]})
    # Абонемент 670/16 (41,87) из фикстуры: у A — только на «Хоккейное» (4), у остальных нет.
    await db_session.execute(
        text("DELETE FROM trainer_pass_products WHERE trainer_id = ANY(:t)"), {"t": [ids["B"], ids["C"], ids["D"]]}
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_pass_product_services (pass_product_id, service_id) "
            "SELECT id, 4 FROM trainer_pass_products WHERE trainer_id = :t"
        ),
        {"t": ids["A"]},
    )
    await db_session.execute(text("DELETE FROM trainer_arenas WHERE trainer_id = :t"), {"t": ids["C"]})
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) VALUES (:t, :a, true)"),
        {"t": ids["B"], "a": other_arena},
    )
    await db_session.execute(
        text(
            "UPDATE trainer_profiles SET rating_avg = 5.0, rating_count = 2, experience_years = 6 WHERE trainer_id = :t"
        ),
        {"t": ids["A"]},
    )
    await db_session.execute(
        text(
            "UPDATE trainer_profiles SET rating_avg = 4.7, rating_count = 3, education = 'Высшее профильное' WHERE trainer_id = :t"
        ),
        {"t": ids["B"]},
    )
    await _ensure_trainer_subscription_tier(db_session, ids["A"], SUBSCRIPTION_TIER_ONLINE)
    await _slot(db_session, ids["A"], days=2, hour=12, arena_id=place["arena_id"])
    await db_session.commit()
    return {**place, "other_arena": other_arena, "ids": ids, "names": names, "slug": city_slug(place["city_name"])}


def _cards(html: str) -> list[str]:
    return re.findall(r'<article class="tc">(.*?)</article>', html, re.S)


def _tab(html: str, label: str) -> str | None:
    m = re.search(rf'class="tcat-tab[^"]*"[^>]*>{re.escape(label)}<b>(\d+)</b>', html)
    return m.group(1) if m else None


@pytest.mark.asyncio
async def test_catalog_tabs_rule_and_cards(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        base = f"/c/{c['slug']}/trenery"
        all_r = await client.get(base)
        zero = await client.get(f"{base}/s-nulya")
        hock = await client.get(f"{base}/s-klyushkoy")
        fig = await client.get(f"{base}/figurnoe")
    ids, names = c["ids"], c["names"]
    assert all_r.status_code == zero.status_code == hock.status_code == fig.status_code == 200

    html = zero.text
    # Правило показа: A (цена) и B (без цены, но с катком); C без цены и катка и D (ролики) — нет.
    assert names["A"] in html and names["B"] in html
    assert names["C"] not in all_r.text and names["D"] not in all_r.text
    # Вкладки — ссылки с числами; «Фигурное» с нулём скрыта.
    assert _tab(html, "Все") == "2" and _tab(html, "С нуля") == "2" and _tab(html, "Уже катаюсь") == "1"
    assert _tab(html, "С клюшкой") == "1" and _tab(html, "Фигурное") is None
    assert f'href="{base}/s-klyushkoy"' in html
    assert "Научиться кататься на коньках с нуля" in html and "Мне 35 — не поздно начинать?" in html
    # Лид на странице остаётся общим. В сниппете — только направления, которые реально есть.
    assert "Учат кататься с нуля и ставят технику. Есть фигурное катание и хоккей." in all_r.text
    meta = re.search(r'name="description" content="([^"]*)"', all_r.text).group(1)
    assert "по катанию на коньках" in meta and "с нуля" in meta and "хоккейное катание" in meta
    assert "учат" not in meta
    assert "фигурное" not in meta and "…" not in meta and meta.endswith("Запись в Telegram.")
    assert "Оплата тренеру на месте." not in re.search(r'<p class="tcat-lead">(.*?)</p>', all_r.text).group(1)
    # Сверху — с онлайн-записью: A первая; окно — ссылка в запись Mini App через учётный прокси.
    cards = _cards(html)
    assert names["A"] in cards[0] and names["B"] in cards[1]
    assert f'href="{trainer_path(ids["A"], names["A"])}?via=k' in cards[0]
    # Время — сразу запись на этот слот (TASK-357), источник — «каталог сайта».
    assert (
        re.search(rf"startapp=trainer_{ids['A']}_s_[1-9][0-9]*_v_k[1-9]", cards[0])
        and "surface=trainer_catalog" in cards[0]
    )
    assert 'class="tc-slot"' in cards[0]
    # Цена — по тарифам направления; без цены — честно.
    assert "45 BYN <small>ребёнок</small>" in cards[0] and "50 BYN <small>взрослый</small>" in cards[0]
    assert "Цену уточните у тренера" in cards[1]
    # Абонемент A только на «Хоккейное» не трогает «от» вкладки «С нуля».
    assert "от <b>45 BYN</b> за занятие" in html
    # Оценка — с первой, одна подпись; стаж и образование — из полей; числа занятий нет.
    assert "★" in cards[0] and "2 оценки" in cards[0]
    assert "★" in cards[1] and "3 оценки" in cards[1]
    assert "оценили" not in cards[0] and "оценили" not in cards[1]
    assert "Тренирует 6 лет" in cards[0] and "Высшее профильное образование" in cards[1]
    assert not re.search(r"\d+\s*занят(ие|ия|ий)\b", html.replace("за занятие", ""))
    # «вместе с ребёнком» — из тарифов: 1 тренер с ценой «взрослый + ребёнок».
    assert "у 1 тренера есть цена «взрослый + ребёнок»" in html
    assert "Что будет после записи" in html and "Как проходит первое занятие" in html
    assert "оплата тренеру лично" in html and "Расскажите, какая у вас цель?" in html
    assert "Приезжайте за 15" not in html
    from src.application.catalog_directions import ALL

    assert ALL.steps[2][0] == "Вперёд тренироваться!"

    # «С клюшкой» = хоккейное катание (4): тариф 50/55.
    hcards = _cards(hock.text)
    assert len(hcards) == 1 and "50 BYN <small>ребёнок</small>" in hcards[0]
    assert "Хоккейное катание" in hock.text and "Мне 35" not in hock.text
    # «от» вкладки и «Все» — с абонементом на занятие, дробь как есть.
    assert "от <b>41,87 BYN</b> за занятие" in hock.text and "от <b>41,87 BYN</b> за занятие" in all_r.text
    # Пустое направление — своего состава нет, в индексе ему нечего делать. Canonical — свой адрес.
    assert 'content="noindex, follow"' in fig.text and not _cards(fig.text)
    assert f'rel="canonical" href="https://glide.example{base}/figurnoe"' in fig.text
    # «С нуля» совпадает со «Всеми» по людям, но запрос свой — страница в индексе, canonical на себя.
    assert 'content="index, follow"' in zero.text
    assert f'rel="canonical" href="https://glide.example{base}/s-nulya"' in zero.text
    assert 'content="index, follow"' in all_r.text
    assert f'rel="canonical" href="https://glide.example{base}"' in all_r.text
    # В JSON-LD — канонические адреса тренеров, без ?via=.
    ld_urls = re.findall(r'"url":\s*"([^"]+)"', all_r.text)
    assert any("/t/" in u for u in ld_urls) and not any("via=" in u for u in ld_urls if "/t/" in u)


@pytest.mark.asyncio
async def test_arena_filter_canonical_and_empty_state(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        base = f"/c/{c['slug']}/trenery"
        other = await client.get(f"{base}/s-nulya?arena={c['other_arena']}")
        empty = await client.get(f"{base}/s-klyushkoy?arena={c['other_arena']}")
        junk = await client.get(f"{base}/s-nulya?arena=abc")
    names = c["names"]
    # Второй каток — только B; canonical без фильтра; вкладки несут фильтр.
    cards = _cards(other.text)
    assert len(cards) == 1 and names["B"] in cards[0]
    assert f'rel="canonical" href="https://glide.example{base}/s-nulya"' in other.text
    assert f'href="{base}/uzhe-katayus?arena={c["other_arena"]}"' in other.text
    assert "Где удобно заниматься?" in other.text and 'aria-label="Сбросить каток"' in other.text
    # Пустое состояние фильтра: вкладку сам не переключает, предлагает два выхода.
    assert not _cards(empty.text)
    assert "тренеров «С клюшкой» здесь пока нет" in empty.text
    assert f'href="{base}?arena={c["other_arena"]}">Все тренеры этого катка' in empty.text
    assert f'href="{base}/s-klyushkoy">«С клюшкой» на всех катках' in empty.text
    assert junk.status_code == 200 and len(_cards(junk.text)) == 2


@pytest.mark.asyncio
async def test_unknown_city_or_direction_404_and_city_id_redirects(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        bad_dir = await client.get(f"/c/{c['slug']}/trenery/roliki")
        bad_city = await client.get("/c/no-such-city-xyz/trenery")
        by_id = await client.get(f"/c/{c['city_id']}/trenery/s-nulya?arena=1", follow_redirects=False)
        head = await client.head(f"/c/{c['slug']}/trenery")
    assert bad_dir.status_code == 404 and bad_city.status_code == 404
    assert by_id.status_code == 301 and by_id.headers["location"] == f"/c/{c['slug']}/trenery/s-nulya?arena=1"
    assert head.status_code == 200


@pytest.mark.asyncio
async def test_sitemap_lists_only_directions_with_trainers(app_use_test_db, db_session) -> None:
    async with _client() as client:
        c = await _city(db_session, client)
        xml = (await client.get("/sitemap.xml")).text
        all_html = (await client.get(f"/c/{c['slug']}/trenery")).text
    base = f"https://glide.example/c/{c['slug']}/trenery"
    assert f"<loc>{base}</loc>" in xml
    assert f"<loc>{base}/s-nulya</loc>" in xml
    assert f"<loc>{base}/uzhe-katayus</loc>" in xml
    assert f"<loc>{base}/s-klyushkoy</loc>" in xml
    assert f"<loc>{base}/figurnoe</loc>" not in xml
    assert re.search(rf"<loc>{re.escape(base)}</loc><lastmod>\d{{4}}-\d{{2}}-\d{{2}}T", xml)
    assert re.search(r"<loc>https://glide\.example/t/[^<]+</loc><lastmod>\d{4}-\d{2}-\d{2}T", xml)
    assert 'content="index, follow"' in all_html


@pytest.mark.asyncio
async def test_city_with_one_trainer_has_no_tabs_or_filter(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place = await _place(db_session)
        first = f"Один{uuid.uuid4().hex[:4]}"
        await _trainer_on(db_session, client, place, first_name=first)
        html = (await client.get(f"/c/{city_slug(place['city_name'])}/trenery")).text
    assert len(_cards(html)) == 1 and f"{first} Тренерова" in html
    assert "tcat-tabs" not in html and "Где удобно заниматься?" not in html
    assert "Тренер по катанию на коньках" in html
    assert "1 тренер по катанию на коньках" in html
    assert "Сверху — тренеры" not in html


@pytest.mark.asyncio
async def test_catalog_stylesheet_is_served() -> None:
    async with _client() as client:
        r = await client.get("/static/share/trainer-catalog.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css") and ".tc-slot" in r.text


async def _two_city_trainer(db_session, client) -> dict:
    """Тренер работает на катках двух городов; online-запись включена."""
    a = await _place(db_session)
    b = await _place(db_session)
    tid = await _trainer_on(db_session, client, a, first_name=f"Двагорода{uuid.uuid4().hex[:4]}")
    await db_session.execute(
        text(
            "INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) VALUES (:t, :a, true) ON CONFLICT DO NOTHING"
        ),
        {"t": tid, "a": b["arena_id"]},
    )
    await db_session.execute(
        text("INSERT INTO trainer_cities (trainer_id, city_id) VALUES (:t, :c) ON CONFLICT DO NOTHING"),
        {"t": tid, "c": b["city_id"]},
    )
    await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
    return {"a": a, "b": b, "tid": tid}


@pytest.mark.asyncio
async def test_city_catalog_hides_windows_from_another_city(app_use_test_db, db_session) -> None:
    """Единственное окно тренера — на катке города B: в каталоге города A его нет (не врём «есть время»)."""
    async with _client() as client:
        t = await _two_city_trainer(db_session, client)
        await _slot(db_session, t["tid"], days=2, hour=13, arena_id=t["b"]["arena_id"])
        await db_session.commit()
        html_a = (await client.get(f"/c/{city_slug(t['a']['city_name'])}/trenery")).text
        html_b = (await client.get(f"/c/{city_slug(t['b']['city_name'])}/trenery")).text
    assert 'class="tc-slot"' not in html_a
    assert 'class="tc-slot"' in html_b
    # Катки в разных городах — у окна подпись, где именно.
    assert f"· {t['b']['name']}" in html_b


@pytest.mark.asyncio
async def test_city_catalog_names_arena_when_trainer_has_several(app_use_test_db, db_session) -> None:
    async with _client() as client:
        t = await _two_city_trainer(db_session, client)
        second = await _insert_arena(db_session, t["a"]["city_id"], name=f"Второй {uuid.uuid4().hex[:4]}")
        await db_session.execute(
            text("INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) VALUES (:t, :a, true)"),
            {"t": t["tid"], "a": second},
        )
        await _slot(db_session, t["tid"], days=2, hour=13, arena_id=t["a"]["arena_id"])
        await _slot(db_session, t["tid"], days=2, hour=15, arena_id=t["b"]["arena_id"])
        await db_session.commit()
        html = (await client.get(f"/c/{city_slug(t['a']['city_name'])}/trenery")).text
    assert len(re.findall(r'class="tc-slot"', html)) == 1
    assert f"13:00 · {t['a']['name']}" in html
    assert t["b"]["name"] not in html


@pytest.mark.asyncio
async def test_city_catalog_single_arena_has_no_arena_name_on_slot(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Один{uuid.uuid4().hex[:4]}")
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=13, arena_id=place["arena_id"])
        await db_session.commit()
        html = (await client.get(f"/c/{city_slug(place['city_name'])}/trenery")).text
    assert 'class="tc-slot"' in html and "13:00 ·" not in html


@pytest.mark.asyncio
async def test_city_catalog_window_on_public_primary_arena_without_trainer_arenas_row(
    app_use_test_db, db_session
) -> None:
    """Основной публичный каток без ``trainer_arenas`` показывает окно; каток другого города — нет."""
    async with _client() as client:
        t = await _two_city_trainer(db_session, client)
        await db_session.execute(text("DELETE FROM trainer_arenas WHERE trainer_id = :t"), {"t": t["tid"]})
        await db_session.execute(
            text("UPDATE trainers SET primary_arena_id = :a WHERE id = :t"), {"a": t["a"]["arena_id"], "t": t["tid"]}
        )
        await _slot(db_session, t["tid"], days=2, hour=13, arena_id=None)
        await _slot(db_session, t["tid"], days=2, hour=15, arena_id=t["b"]["arena_id"])
        await db_session.commit()
        html_a = (await client.get(f"/c/{city_slug(t['a']['city_name'])}/trenery")).text
    assert len(re.findall(r'class="tc-slot"', html_a)) == 1
    assert "13:00" in html_a


@pytest.mark.asyncio
async def test_city_catalog_hides_window_on_unpublished_primary_arena(app_use_test_db, db_session) -> None:
    """Каток на модерации (не подтверждён) — окно на нём клиентам города не светим, даже если он основной."""
    async with _client() as client:
        t = await _two_city_trainer(db_session, client)
        await db_session.execute(text("DELETE FROM trainer_arenas WHERE trainer_id = :t"), {"t": t["tid"]})
        await db_session.execute(
            text("UPDATE trainers SET primary_arena_id = :a WHERE id = :t"), {"a": t["a"]["arena_id"], "t": t["tid"]}
        )
        await db_session.execute(
            text("UPDATE arenas SET is_confirmed = false WHERE id = :a"), {"a": t["a"]["arena_id"]}
        )
        await _slot(db_session, t["tid"], days=2, hour=13, arena_id=None)
        await db_session.commit()
        html_a = (await client.get(f"/c/{city_slug(t['a']['city_name'])}/trenery")).text
    assert 'class="tc-slot"' not in html_a


def test_window_in_city_hides_only_known_other_city() -> None:
    from src.application.site_trainer_catalog import window_in_city

    cities = {1: 10, 2: 20, 3: None}
    assert window_in_city(None, cities, 10)
    assert window_in_city(1, cities, 10)
    assert not window_in_city(2, cities, 10)
    assert window_in_city(3, cities, 10)  # город неизвестен
    assert window_in_city(99, cities, 10)  # каток не найден
    assert window_in_city(2, cities, None)


def test_split_service_summary_and_service_title() -> None:
    from src.application.catalog_directions import service_title, split_service_summary

    hook, body = split_service_summary(
        "Если вы почти не стояли на льду.\n\nСпокойный старт: равновесие.\nВторая строка."
    )
    assert hook == "Если вы почти не стояли на льду."
    assert body == "Спокойный старт: равновесие.\nВторая строка."
    assert split_service_summary(None) == ("", "") and split_service_summary("  \n ") == ("", "")
    assert split_service_summary("Один абзац.") == ("Один абзац.", "")
    assert service_title("ОХМ(отработка хоккейного мастерства)") == "ОХМ — отработка хоккейного мастерства"
    assert service_title("Хоккейное катание") == "Хоккейное катание"
    assert service_title("ОФП/СФП") == "ОФП/СФП"


def test_card_has_save_heart_and_request_when_no_time() -> None:
    """Сердце — на каждой карточке; «Оставить заявку» — только когда окон нет (рядом с «Написать»)."""
    from src.application.catalog_directions import ALL
    from src.application.site_trainer_catalog import _card_html

    t = {
        "id": 9,
        "name": "Анна Тренерова",
        "initial": "А",
        "path": "/t/9-anna",
        "photo_url": None,
        "services_by_dir": {},
        "arenas": [],
        "about": None,
        "education": None,
        "experience_years": None,
        "windows": [],
        "can_book": True,
        "contact_url": "https://t.me/anna",
        "services": [],
    }
    html = _card_html(t, ALL, base_url="https://glide.example", city_id=1, arena_id=None)
    assert 'class="tc-save"' in html and "_i_save" in html.replace("&amp;", "&")
    assert ">Оставить заявку</a>" in html and "_i_request" in html.replace("&amp;", "&")
    assert "Написать в Telegram" in html
