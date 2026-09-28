"""
The «Каталог» section API (TASK-140, AC-009/011/012/014).

The screen exists to answer «в каталоге я или нет, и что с этим делать», so these tests check the
payload actually carries that answer — state, reason, both versions of a pending edit, the soft
warnings, and the history — and that each action lands in the state machine rather than writing
the column behind its back.
"""
from __future__ import annotations

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.trainer_catalog_state import (
    CATALOG_ACTOR_MODERATOR,
    REASON_BACKFILL_0206,
    REASON_MODERATOR_APPROVED,
    REASON_TRAINER_SUBMITTED,
    set_catalog_state,
)
from src.application.trainer_use_cases import create_trainer
from src.shared.catalog_visibility import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
)
from tests.api.test_webapp_trainer_miniapp_profile_integration import (
    _fresh_trainer_telegram_id,
    patch_trainer_init_auth,
)
from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids

HEADERS = {"X-Telegram-Init-Data": "mock"}


async def _complete_trainer(db_session, *, published: bool = False) -> tuple[int, int]:
    """A trainer whose card meets the submission bar. Returns (trainer_id, telegram_id)."""
    sid, cid, aid = await _require_seed_ids(db_session)
    if aid is None:
        pytest.skip("need a seeded arena")
    tid = await create_trainer(
        db_session,
        profile={
            "first_name": "Карточка",
            "last_name": f"Тест{uuid.uuid4().hex[:5]}",
            "phone": "+375291110099",
            "city_id": cid,
            "description": "d" * 40,
            "education": "Высшее",
            "experience_years": 4,
            "session_duration_minutes": 45,
            "min_hours_before_booking": 3,
        },
        service_ids=[sid],
        arena_ids=[aid],
    )
    await db_session.execute(
        text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:t, :fk, 0)"),
        {"t": tid, "fk": f"trainers/{tid}/a.jpg"},
    )
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg, status = 'active' WHERE id = :t"),
        {"tg": tg, "t": tid},
    )
    await db_session.commit()
    if published:
        await set_catalog_state(
            db_session, tid, CATALOG_STATE_PENDING_REVIEW,
            reason=REASON_TRAINER_SUBMITTED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
        )
        await set_catalog_state(
            db_session, tid, CATALOG_STATE_PUBLISHED,
            reason=REASON_MODERATOR_APPROVED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
        )
    return tid, tg


async def _get(tg: int) -> dict:
    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/webapp/trainer/catalog", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _post(tg: int, path: str) -> tuple[int, dict]:
    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/api/webapp/trainer/catalog/{path}", headers=HEADERS)
    try:
        return resp.status_code, resp.json()
    except Exception:  # noqa: BLE001
        return resp.status_code, {}


@pytest.mark.asyncio
async def test_draft_screen_explains_the_catalog_and_offers_to_publish(app_use_test_db, db_session) -> None:
    _, tg = await _complete_trainer(db_session)
    body = await _get(tg)
    assert body["state"] == CATALOG_STATE_DRAFT
    assert body["headline"] and body["body"]
    assert "submit" in body["actions"]
    # The fear this line exists to remove.
    assert "подписка" in body["subscription_note"].lower()


@pytest.mark.asyncio
async def test_published_screen_carries_preview_and_history(app_use_test_db, db_session) -> None:
    _, tg = await _complete_trainer(db_session, published=True)
    body = await _get(tg)
    assert body["state"] == CATALOG_STATE_PUBLISHED
    assert body["actions"] == ["hide"]
    preview = body["preview"]
    assert preview["first_name"] == "Карточка"
    assert preview["photo_file_key"]
    # Набор фактов — ровно тот, что рисует клиентский список (catalog-main.js): услуга с ценой,
    # площадки, свободные слоты. Города там нет — он фильтр, а не факт карточки, и превью с ним
    # показывало тренеру карточку, которой в каталоге не существует.
    assert "city_name" not in preview
    assert preview["service_line"]
    assert preview["arena_names"]
    assert isinstance(preview["free_slots_14d"], int)
    # History is what makes «следить, что я в каталоге» possible at all.
    assert [e["to_state"] for e in body["events"]][:2] == [
        CATALOG_STATE_PUBLISHED,
        CATALOG_STATE_PENDING_REVIEW,
    ]


