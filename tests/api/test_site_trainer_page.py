"""TASK-350/356: страница тренера ``/t/{id}-{slug}`` — та же логика, что у карточки тренера в Mini App.

TASK-356 (PDEC-033, ``design/trainer.html``): карточка цены с вкладками направлений и ближайшим
временем, неделя, цены по тарифам, «Ещё ведёт», оценка от 3 оценок, «В Glide с …», без числа занятий.
"""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.site_trainer_page import parse_trainer_ref, trainer_path, trainer_slug
from src.infrastructure.db.models import SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE
from tests.api.test_arena_trainer_windows import _slot
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on
from tests.api.test_webapp_client_miniapp_integration import _ensure_trainer_subscription_tier


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")


def test_slug_is_id_plus_transliterated_name() -> None:
    assert trainer_slug(9, "Александр Гаевский") == "9-aleksandr-gaevskiy"
    assert trainer_slug(9, "🪴 Максим") == "9-maksim"
    assert trainer_slug(9, "Тренер") == "9"
    assert trainer_path(9, "") == "/t/9"
    assert parse_trainer_ref("9-aleksandr-gaevskiy") == 9
    assert parse_trainer_ref("9") == 9
    assert parse_trainer_ref("abc") is None
    assert parse_trainer_ref("0-x") is None


async def _listed(db_session, client, *, tier: str | None) -> tuple[dict, int, str]:
    place = await _place(db_session)
    first = f"Анна{uuid.uuid4().hex[:4]}"
    tid = await _trainer_on(db_session, client, place, first_name=first)
    await db_session.execute(text("UPDATE trainers SET telegram_username = 'anna_coach' WHERE id = :t"), {"t": tid})
    if tier:
        await _ensure_trainer_subscription_tier(db_session, tid, tier)
    await db_session.commit()
    return place, tid, f"{first} Тренерова"


