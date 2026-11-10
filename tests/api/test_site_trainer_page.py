"""TASK-350/356: страница тренера ``/t/{id}-{slug}`` — та же логика, что у карточки тренера в Mini App.

TASK-356 (PDEC-033, ``design/trainer.html``): карточка цены с вкладками направлений и ближайшим
временем, неделя, цены по тарифам, «Ещё ведёт», оценка с первой, «В Glide с …», без числа занятий.
"""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.site_trainer_page import _panel_html, _price_card, parse_trainer_ref, trainer_path, trainer_slug
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
@pytest.mark.asyncio
async def test_trainer_page_og_type_is_profile(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        html = (await client.get(trainer_path(tid, name))).text
    assert 'property="og:type" content="profile"' in html


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
    assert f'<h1 class="tp-name">{name}<span class="tp-trade"> — тренер по катанию на коньках' in html
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
    # Вордмарк в шапке — «Glide», не «Glideclub».
    assert '<a class="b-brand" href="/">Glide</a>' in html
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
    assert '<h2 class="b-h2 tp-h2">Занятия и цены</h2>' in html and "45\u00a0BYN" in html


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
    assert (
        f'rel="canonical" href="https://glide.example{link.replace("https://glide.example", "").split("?")[0]}"'
        in shared
    )


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
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents, description, client_notice) VALUES (:t, :s, :p, :d, :n) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "t": tid,
            "s": service_id,
            "p": cols.get("price_cents"),
            "d": cols.get("description"),
            "n": cols.get("client_notice"),
        },
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
        await _add_service(db_session, tid, 1, {"two_children": 7500, "adult_and_child": 8000, "two_adults": 8500})
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
    # Первый экран: стаж, строка направлений и аудитории, оценка с первой, галочки из анкеты.
    assert "Тренирует 6 лет" in html
    assert "Занятия с нуля, для уже катающихся и по фигурному катанию. Дети и взрослые." in html
    assert "<span>· 7 оценок</span>" in html and "7 оценок — все на 5 из 5" in html
    assert "AggregateRating" not in html
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
    prices = html.split(">Занятия и цены</h2>", 1)[1].split("</section>", 1)[0]
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
async def test_one_five_star_rating_says_one_not_all_fives(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_CRM)
        await db_session.execute(
            text("UPDATE trainer_profiles SET rating_avg = 5, rating_count = 1 WHERE trainer_id = :t"), {"t": tid}
        )
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
    assert "1 оценка — 5 из 5" in html
    assert "все на 5 из 5" not in html


@pytest.mark.asyncio
async def test_two_ratings_shown_and_no_photo_shows_letter(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_CRM)
        await db_session.execute(text("DELETE FROM trainer_photos WHERE trainer_id = :t"), {"t": tid})
        await db_session.execute(
            text("UPDATE trainer_profiles SET rating_avg = 5, rating_count = 2 WHERE trainer_id = :t"), {"t": tid}
        )
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
    assert "tp-photo" not in html and 'class="tp-ava tp-ava--mono"' in html
    assert "★" in html and "<span>· 2 оценки</span>" in html
    assert "AggregateRating" not in html and "0 оценок" not in html
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
    assert f"/t/{other}-" in more and "от 25 BYN" in more and place["name"] in more
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
    # Тренер из каталога: главное действие — заявка (в Telegram), «Написать» остаётся ниже.
    assert "Индивидуального свободного времени на этой неделе нет — оставьте заявку" in html
    assert "свободного времени нет." not in html.replace("Индивидуального свободного времени на этой неделе нет", "")
    assert 'class="tp-slot"' not in html
    assert "_i_request" in html and ">Оставить заявку</a>" in html
    assert "Написать тренеру" in html


