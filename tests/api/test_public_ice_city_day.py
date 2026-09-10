"""
TASK-096 S3 — шеринг-артефакт «Лёд сегодня в городе» (AC-003, AC-005, AC-007).

Что здесь доказывается:
  * публичная страница отдаётся без авторизации и несёт og-теги (иначе превью в чате
    пустое, и пересылать нечего);
  * og:image — настоящий PNG, а не 404 и не заглушка;
  * ``/api/public/ice/share/{city_id}`` отдаёт контракт ``share_url``/``share_body``/
    ``share_text`` — тот же, что у share-trainer, поэтому фронт не пишет свой обработчик;
  * каждое нажатие «Поделиться» пишет строку в ``client_share_events`` (DEC-005, G-P5
    «и это измеряется»);
  * на странице нет выдуманных данных (AC-005): цены нет — значит поля нет, а не «0».
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug, summary_line
from tests.api.test_public_arenas import _insert_arena, _insert_city
from src.application.ice_session_use_cases import create_ice_session


def _minsk_today() -> date:
    """City day pages use Europe/Minsk; CI runners are often UTC — date.today() drifts."""
    return datetime.now(ZoneInfo("Europe/Minsk")).date()


async def _add_today_session(
    db_session,
    arena_id: int,
    *,
    starts_at_local: str = "23:30",
    price_adult_minor: int | None = 850,
) -> int:
    """
    Сеанс на сегодня (по Минску), поздним временем.

    23:30 не украшение: выборка отбрасывает сеансы с ``starts_at_utc <= now``
    (PDEC-005), и тест, поставленный на утро, разваливался бы каждый раз после
    старта слота.
    """
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=_minsk_today(),
        starts_at_local=starts_at_local,
        duration_minutes=45,
        kind="public_skate",
        price_adult_minor=price_adult_minor,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.flush()
    return int(created["id"])


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_city_slug_transliterates_and_normalizes() -> None:
    assert city_slug("Минск") == "minsk"
    assert city_slug("Санкт-Петербург") == "sankt-peterburg"
    assert city_slug("Москва / МО") == "moskva-mo"
    assert city_slug("  Брест  ") == "brest"


@pytest.mark.asyncio
async def test_public_page_opens_without_auth_and_carries_og_tags(
    app_use_test_db, db_session
) -> None:
    """AC-003: получатель ссылки не ставит бота, чтобы увидеть расписание."""
    name = f"Огтест{uuid.uuid4().hex[:6]}"
    cid = await _insert_city(db_session, name=name)
    arena = await _insert_arena(db_session, cid, name="Ледовый дворец «Проба»")
    await _add_today_session(db_session, arena)

    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/ice/{slug}/today")

    assert page.status_code == 200, page.text
    html = page.text
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'property="og:image"' in html
    assert f"/ice/{slug}/today/og.png" in html
    assert 'name="twitter:card"' in html
    # Расписание — в первом же ответе, а не подгружается скриптом.
    assert "Ледовый дворец «Проба»" in html or "Ледовый дворец" in html
    assert "23:30" in html
    assert "8.50 BYN" in html
    # Ни одного незаменённого плейсхолдера шаблона.
    assert "__" not in html.split("<style>")[0]


@pytest.mark.asyncio
async def test_page_by_city_id_redirects_to_canonical_slug(app_use_test_db, db_session) -> None:
    """Одна ссылка в чатах, а не две на одно и то же."""
    name = f"Редирект{uuid.uuid4().hex[:6]}"
    cid = await _insert_city(db_session, name=name)
    async with _client() as client:
        resp = await client.get(f"/ice/{cid}/today", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == f"/ice/{city_slug(name)}/today"


@pytest.mark.asyncio
async def test_unknown_city_is_404_not_empty_page(app_use_test_db, db_session) -> None:
    async with _client() as client:
        resp = await client.get("/ice/gorod-kotorogo-net/today")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_empty_day_page_is_honest_and_has_an_exit(app_use_test_db, db_session) -> None:
    """
    AC-002/AC-005 на публичной странице: пустой день говорит «нет», а не изображает загрузку.

    Кнопка «Открыть в Glide» — тот самый выход; без CLIENT_BOT_USERNAME её нет вовсе,
    и это проверяется отдельно ниже.
    """
    name = f"Пустой{uuid.uuid4().hex[:6]}"
    await _insert_city(db_session, name=name)
    async with _client() as client:
        page = await client.get(f"/ice/{city_slug(name)}/today")
    assert page.status_code == 200
    assert "массовых катаний в расписании нет" in page.text
    assert "Загрузка" not in page.text


@pytest.mark.asyncio
async def test_city_day_page_hides_in_progress_slots(app_use_test_db, db_session) -> None:
    """PDEC-005: 12:15 at 13:10 must not stay on the public day page either."""
    from src.application.ice_city_day import get_city_ice_day
    from tests.api.test_public_arenas import _add_minsk_session

    now_minsk = datetime.now(ZoneInfo("Europe/Minsk"))
    name = f"Идущий{uuid.uuid4().hex[:6]}"
    cid = await _insert_city(db_session, name=name)
    arena = await _insert_arena(db_session, cid, name="ТЦ Diamond city")
    await _add_minsk_session(
        db_session, arena, when=now_minsk - timedelta(minutes=55), duration_minutes=90
    )
    upcoming = now_minsk + timedelta(hours=2)
    await _add_minsk_session(db_session, arena, when=upcoming, duration_minutes=45)

    day = await get_city_ice_day(db_session, city_id=cid)
    times = [
        s.get("starts_at_local")
        for a in day.get("arenas") or []
        for s in a.get("sessions") or []
    ]
    started_hhmm = (now_minsk - timedelta(minutes=55)).strftime("%H:%M")
    upcoming_hhmm = upcoming.strftime("%H:%M")
    assert started_hhmm not in times
    if upcoming.date() == now_minsk.date():
        assert upcoming_hhmm in times

    async with _client() as client:
        page = await client.get(f"/ice/{city_slug(name)}/today")
    assert page.status_code == 200, page.text
    assert started_hhmm not in page.text


@pytest.mark.asyncio
async def test_og_image_is_a_real_png(app_use_test_db, db_session) -> None:
    name = f"Пнг{uuid.uuid4().hex[:6]}"
    cid = await _insert_city(db_session, name=name)
    arena = await _insert_arena(db_session, cid, name="Каток для превью")
    await _add_today_session(db_session, arena)

    async with _client() as client:
        img = await client.get(f"/ice/{city_slug(name)}/today/og.png")

    assert img.status_code == 200, img.text
    assert img.headers["content-type"] == "image/png"
    assert img.content[:8] == b"\x89PNG\r\n\x1a\n"
    # 1200×630 — размер, который Telegram и Open Graph ждут для широкого превью.
    assert int.from_bytes(img.content[16:20], "big") == 1200
    assert int.from_bytes(img.content[20:24], "big") == 630


@pytest.mark.asyncio
async def test_share_endpoint_contract_matches_share_trainer(app_use_test_db, db_session) -> None:
    """AC-003: фронт переиспользует openTelegramShareUrlFromMiniApp без правок."""
    name = f"Шеринг{uuid.uuid4().hex[:6]}"
    cid = await _insert_city(db_session, name=name)
    arena = await _insert_arena(db_session, cid, name="Каток «Шеринг»")
    await _add_today_session(db_session, arena)

    async with _client() as client:
        resp = await client.get(f"/api/public/ice/share/{cid}", params={"share_context": "ice_tab"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("share_url", "share_body", "share_text"):
        assert key in body and body[key], f"{key} пустой"
    assert body["share_url"].endswith(f"/ice/{city_slug(name)}/today")
    # share_text начинается ссылкой, share_body её не дублирует — иначе Telegram
    # покажет URL дважды.
    assert body["share_text"].startswith(body["share_url"])
    assert body["share_url"] not in body["share_body"]
    assert body["city_name"] == name
    assert body["session_count"] == 1
    assert body["arena_count"] == 1


@pytest.mark.asyncio
async def test_share_click_is_recorded_in_client_share_events(app_use_test_db, db_session) -> None:
    """DEC-005 / G-P5: до TASK-096 доля шеринга была непознаваема, а не мала."""
    name = f"Метрика{uuid.uuid4().hex[:6]}"
    cid = await _insert_city(db_session, name=name)
    arena = await _insert_arena(db_session, cid, name="Каток «Метрика»")
    await _add_today_session(db_session, arena)

    async with _client() as client:
        first = await client.get(f"/api/public/ice/share/{cid}", params={"share_context": "ice_tab"})
        second = await client.get(f"/api/public/ice/share/{cid}")
    assert first.status_code == 200 and second.status_code == 200

    rows = (
        await db_session.execute(
            text(
                """
                SELECT kind, share_context, city_id, trainer_id
                FROM client_share_events
                WHERE city_id = :cid
                ORDER BY id
                """
            ),
            {"cid": cid},
        )
    ).all()
    # Событие на каждое нажатие: это интерес к шерингу, а не «сообщение отправлено» —
    # факт отправки Telegram нам не сообщает, и колонку нельзя читать как отправку.
    assert len(rows) == 2
    assert {r[0] for r in rows} == {"ice_city_day"}
    assert rows[0][1] == "ice_tab"
    assert rows[1][1] == "ice_tab"  # умолчание, когда контекст не передали
    assert all(r[3] is None for r in rows), "у шеринга города нет тренера"


@pytest.mark.asyncio
async def test_share_unknown_city_is_404_and_writes_nothing(app_use_test_db, db_session) -> None:
    before = (
        await db_session.execute(text("SELECT count(*) FROM client_share_events"))
    ).scalar_one()
    async with _client() as client:
        resp = await client.get("/api/public/ice/share/99999999")
    assert resp.status_code == 404
    after = (
        await db_session.execute(text("SELECT count(*) FROM client_share_events"))
    ).scalar_one()
    assert after == before


@pytest.mark.asyncio
async def test_no_invented_data_when_price_is_unknown(app_use_test_db, db_session) -> None:
    """
    AC-005: неизвестная цена остаётся неизвестной.

    Самый дешёвый способ соврать в этом продукте — напечатать «0 BYN» там, где парсер
    цену не достал. Тест держит именно эту границу.
    """
    name = f"Безцен{uuid.uuid4().hex[:6]}"
    cid = await _insert_city(db_session, name=name)
    arena = await _insert_arena(db_session, cid, name="Каток без цен")
    await _add_today_session(db_session, arena, price_adult_minor=None)

    async with _client() as client:
        page = await client.get(f"/ice/{city_slug(name)}/today")
        share = await client.get(f"/api/public/ice/share/{cid}")

    assert page.status_code == 200
    assert "0 BYN" not in page.text
    assert "23:30" in page.text
    body = share.json()
    # Сводка честно молчит о ценах, но не молчит о сеансах.
    assert "BYN" not in body["summary"]
    assert "1 сеанс" in body["summary"]


def test_summary_line_never_invents_urgency() -> None:
    """AC-005 на уровне копирайта: ни «осталось мест», ни «смотрят сейчас»."""
    day = {
        "arena_count": 3,
        "session_count": 7,
        "day_label": "сегодня",
        "price_min_minor": 800,
        "price_max_minor": 1200,
        "currency_code": "BYN",
    }
    line = summary_line(day, city_name="Минск")
    assert line == "Минск, сегодня: 7 сеансов на 3 катках, от 8 BYN до 12 BYN."
    for forbidden in ("осталось", "смотрят", "успей", "только сегодня", "мест"):
        assert forbidden not in line.lower()