@pytest.mark.asyncio
async def test_listed_trainer_with_booking_has_page_windows_and_book_cta(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        path = trainer_path(tid, name)
        short = await client.get(f"/t/{tid}", follow_redirects=False)
        wrong = await client.get(f"/t/{tid}-wrong?utm_source=x", follow_redirects=False)
        resp = await client.get(path)
        api = (await client.get(f"/api/public/trainers/{tid}")).json()

    assert short.status_code == 301 and short.headers["location"] == path
    assert wrong.status_code == 301 and wrong.headers["location"] == path + "?utm_source=x"
    assert resp.status_code == 200
    html = resp.text
    assert api["can_book"] is True
    assert f"<h1 class=\"tp-name\">{name}</h1>" in html
    assert 'content="index, follow"' in html
    assert f'rel="canonical" href="https://glide.example{path}"' in html
    assert '"@type": "Person"' in html
    # JSON-LD — валидный JSON в одном теге (раньше шаблон оборачивал готовый <script> ещё раз).
    import json

    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        json.loads(block)
    # Время — сразу запись на этот слот в Mini App (TASK-357), через учётный прокси.
    assert "Ближайшее время — записаться" in html
    assert re.search(rf"startapp=trainer_{tid}_s_[1-9][0-9]*&amp;surface=trainer_page", html)
    assert "Нужен Telegram — запись и переписка идут там." in html
    assert "Всё время на неделю" in html and "нет окон" in html
    assert 'id="tp-mbar"' in html and "Записаться на " in html
    # Каток — ссылкой на страницу катка сайта, не в Telegram.
    assert f'href="https://glide.example{place["path"]}"' in html
    # Тарифы фикстуры 45/50 — в карточке ребёнок и взрослый, цена только из тарифов (не групповая 25).
    assert "<span>Ребёнок</span><b>45\u00a0BYN</b>" in html and "<span>Взрослый</span><b>50\u00a0BYN</b>" in html
    assert "25\u00a0BYN" not in html
    assert "Что будет после записи" in html and f"{name.split()[0]} подтвердит" in html


@pytest.mark.asyncio
async def test_without_online_booking_page_offers_write_not_book(app_use_test_db, db_session) -> None:
    """Карточка без подписки — бесплатна: «Написать в Telegram», окон и «Записаться» нет (PDEC-025)."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_CRM)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
        api = (await client.get(f"/api/public/trainers/{tid}")).json()
    assert api["can_book"] is False
    assert "Записаться" not in html
    assert "Всё время на неделю" not in html and "Ближайшее время" not in html and 'id="tp-mbar"' not in html
    assert "Что будет после записи" not in html
    assert f'href="/r/tg/{tid}"' in html and "Написать в Telegram" in html
    assert "data-catalog-phone-beacon=" in html
    # Цены остаются: бесплатная карточка — «Написать» и цены.
    assert "<h2 class=\"b-h2 tp-h2\">Цены</h2>" in html and "45\u00a0BYN" in html


@pytest.mark.asyncio
async def test_hidden_trainer_page_opens_by_link_but_is_noindex_and_off_sitemap(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await db_session.execute(
            text("UPDATE trainers SET catalog_state = 'hidden', is_catalog_visible = false WHERE id = :t"), {"t": tid}
        )
        await db_session.commit()
        path = trainer_path(tid, name)
        resp = await client.get(path)
        sitemap = (await client.get("/sitemap.xml")).text
        api = await client.get(f"/api/public/trainers/{tid}")
        place_html = (await client.get(place["path"])).text
    assert api.status_code == 404
    assert resp.status_code == 200
    assert 'content="noindex, follow"' in resp.text
    assert '"@type": "Person"' not in resp.text
    # Не в каталоге — постоянная ссылка тренера: бот привяжет человека к нему.
    assert f"https://t.me/glide_test_bot?start=welcome_ref_{tid}" in resp.text
    assert path not in sitemap
    assert path not in place_html


@pytest.mark.asyncio
async def test_listed_trainer_in_sitemap_and_deactivated_is_404(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=None)
        path = trainer_path(tid, name)
        sitemap = (await client.get("/sitemap.xml")).text
        assert f"<loc>https://glide.example{path}</loc>" in sitemap
        await db_session.execute(text("UPDATE trainers SET status = 'deactivated' WHERE id = :t"), {"t": tid})
        await db_session.commit()
        gone = await client.get(path)
        missing = await client.get("/t/999999999-nobody")
    assert gone.status_code == 404
    assert missing.status_code == 404
    assert re.search(r'name="robots" content="noindex"', gone.text)


@pytest.mark.asyncio
async def test_trainer_shared_link_is_site_page_and_keeps_welcome_ref_binding(app_use_test_db, db_session) -> None:
    """Ссылка из кабинета — ``/t/…?via=link``; кнопка на ней — ``welcome_ref``, бот привяжет ученика."""
    from tests.api.test_webapp_trainer_catalog import HEADERS
    from tests.api.test_webapp_trainer_miniapp_profile_integration import (
        _fresh_trainer_telegram_id,
        patch_trainer_init_auth,
    )

    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(text("UPDATE trainers SET telegram_id = :tg WHERE id = :t"), {"tg": tg, "t": tid})
    await db_session.commit()
    with patch_trainer_init_auth(tg):
        async with _client() as client:
            body = (await client.get("/api/webapp/trainer/hub/universal-invite-link", headers=HEADERS)).json()
    link = body["link"]
    assert link == f"https://glide.example{trainer_path(tid, name)}?via=link"
    assert link in body["share_text"]
    async with _client() as client:
        shared = (await client.get(link.replace("https://glide.example", ""))).text
        plain = (await client.get(link.replace("https://glide.example", "").split("?")[0])).text
    assert f"https://t.me/glide_test_bot?start=welcome_ref_{tid}" in shared
    # Тот же адрес без метки — витрина: карточка в Mini App через учётный прокси.
    assert f"startapp=trainer_{tid}&amp;surface=trainer_page" in plain
    # Канонический адрес один — метка ссылки на него не влияет.
    assert f'rel="canonical" href="https://glide.example{link.replace("https://glide.example", "").split("?")[0]}"' in shared


@pytest.mark.asyncio
async def test_page_from_client_recommendation_keeps_share_ref(app_use_test_db, db_session) -> None:
    """«Поделиться тренером» → ``/t/…?via=share``; кнопка — ``share_ref``, как прежняя рекомендация."""
    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        html = (await client.get(f"{trainer_path(tid, name)}?via=share")).text
    assert f"https://t.me/glide_test_bot?start=share_ref_{tid}" in html


# ── TASK-356: дизайн страницы ────────────────────────────────────────


async def _add_service(db_session, tid: int, service_id: int, tiers: dict[str, int] | None = None, **cols) -> None:
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents, description) VALUES (:t, :s, :p, :d) "
            "ON CONFLICT DO NOTHING"
        ),
        {"t": tid, "s": service_id, "p": cols.get("price_cents"), "d": cols.get("description")},
    )
    for i, (kind, cents) in enumerate((tiers or {}).items()):
        await db_session.execute(
            text(
                "INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind) "
                "VALUES (:t, :s, :l, :p, :o, :k)"
            ),
            {"t": tid, "s": service_id, "l": kind, "p": cents, "o": i, "k": kind},
        )


async def _own_service(db_session, tid: int, name: str, *, direction: int | None, decided: bool = True) -> int:
    sid = (
        await db_session.execute(
            text(
                "INSERT INTO services (name, is_public, created_by_trainer_id, direction_service_id, direction_decided_at) "
                "VALUES (:n, false, :t, :d, CASE WHEN :dec THEN now() END) RETURNING id"
            ),
            {"n": name, "t": tid, "d": direction, "dec": decided},
        )
    ).scalar_one()
    await _add_service(db_session, tid, int(sid), {"adult": 6000})
    return int(sid)


async def _completed_booking(db_session, tid: int, *, days_ago: int, self_booking: bool = False) -> None:
    if self_booking:
        await db_session.execute(
            text("UPDATE trainers SET telegram_id = COALESCE(telegram_id, :tg) WHERE id = :t"),
            {"t": tid, "tg": 7_000_000_000 + uuid.uuid4().int % 1_000_000_000},
        )
    tg = (await db_session.execute(text("SELECT telegram_id FROM trainers WHERE id = :t"), {"t": tid})).scalar()
    cid = (
        await db_session.execute(
            text("INSERT INTO clients (telegram_id) VALUES (:tg) RETURNING id"),
            {"tg": tg if self_booking else None},
        )
    ).scalar_one()
    slot = (
        await db_session.execute(
            text(
                "INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status) "
                "VALUES (:t, current_date - CAST(:d AS integer), '10:00', '11:00', 'booked') RETURNING id"
            ),
            {"t": tid, "d": days_ago},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status) "
            "VALUES (:s, :t, :c, (SELECT service_id FROM trainer_services WHERE trainer_id = :t ORDER BY service_id LIMIT 1), 'completed')"
        ),
        {"s": slot, "t": tid, "c": cid},
    )


@pytest.mark.asyncio
async def test_two_directions_tabs_week_prices_and_also_teaches(app_use_test_db, db_session) -> None:
    """Гаевский-подобный: «С нуля» + «Уже катаюсь», ролики — «Ещё ведёт», 7 оценок, неделя времени."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _add_service(
            db_session, tid, 1, {"two_children": 7500, "adult_and_child": 8000, "two_adults": 8500}
        )
        await _add_service(db_session, tid, 2, price_cents=5500, description="Ставлю ход и торможение.")
        await _add_service(db_session, tid, 5, price_cents=4000)
        bound = await _own_service(db_session, tid, "Постановка прыжков", direction=3)
        await _own_service(db_session, tid, "Растяжка для фигуристов", direction=None, decided=False)
        await db_session.execute(
            text(
                "UPDATE trainer_profiles SET rating_avg = 5, rating_count = 7, experience_years = 6, "
                "education = 'Высшее профильное', description = :d WHERE trainer_id = :t"
            ),
            {"t": tid, "d": "На коньках больше 20 лет.\nРаботал инструктором."},
        )
        for d, h in ((2, 12), (3, 10), (3, 15), (5, 12)):
            await _slot(db_session, tid, days=d, hour=h, arena_id=place["arena_id"])
        await _completed_booking(db_session, tid, days_ago=40, self_booking=True)
        await _completed_booking(db_session, tid, days_ago=10)
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text

    assert bound
    # Вкладки — направления тренера в порядке каталога; своя услуга — во вкладке своего направления.
    tabs = re.findall(r'<button type="button" data-dir="(\w+)"[^>]*>([^<]+)</button>', html)
    assert tabs == [("zero", "С нуля"), ("better", "Уже катаюсь"), ("fig", "Фигурное")]
    assert 'data-dir-panel="better" hidden' in html
    assert "Постановка прыжков" in html
    # Ролики (не вкладка) и неразобранная своя услуга — «Ещё ведёт» словами тренера.
    assert "Ещё ведёт: Катание на роликах, Растяжка для фигуристов." in html
    # Первый экран: стаж, строка направлений и аудитории, оценка от 3, галочки из анкеты.
    assert "Тренирует 6 лет" in html
    assert "С нуля, для тех, кто уже катается и фигурное катание. Дети и взрослые." in html
    assert "<span>· 7 оценок</span>" in html and "7 оценок — все на 5 из 5" in html
    assert "<li>Высшее профильное образование</li>" in html and f"<li>Каток: {place['name']}</li>" in html
    # «В Glide с» — месяц первой состоявшейся записи; запись тренера к себе (40 дней назад) не в счёт.
    from datetime import date, timedelta

    from src.application.site_trainer_page import _MONTHS_GEN

    since = date.today() - timedelta(days=10)
    assert f"В Glide с {_MONTHS_GEN[since.month - 1]} {since.year}" in html
    # Число занятий не показываем никогда.
    assert not re.search(r"\d+\s*заняти", html)
    # Три ближайших времени и неделя: 4 слота, 7 дней, у пустых — «нет окон».
    near = html.split('class="tp-near"', 1)[1].split("</div>", 1)[0]
    assert near.count("<a ") == 3 and "<small>" in near
    week = html.split('class="tp-week"', 1)[1].split("</section>", 1)[0]
    assert week.count('class="tp-slot"') == 4
    assert week.count("tp-day") >= 7 and week.count("нет окон") == 4
    # Цены списком: все тарифы, «на двоих» тоже; слова тренера к услуге — дословно.
    prices = html.split(">Цены</h2>", 1)[1].split("</section>", 1)[0]
    for label in ("Ребёнок", "Взрослый", "Двое детей", "Взрослый + ребёнок", "Двое взрослых"):
        assert f"<dt>{label}</dt>" in prices
    assert "<dt>Занятие</dt><dd>55 BYN</dd>" in prices and "Ставлю ход и торможение." in prices
    assert "<h3>Катание на роликах</h3>" in prices
    assert "Билет на каток покупается отдельно, на кассе." in prices
    assert "На коньках больше 20 лет.\nРаботал инструктором." in html
    # «Написать» в карточке и под неделей — с учётом клика.
    assert html.count("data-catalog-phone-beacon=") == 2
    assert "Напишите тренеру — он предложит своё." in html
    # Перед первым занятием — вопросы направления «С нуля», ссылка — на каталог направления.
    assert "Перед первым занятием" in html and "Мне 35 — не поздно начинать?" in html
    assert "/trenery/s-nulya" in html
    assert "окн" not in html.split("<main", 1)[1].split("</main>", 1)[0].lower().replace("окна", "")