def test_price_card_no_windows_without_nick_does_not_promise_write() -> None:
    """Без ника: текст не говорит «напишите», кнопка «Написать» скрыта, Telegram-выход остаётся."""
    html = _price_card(
        {"id": 9, "can_book": True, "windows": [], "directions": [], "contact_url": None, "phone": None},
        app="https://t.me/bot",
        cta=None,
        via=None,
    )
    assert "напишите тренеру" not in html
    assert "следующие недели видны в Telegram" in html
    assert "Следующие недели — в Telegram" in html
    assert "Написать тренеру" not in html


def test_price_card_no_windows_with_nick_keeps_write_cta() -> None:
    html = _price_card(
        {"id": 9, "can_book": True, "windows": [], "directions": [], "contact_url": "/r/tg/9", "phone": None},
        app="https://t.me/bot",
        cta=None,
        via=None,
    )
    assert "напишите тренеру" in html
    assert "Написать тренеру" in html


def test_price_card_phone_copy_and_free_card_copy_honesty() -> None:
    with_phone = _price_card(
        {"id": 9, "can_book": False, "windows": [], "directions": [], "contact_url": None, "phone": "+375291112233"},
        app=None,
        cta=("Открыть в Telegram", "https://t.me/bot"),
        via=None,
    )
    assert 'data-copy="+375291112233"' in with_phone
    assert "Скопировать телефон" in with_phone
    assert "напишите и договоритесь" not in with_phone
    assert "позвоните или откройте Telegram" in with_phone

    no_contact = _price_card(
        {"id": 9, "can_book": False, "windows": [], "directions": [], "contact_url": None, "phone": None},
        app=None,
        cta=("Открыть в Telegram", "https://t.me/bot"),
        via=None,
    )
    assert "напишите и договоритесь" not in no_contact
    assert "откройте Telegram и договоритесь" in no_contact


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


def test_role_line_reads_as_one_grammatical_phrase_for_every_combination() -> None:
    from src.application.catalog_directions import DIRECTIONS
    from src.application.site_trainer_page import _role_line

    by = {d.slug: d for d in DIRECTIONS}
    zero, better, hockey, fig = by["s-nulya"], by["uzhe-katayus"], by["s-klyushkoy"], by["figurnoe"]
    assert _role_line([zero]) == "Занятия с нуля."
    assert _role_line([better]) == "Занятия для уже катающихся."
    assert _role_line([fig]) == "Занятия по фигурному катанию."
    assert _role_line([zero, fig]) == "Занятия с нуля и по фигурному катанию."
    assert _role_line([zero, better]) == "Занятия с нуля и для уже катающихся."
    assert _role_line([zero, better, fig]) == "Занятия с нуля, для уже катающихся и по фигурному катанию."
    assert _role_line([zero, better, fig, hockey]) == (
        "Занятия с нуля, для уже катающихся, по фигурному катанию и по хоккейному катанию."
    )
    assert _role_line([]) == ""


# ── Подача услуг: крючок, описание, слова тренера, «не входит в цену» ─

HOOK_ZERO = "Если вы почти не стояли на льду или давно не катались — это про вас."
HOOK_BETTER = "Уже катаетесь, но хочется увереннее, ровнее и «красивее» на льду."
HOOK_HOCKEY = "Взрывной старт, маневренность"
HOOK_OHM = "Узкий формат для игроков"