@pytest.mark.asyncio
async def test_submit_requires_a_complete_card_and_reports_gaps(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session)
    await db_session.execute(
        text("UPDATE trainer_profiles SET phone = '' WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.commit()
    status, body = await _post(tg, "submit")
    assert status == 422
    detail = body["detail"]
    assert "phone" in (detail.get("missing_fields") or [])
    assert any("телефон" in label for label in detail.get("missing_labels_ru") or [])


@pytest.mark.asyncio
async def test_submit_then_hide_then_restore_round_trip(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session)

    status, body = await _post(tg, "submit")
    assert status == 200, body
    assert body["state"] == CATALOG_STATE_PENDING_REVIEW
    assert body["actions"] == ["withdraw"]

    # A moderator approves; then the trainer takes it down and puts it back.
    await set_catalog_state(
        db_session, tid, CATALOG_STATE_PUBLISHED,
        reason=REASON_MODERATOR_APPROVED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
    )
    status, body = await _post(tg, "hide")
    assert status == 200, body
    assert body["state"] == CATALOG_STATE_HIDDEN

    status, body = await _post(tg, "restore")
    assert status == 200, body
    # Straight back, no second review: the dialog promises exactly this.
    assert body["state"] == CATALOG_STATE_PUBLISHED


@pytest.mark.asyncio
async def test_restore_from_paused_returns_422_while_the_gap_is_open(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session, published=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET phone = '' WHERE trainer_id = :t"), {"t": tid}
    )
    await set_catalog_state(
        db_session, tid, CATALOG_STATE_PAUSED,
        reason="missing_fields", actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
    )
    await db_session.commit()
    status, body = await _post(tg, "restore")
    assert status == 422
    assert "phone" in (body["detail"].get("missing_fields") or [])


@pytest.mark.asyncio
async def test_withdraw_clears_the_queue_stamp(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session)
    await _post(tg, "submit")
    status, body = await _post(tg, "withdraw")
    assert status == 200, body
    assert body["state"] == CATALOG_STATE_DRAFT
    r = await db_session.execute(
        text("SELECT moderation_submitted_at FROM trainers WHERE id = :t"), {"t": tid}
    )
    assert r.scalar() is None


@pytest.mark.asyncio
async def test_pending_revision_shows_both_versions_and_can_be_cancelled(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session, published=True)
    await db_session.execute(
        text(
            "UPDATE trainers SET photo_pending = CAST(:js AS jsonb) WHERE id = :t"
        ),
        {"t": tid, "js": json.dumps({"file_key": f"trainers/{tid}/new.jpg"})},
    )
    await db_session.commit()

    body = await _get(tg)
    revision = body["revision"]
    assert revision is not None and revision["has_photo"] is True
    # The thing the trainer could never see before: what clients are looking at *right now*.
    assert revision["current"]["photo_file_key"] != revision["next"]["photo_file_key"]
    assert body["state"] == CATALOG_STATE_PUBLISHED, "a pending edit must not unpublish the card"

    status, after = await _post(tg, "cancel-revision")
    assert status == 200, after
    assert after["revision"] is None


@pytest.mark.asyncio
async def test_hidden_arenas_warn_without_unpublishing(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session, published=True)
    await db_session.execute(
        text("UPDATE trainer_arenas SET is_public = false WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.commit()
    body = await _get(tg)
    assert body["state"] == CATALOG_STATE_PUBLISHED
    codes = {w["code"] for w in body["warnings"]}
    assert "no_public_arenas" in codes


@pytest.mark.asyncio
async def test_studio_managed_trainer_gets_a_read_only_screen(app_use_test_db, db_session, monkeypatch) -> None:
    tid, tg = await _complete_trainer(db_session, published=True)
    monkeypatch.setattr(
        "src.application.trainer_catalog_view.get_effective_studio_access_mode",
        lambda *a, **kw: _async_value("studio_admin_only"),
    )
    body = await _get(tg)
    assert body["can_act"] is False
    assert body["managed_by_studio"] is True
    assert body["actions"] == []
    status, _ = await _post(tg, "hide")
    assert status == 403


def _async_value(value):
    async def _inner():
        return value

    return _inner()


@pytest.mark.asyncio
async def test_migration_backfill_never_becomes_the_reason_the_trainer_reads(
    app_use_test_db, db_session
) -> None:
    """
    Every trainer who existed before migration 0206 carries one backfill event whose
    ``reason_detail`` is engineering shorthand. Read back as the current explanation it opened
    the screen with a line that reads like a crash report, so the payload must not carry it.
    """
    tid, tg = await _complete_trainer(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_catalog_events (
                trainer_id, from_state, to_state, reason, reason_detail, actor_type, actor_id
            ) VALUES (:t, NULL, 'draft', :reason, :detail, 'system', 'migration')
            """
        ),
        {
            "t": tid,
            "reason": REASON_BACKFILL_0206,
            "detail": "Состояние восстановлено из status + is_catalog_visible при переходе на явную модель.",
        },
    )
    await db_session.commit()

    body = await _get(tg)
    assert body["state_detail"] is None
    assert "is_catalog_visible" not in json.dumps(body, ensure_ascii=False)


@pytest.mark.asyncio
async def test_online_trainer_reaches_the_catalog_without_a_fixed_arena(
    app_use_test_db, db_session
) -> None:
    """
    Working online is not the same as being barred from the catalog. The submission tier used to
    demand a row in ``arena_ids``, which also dead-ended the profile carousel: it builds its rail
    from these keys, so the arena step re-armed itself forever with «Сначала заполните».
    """
    tid, tg = await _complete_trainer(db_session)
    await db_session.execute(text("DELETE FROM trainer_arenas WHERE trainer_id = :t"), {"t": tid})
    await db_session.execute(
        text("UPDATE trainers SET arena_work_format = 'online' WHERE id = :t"), {"t": tid}
    )
    await db_session.commit()

    body = await _get(tg)
    assert body["readiness"]["submit_ready"] is True
    assert "arenas" not in body["readiness"]["missing_fields"]
    assert "submit" in body["actions"]

    status, _ = await _post(tg, "submit")
    assert status == 200


@pytest.mark.asyncio
async def test_a_trainer_with_no_arena_and_no_format_still_has_to_pick_one(
    app_use_test_db, db_session
) -> None:
    """The relaxation is about the online/mobile format, not about dropping the check."""
    tid, tg = await _complete_trainer(db_session)
    await db_session.execute(text("DELETE FROM trainer_arenas WHERE trainer_id = :t"), {"t": tid})
    await db_session.commit()

    body = await _get(tg)
    assert body["readiness"]["submit_ready"] is False
    assert "arenas" in body["readiness"]["missing_fields"]


@pytest.mark.asyncio
async def test_prices_are_named_as_something_worth_adding(app_use_test_db, db_session) -> None:
    """
    Цены не блокируют публикацию, поэтому их не было ни в одном tier — и тренер узнавал про
    них только из строки «цена не указана» в карточке модератора, которую он не видит.
    """
    tid, tg = await _complete_trainer(db_session)
    body = await _get(tg)
    assert "цены на услуги" in body["readiness"]["optional_missing_labels_ru"]

    await db_session.execute(
        text("UPDATE trainer_services SET price_cents = 5000 WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.commit()
    body2 = await _get(tg)
    assert "цены на услуги" not in body2["readiness"]["optional_missing_labels_ru"]


@pytest.mark.asyncio
async def test_history_says_what_happened_not_who_checked_whom(app_use_test_db, db_session) -> None:
    """
    Строка собиралась как «<состояние> · <автор>», и «На проверке · вами» читалось так, будто
    тренер проверяет сам себя. Событие называется глаголом и само говорит, кто его совершил.
    """
    _, tg = await _complete_trainer(db_session)
    status, _ = await _post(tg, "submit")
    assert status == 200

    body = await _get(tg)
    headlines = [e["headline"] for e in body["events"]]
    assert headlines[0] == "Вы отправили карточку на проверку"
    for h in headlines:
        assert "·" not in h
        assert "вами" not in h


@pytest.mark.asyncio
async def test_editing_a_card_in_review_leaves_a_way_to_re_ping_the_moderator(
    app_use_test_db, db_session
) -> None:
    """
    Реальная правка снимает отметку в очереди (``clear_moderation_submitted_at``), и модератор
    держит ссылку на версию, которой уже нет. На экране при этом была одна кнопка «Отменить
    заявку»: позвать на проверку заново тренеру было нечем, и ждать он мог бесконечно.
    """
    tid, tg = await _complete_trainer(db_session)
    status, _ = await _post(tg, "submit")
    assert status == 200

    in_queue = await _get(tg)
    assert in_queue["state"] == CATALOG_STATE_PENDING_REVIEW
    assert in_queue["actions"] == ["withdraw"]
    assert "изменили карточку" not in in_queue["body"]

    # Тренер правит карточку — отметка в очереди слетает.
    await db_session.execute(
        text("UPDATE trainers SET moderation_submitted_at = NULL WHERE id = :t"), {"t": tid}
    )
    await db_session.commit()

    edited = await _get(tg)
    assert edited["state"] == CATALOG_STATE_PENDING_REVIEW
    assert edited["actions"] == ["resubmit", "withdraw"]
    assert "модератор ещё не видел новую версию" in edited["body"].lower()

    status2, _ = await _post(tg, "submit")
    assert status2 == 200
    again = await _get(tg)
    assert again["actions"] == ["withdraw"]


@pytest.mark.asyncio
async def test_a_card_in_review_that_was_not_touched_offers_only_withdrawal(
    app_use_test_db, db_session
) -> None:
    """Пока модератор смотрит ровно ту версию, что ему отправили, второй кнопки быть не должно."""
    _, tg = await _complete_trainer(db_session)
    await _post(tg, "submit")
    body = await _get(tg)
    assert body["actions"] == ["withdraw"]