@pytest.mark.asyncio
async def test_few_ratings_hidden_and_no_photo_shows_letter(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_CRM)
        await db_session.execute(text("DELETE FROM trainer_photos WHERE trainer_id = :t"), {"t": tid})
        await db_session.execute(
            text("UPDATE trainer_profiles SET rating_avg = 5, rating_count = 2 WHERE trainer_id = :t"), {"t": tid}
        )
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
    assert "tp-photo" not in html and 'class="tp-ava tp-ava--mono"' in html
    assert "★" not in html and "Оценки учеников" not in html and "оценк" not in html.lower().replace("оценить", "")
    assert "В Glide с" not in html
    assert "Онлайн-записи нет — напишите и договоритесь о времени." in html
    assert "Нужен Telegram — переписка идёт там." in html


@pytest.mark.asyncio
async def test_own_link_puts_time_on_top_without_selling_blocks(app_use_test_db, db_session) -> None:
    """``?via=link`` — свои ученики тренера: без фото на весь экран, оценок, других тренеров и «Тренируете?»."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await db_session.execute(
            text("UPDATE trainer_profiles SET rating_avg = 5, rating_count = 7 WHERE trainer_id = :t"), {"t": tid}
        )
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        own = (await client.get(f"{trainer_path(tid, name)}?via=link")).text
        plain = (await client.get(trainer_path(tid, name))).text
    assert "Тренируете" in plain and "tp-photo" in plain and "Оценки учеников" in plain
    assert "Тренируете" not in own and "tp-photo" not in own and "Оценки учеников" not in own
    assert "Ещё тренеры" not in own
    # Время и запись — через постоянную ссылку тренера (бот привяжет ученика).
    assert "Ближайшее время — записаться" in own
    assert f"start=welcome_ref_{tid}" in own


@pytest.mark.asyncio
async def test_peers_of_the_same_direction_in_city(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        other = await _trainer_on(db_session, client, place, first_name=f"Влад{uuid.uuid4().hex[:4]}")
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
    more = html.split('class="tp-more"', 1)[1].split("</section>", 1)[0]
    assert f"/t/{other}-" in more and "от 45 BYN" in more and place["name"] in more
    assert f"/t/{tid}-" not in more
    assert "Здесь же ещё 1 тренер" in html


@pytest.mark.asyncio
async def test_no_individual_windows_text_does_not_claim_no_time_at_all(app_use_test_db, db_session) -> None:
    """Групповой слот в публичные окна не входит (семантика /client/slots) — текст не утверждает «времени нет»."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"], capacity=4)
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
    assert "Индивидуального свободного времени на этой неделе нет — напишите тренеру." in html
    assert "свободного времени нет." not in html.replace("Индивидуального свободного времени на этой неделе нет", "")
    assert 'class="tp-slot"' not in html


@pytest.mark.asyncio
async def test_link_and_share_pages_carry_the_slot_into_the_bot_payload(app_use_test_db, db_session) -> None:
    """``?via=link``/``share``: время ведёт в бота со слотом (``..._s_<slot>``), основная кнопка — прежняя ссылка."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        sid = await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        own = (await client.get(f"{trainer_path(tid, name)}?via=link")).text
        shared = (await client.get(f"{trainer_path(tid, name)}?via=share")).text
    assert f"start=welcome_ref_{tid}_s_{sid}" in own and f"start=share_ref_{tid}_s_{sid}" in shared
    async with _client() as client:
        place2, tid2, name2 = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        bare = (await client.get(f"{trainer_path(tid2, name2)}?via=link")).text
    # Без окон слота нет — прежняя постоянная ссылка.
    assert f'start=welcome_ref_{tid2}"' in bare