@pytest.mark.asyncio
async def test_card_panels_show_their_own_hook_and_two_services_get_titles(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _add_service(db_session, tid, 1, price_cents=5000)
        await _add_service(db_session, tid, 2, {"child": 5000, "adult": 5500})
        await _add_service(db_session, tid, 4, price_cents=5000)
        await _add_service(db_session, tid, 6, price_cents=5000)
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
    card = html.split('class="tp-pcard', 1)[1].split("</section>", 1)[0]
    zero = card.split('data-dir-panel="zero"', 1)[1].split('data-dir-panel="better"', 1)[0]
    better = card.split('data-dir-panel="better"', 1)[1].split('data-dir-panel="hock"', 1)[0]
    hockey = card.split('data-dir-panel="hock"', 1)[1]
    assert f'<p class="tp-hook">{HOOK_ZERO}</p>' in zero and HOOK_BETTER not in zero
    assert f'<p class="tp-hook">{HOOK_BETTER}</p>' in better and HOOK_ZERO not in better
    # Хук стоит над ценами; название одной услуги во вкладке не повторяется.
    assert zero.index("tp-hook") < zero.index("tp-tiers") and "tp-svc__name" not in zero
    assert "Ребёнок" in better and "Взрослый" in better
    # Две услуги вкладки: название (service_title), крючок и цены у каждой.
    assert hockey.count('class="tp-svc"') == 2
    assert '<span class="tp-svc__name">ОХМ — отработка хоккейного мастерства</span>' in hockey
    assert '<span class="tp-svc__name">Хоккейное катание</span>' in hockey
    assert HOOK_HOCKEY in hockey and HOOK_OHM in hockey


def test_panel_with_two_services_puts_prices_on_one_line_and_cuts_hook_on_word() -> None:
    long_hook = "Хоккейная стойка, ход, повороты и торможения без лишней теории " * 3
    html = _panel_html(
        [
            {
                "title": "Хоккейное катание",
                "hook": long_hook,
                "card_prices": [("Ребёнок", "50 BYN"), ("Взрослый", "55 BYN")],
            },
            {"title": "ОХМ", "hook": "Коротко.", "card_prices": [("Дети и взрослые", "50 BYN")]},
        ]
    )
    assert html.count('class="tp-svc"') == 2
    assert "Ребёнок <b>50 BYN</b> · Взрослый <b>55 BYN</b>" in html
    assert "Дети и взрослые <b>50 BYN</b>" in html
    assert "tp-tiers" not in html
    hook = re.search(r'<p class="tp-hook">([^<]*)</p>', html).group(1)
    assert hook.endswith("…") and len(hook) <= 112
    assert hook[:-1].split(" ")[-1] in long_hook.split(" ")  # последнее слово целое


def test_panel_with_one_service_keeps_big_tiers() -> None:
    html = _panel_html([{"title": "С нуля", "hook": "Крючок.", "card_prices": [("Дети и взрослые", "50 BYN")]}])
    assert "tp-tiers" in html and "tp-prices" not in html and "tp-svc__name" not in html


@pytest.mark.asyncio
async def test_prices_section_presents_service_words_and_notice(app_use_test_db, db_session) -> None:
    words = "Подойдет для тех, кто ни разу не стоял на льду <b>& «катается» вдоль бортика"
    async with _client() as client:
        _place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _add_service(db_session, tid, 1, price_cents=5000)
        await db_session.execute(
            text(
                "UPDATE trainer_services SET description = :d, client_notice = :n WHERE trainer_id = :t AND service_id = 1"
            ),
            {"t": tid, "d": words, "n": "В стоимость не входят: прокат коньков, билеты <на> лёд & «всё»."},
        )
        await _add_service(db_session, tid, 2, price_cents=5500)
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
    sec = html.split(">Занятия и цены</h2>", 1)[1].split("</section>", 1)[0]
    zero = sec.split("<h3>С нуля</h3>", 1)[1].split("<h3>", 1)[0]
    better = sec.split("<h3>Уже катаюсь</h3>", 1)[1]
    assert f'<p class="tp-lead">{HOOK_ZERO}</p>' in zero
    # Слова тренера — дословно (с экранированием), с подписью; подписи без имени.
    assert "<figcaption>Слова тренера</figcaption>" in zero
    assert "Подойдет для тех, кто ни разу не стоял на льду &lt;b&gt;&amp; «катается» вдоль бортика" in zero
    assert "<b>& " not in zero
    # «Не входит в цену»: зачин заметки не дублируется, текст экранирован.
    assert "<b>Не входит в цену:</b> прокат коньков, билеты &lt;на&gt; лёд &amp; «всё»." in zero
    assert "В стоимость не входят" not in sec
    # Нет слов тренера и заметки — нет блоков.
    assert "Слова тренера" not in better and "Не входит в цену" not in better


@pytest.mark.asyncio
async def test_own_service_has_no_directory_text_and_empty_data_shows_no_blocks(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _own_service(db_session, tid, "Постановка прыжков", direction=3)
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
    assert "Постановка прыжков" in html
    fig = html.split('data-dir-panel="fig"', 1)[1].split("</div></div>", 1)[0]
    assert "tp-hook" not in fig
    sec = html.split(">Занятия и цены</h2>", 1)[1].split("</section>", 1)[0]
    own = sec.split("<h3>Фигурное</h3>", 1)[1]
    assert "<h4" in own and "tp-lead" not in own and "tp-words" not in own
    assert "Слова тренера" not in own and "Не входит в цену" not in own
    assert "Повороты, прыжки, вращения" not in html


def test_notice_text_strips_only_the_leading_phrase() -> None:
    from src.application.site_trainer_page import _notice_text

    assert _notice_text("В стоимость не входят: прокат.") == "прокат."
    assert _notice_text("  В цену не входит билет") == "билет"
    assert _notice_text("Коньки берите свои") == "Коньки берите свои"
    assert _notice_text(None) == ""


def test_week_starts_on_first_day_with_time_not_on_empty_today() -> None:
    """Сегодня окон нет — неделя начинается с завтра: первым экраном не «нет окон»."""
    from datetime import date as _date

    from src.application.site_trainer_page import _week_html

    page = {
        "can_book": True,
        "today": _date(2026, 11, 8),
        "contact_url": None,
        "windows": [{"starts_at": "2026-11-09T10:15:00", "time": "10:15", "slot_id": 1}],
    }
    html = _week_html(page, "https://t.me/bot", None)
    first = html.split('class="tp-day', 2)[1]
    assert '<span class="tp-d">9</span>' in first and "нет окон" not in first
    assert "tp-day--today" not in html


def test_bookable_card_has_one_primary_cta_on_nearest_time() -> None:
    from datetime import date as _date

    html = _price_card(
        {
            "id": 9,
            "can_book": True,
            "today": _date(2026, 11, 8),
            "directions": [],
            "contact_url": "/r/tg/9",
            "phone": None,
            "windows": [
                {"starts_at": "2026-11-09T10:15:00", "time": "10:15", "slot_id": 1, "book_href": "https://t.me/b?s=1"}
            ],
        },
        app="https://t.me/bot",
        cta=None,
        via=None,
    )
    assert html.count("tp-btn--teal") == 1 and 'href="https://t.me/b?s=1" rel="nofollow">Записаться на' in html
    assert "Написать тренеру" in html and "tp-btn--tg" not in html


def test_horizontal_strip_gets_scroll_arrows_hooked_to_page_script() -> None:
    from src.application.site_trainer_page import _SCROLLER_SCRIPT, _scroller

    html = _scroller('<div class="tp-more">x</div>')
    assert html.startswith('<div class="tp-scroller" data-scroller><div class="tp-more">')
    assert "tp-arrow--prev" in html and "tp-arrow--next" in html
    assert "data-scroller" in _SCROLLER_SCRIPT and "has-next" in _SCROLLER_SCRIPT


def _week_cells(html: str) -> list[str]:
    week = html.split('<div class="tp-week">', 1)[1].split('<div class="tp-request">', 1)[0]
    return re.split(r'(?=<div class="tp-day)', week)[1:]


@pytest.mark.asyncio
async def test_week_shows_every_day_of_the_grid_when_today_has_no_slots(app_use_test_db, db_session) -> None:
    """Сетка стартует с первого дня с окнами (не с сегодня): её последний день не должен теряться."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        for d in range(1, 8):  # завтра … через 7 дней, на сегодня окон нет
            await _slot(db_session, tid, days=d, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text

    cells = _week_cells(html)
    assert len(cells) == 7
    assert [c for c in cells if "tp-day--empty" in c] == []


@pytest.mark.asyncio
async def test_week_keeps_last_day_for_a_busy_trainer(app_use_test_db, db_session) -> None:
    """Много слотов в день: общий лимит окон не должен съедать конец недели."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        for d in range(1, 8):
            for h in range(7, 17):  # 10 слотов в день, 70 за неделю
                await _slot(db_session, tid, days=d, hour=h, arena_id=place["arena_id"])
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text

    cells = _week_cells(html)
    assert len(cells) == 7
    assert cells[-1].count('class="tp-slot"') == 10


@pytest.mark.asyncio
async def test_price_cards_link_to_the_week_grid_when_there_are_slots(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text

    prices = html.split('<h2 class="b-h2 tp-h2">Занятия и цены</h2>', 1)[1]
    assert 'id="time"' in html
    assert prices.count('<a class="tp-go" href="#time">') == prices.count('<div class="tp-card">') >= 1


@pytest.mark.asyncio
async def test_price_cards_offer_write_and_phone_when_there_is_no_week_grid(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_CRM)
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text

    prices = html.split('<h2 class="b-h2 tp-h2">Занятия и цены</h2>', 1)[1]
    assert 'id="time"' not in html and 'href="#time"' not in html
    assert "Остались вопросы?" in prices and "Написать тренеру" in prices


@pytest.mark.asyncio
async def test_save_heart_leads_to_telegram_and_is_absent_on_trainers_own_link(app_use_test_db, db_session) -> None:
    """«Сохранить» — сердце в шапке со ссылкой ``_i_save``; по личной ссылке тренера (``via=link``) карточка Mini App недоступна."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
        own = (await client.get(trainer_path(tid, name) + "?via=link")).text

    m = re.search(r'<a class="tp-save" href="([^"]+)"', html)
    assert m and f"startapp=trainer_{tid}_i_save" in m.group(1).replace("&amp;", "&")
    assert 'class="tp-save"' not in own and "_i_request" not in own


@pytest.mark.asyncio
async def test_page_title_names_the_only_direction_and_snippet_price_matches_the_card(
    app_use_test_db, db_session, monkeypatch
) -> None:
    from src.shared import city_locative
    from tests.api.test_site_trainer_catalog import _set_services

    def meta(html: str) -> tuple[str, str]:
        title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
        description = re.search(r'name="description" content="([^"]*)"', html).group(1)
        return title.replace("\xa0", " "), description.replace("\xa0", " ")

    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=None)
        monkeypatch.setitem(city_locative._LOCATIVE, place["city_name"], "Плейсске")
        path = trainer_path(tid, name)
        # Одно направление (фигурное): групповая 25 дешевле тарифа 50 и абонемента 41,87.
        await _set_services(db_session, tid, {3: [("adult", 5000)]})
        await db_session.execute(
            text("UPDATE trainer_services SET group_price_cents = 2500 WHERE trainer_id = :t"), {"t": tid}
        )
        await db_session.commit()
        title, description = meta((await client.get(path)).text)
        assert title.startswith(f"{name} — тренер по фигурному катанию в Плейсске")
        assert "От 25 BYN в группе, запись в Telegram." in description and "за занятие" not in description

        # Групповой нет — минимум даёт абонемент 670/16.
        await db_session.execute(text("UPDATE trainer_services SET group_price_cents = NULL WHERE trainer_id = :t"), {"t": tid})
        await db_session.commit()
        description = meta((await client.get(path)).text)[1]
        assert "От 41,87 BYN по абонементу, запись в Telegram." in description and "за занятие" not in description

        # Абонемента нет — обычное занятие.
        await db_session.execute(text("DELETE FROM trainer_pass_products WHERE trainer_id = :t"), {"t": tid})
        await db_session.commit()
        description = meta((await client.get(path)).text)[1]
        assert "От 50 BYN за занятие, запись в Telegram." in description

        # Два направления — общий шаблон.
        await _set_services(db_session, tid, {3: [("adult", 5000)], 4: [("adult", 5500)]})
        await db_session.commit()
        title = meta((await client.get(path)).text)[0]
        assert title.startswith(f"{name} — тренер по катанию на коньках в Плейсске")
