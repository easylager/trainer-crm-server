"""Отзывы о тренере: текст виден публично только после «Подтвердить» в админ-боте; секция на сайте — от 3 отзывов."""
from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.review_moderation_notify import format_review_card, review_keyboard
from src.application.review_moderation_use_cases import (
    ReviewModerationError,
    display_name,
    list_pending_reviews,
    moderate_review,
)
from src.application.site_trainer_page import trainer_path
from src.application.trainer_use_cases import add_trainer_rating, list_public_trainer_reviews
from tests.api.test_site_trainer_page import SUBSCRIPTION_TIER_ONLINE, _listed, _slot


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")


def _tg() -> int:
    return int(uuid.uuid4().int % 10**9) + 10**9


async def _rating_id(db_session, tid: int, tg: int) -> int:
    return int(
        (await db_session.execute(text("SELECT id FROM trainer_ratings WHERE trainer_id=:t AND client_telegram_id=:c"), {"t": tid, "c": tg})).scalar()
    )


def test_display_name_is_first_name_and_last_initial() -> None:
    assert display_name("Марк", "Миронов") == "Марк М."
    assert display_name("Андрей", None) == "Андрей"
    assert display_name(None, "Иванов") == "Ученик"


def test_review_card_has_both_buttons_and_escapes_html() -> None:
    card = format_review_card({"id": 5, "rating": 4, "trainer_name": "Анна <b>", "client_name": "Марк М.", "review_text": "Супер & <i>класс</i>"})
    assert "Анна &lt;b&gt;" in card and "Супер &amp; &lt;i&gt;класс&lt;/i&gt;" in card and "★★★★☆" in card
    cb = [b.callback_data for b in review_keyboard(5).inline_keyboard[0]]
    assert cb == ["rvm:ok:5", "rvm:no:5"]


@pytest.mark.asyncio
async def test_text_review_waits_for_moderation_and_is_hidden_until_approved(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place, tid, _name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
    tg = _tg()
    await add_trainer_rating(db_session, tid, tg, 5, review_text=None)
    await add_trainer_rating(db_session, tid, tg, 5, review_text="Отличный тренер, ребёнок в восторге")
    rid = await _rating_id(db_session, tid, tg)
    status = (await db_session.execute(text("SELECT review_status FROM trainer_ratings WHERE id=:i"), {"i": rid})).scalar()
    assert status == "pending" and rid in await list_pending_reviews(db_session, limit=500)
    # Звезда считается сразу, текст — нет.
    items, total = await list_public_trainer_reviews(db_session, tid)
    assert total == 1 and items[0]["rating"] == 5 and items[0]["review_text"] is None

    await moderate_review(db_session, rid, approve=True, admin_id=1)
    items, _ = await list_public_trainer_reviews(db_session, tid)
    assert items[0]["review_text"] == "Отличный тренер, ребёнок в восторге"
    with pytest.raises(ReviewModerationError) as e:
        await moderate_review(db_session, rid, approve=False, admin_id=1)
    assert e.value.code == "closed"

    # Правка текста возвращает отзыв на проверку; правка без текста статус не трогает.
    await add_trainer_rating(db_session, tid, tg, 5, review_text="Совсем другой текст")
    assert (await db_session.execute(text("SELECT review_status FROM trainer_ratings WHERE id=:i"), {"i": rid})).scalar() == "pending"
    await add_trainer_rating(db_session, tid, tg, 4, review_text=None)
    assert (await db_session.execute(text("SELECT review_status FROM trainer_ratings WHERE id=:i"), {"i": rid})).scalar() == "pending"


@pytest.mark.asyncio
async def test_reject_keeps_text_off_the_site(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place, tid, _name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
    tg = _tg()
    await add_trainer_rating(db_session, tid, tg, 2, review_text="Резкий текст")
    rid = await _rating_id(db_session, tid, tg)
    await moderate_review(db_session, rid, approve=False, admin_id=1)
    items, _ = await list_public_trainer_reviews(db_session, tid)
    assert items[0]["review_text"] is None


async def _page(db_session, texts_by_status: list[tuple[str, str]]):
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        for i, (status, body) in enumerate(texts_by_status):
            tg = _tg()
            await add_trainer_rating(db_session, tid, tg, 5, review_text=body)
            rid = await _rating_id(db_session, tid, tg)
            await db_session.execute(text("UPDATE trainer_ratings SET review_status=:s WHERE id=:i"), {"s": status, "i": rid})
        await db_session.commit()
        return (await client.get(trainer_path(tid, name))).text


@pytest.mark.asyncio
async def test_site_section_needs_three_approved_reviews(app_use_test_db, db_session) -> None:
    two = await _page(db_session, [("approved", "Хороший тренер, рекомендую"), ("approved", "Всё понравилось, придём ещё")])
    assert 'id="reviews"' not in two
    four = await _page(
        db_session,
        [("approved", "Первый отзыв про занятия"), ("approved", "Второй отзыв про занятия"), ("approved", "Третий отзыв про занятия"),
         ("pending", "Ещё не проверен"), ("rejected", "Отклонённый текст")],
    )
    assert 'id="reviews"' in four and '<h2 class="b-h2 tp-h2">Отзывы</h2>' in four
    assert four.count('<article class="tp-rev">') == 3
    assert "Ещё не проверен" not in four and "Отклонённый текст" not in four
    assert 'href="#reviews"' in four  # звёзды в шапке ведут к отзывам
    assert "Каждый отзыв проверяем перед публикацией" in four


def test_completed_lesson_message_has_one_tap_stars() -> None:
    from src.bot.messages import build_client_booking_completed_inline_keyboard

    kb = build_client_booking_completed_inline_keyboard(
        webapp_base_url="https://x.example", trainer_id=3, booking_id=77, trainer_telegram_id=None, show_repeat_row=False
    )
    first = kb.inline_keyboard[0]
    assert [b.callback_data for b in first] == [f"feedback_rating:77:{n}" for n in range(1, 6)]
