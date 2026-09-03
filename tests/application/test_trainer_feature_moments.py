"""
TASK-030: все шесть правил «фича в нужный момент» — постоянный клиент, абонемент,
группы, статистика, сертификаты, перенесённый `client_notes`.

Юнит-тесты бьют по чистому `resolve_trainer_feature_moment` на готовых фактах — без БД.
Интеграционные бьют по `fetch_trainer_feature_moment_facts` на реальных бронированиях.
"""
from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock

from sqlalchemy import text

from src.application.trainer_feature_moments import (
    ITEM_CERTIFICATES,
    ITEM_CLIENT_NOTES,
    ITEM_GROUPS,
    ITEM_PASS,
    ITEM_RECURRING_CLIENT,
    ITEM_STATS,
    fetch_trainer_feature_moment_facts,
    resolve_trainer_feature_moment,
)
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


def _checklist(**over) -> dict:
    base = {
        "schedule_unlocked": True,
        "studio_access_mode": None,
        "has_crm_subscription_access": True,
    }
    base.update(over)
    return base


def _recurring_fact(**over) -> dict:
    base = {
        "client_id": 1,
        "client_name": "Анна",
        "day_of_week": 4,  # пятница
        "start_time": time(18, 0),
        "count": 3,
    }
    base.update(over)
    return base


def _pass_fact(**over) -> dict:
    base = {"client_id": 2, "client_name": "Борис", "count": 5}
    base.update(over)
    return base


def _groups_fact(**over) -> dict:
    base = {"day_of_week": 2, "start_time": time(19, 0), "clients_n": 2}
    base.update(over)
    return base


def _stats_fact(**over) -> dict:
    base = {"completed_n": 3}
    base.update(over)
    return base


def _certificates_fact(**over) -> dict:
    base = {"has_moment": True}
    base.update(over)
    return base


# --- resolve_trainer_feature_moment: чистая функция ---------------------------------


def test_no_facts_returns_none() -> None:
    assert resolve_trainer_feature_moment(_checklist(), {}) is None
    assert resolve_trainer_feature_moment(_checklist(), None) is None


def test_recurring_client_card_names_client_and_weekday() -> None:
    card = resolve_trainer_feature_moment(
        _checklist(), {"recurring_client": _recurring_fact(), "pass": None}
    )
    assert card is not None
    assert card["item_id"] == ITEM_RECURRING_CLIENT
    assert "Анна" in card["title"] + card["subtitle"]
    assert "пятниц" in card["subtitle"]  # день недели упомянут текстом


def test_pass_card_fires_when_only_pass_fact_present() -> None:
    card = resolve_trainer_feature_moment(
        _checklist(), {"recurring_client": None, "pass": _pass_fact()}
    )
    assert card is not None
    assert card["item_id"] == ITEM_PASS
    assert "Борис" in card["title"] + card["subtitle"]


def test_recurring_client_wins_over_pass_when_both_present() -> None:
    """AC-004: первое совпадение выигрывает, на экране ровно одна карточка."""
    card = resolve_trainer_feature_moment(
        _checklist(),
        {"recurring_client": _recurring_fact(), "pass": _pass_fact()},
    )
    assert card["item_id"] == ITEM_RECURRING_CLIENT


def test_groups_card_fires_when_only_groups_fact_present() -> None:
    card = resolve_trainer_feature_moment(_checklist(), {"groups": _groups_fact()})
    assert card is not None
    assert card["item_id"] == ITEM_GROUPS
    assert "средам" in card["subtitle"]  # день недели упомянут текстом


def test_stats_card_fires_when_only_stats_fact_present() -> None:
    card = resolve_trainer_feature_moment(_checklist(), {"stats": _stats_fact()})
    assert card is not None
    assert card["item_id"] == ITEM_STATS


def test_certificates_card_fires_when_only_certificates_fact_present() -> None:
    card = resolve_trainer_feature_moment(_checklist(), {"certificates": _certificates_fact()})
    assert card is not None
    assert card["item_id"] == ITEM_CERTIFICATES


def test_client_notes_card_fires_from_checklist_flag_when_no_other_fact() -> None:
    """DEC-004: правило перенесено — условие то же (`has_completed_booking`), просто
    источник истины сменился с `_build_hub_rhythm_inbox_candidates` на этот резолвер."""
    card = resolve_trainer_feature_moment(_checklist(has_completed_booking=True), {})
    assert card is not None
    assert card["item_id"] == ITEM_CLIENT_NOTES
    assert card["primary_action"] == "client_notes"


def test_client_notes_silent_without_completed_booking() -> None:
    card = resolve_trainer_feature_moment(_checklist(has_completed_booking=False), {})
    assert card is None


def test_priority_order_across_all_six_rules() -> None:
    """AC-004: первое совпадение выигрывает, строго в заявленном порядке."""
    all_facts = {
        "recurring_client": _recurring_fact(),
        "pass": _pass_fact(),
        "groups": _groups_fact(),
        "stats": _stats_fact(),
        "certificates": _certificates_fact(),
    }
    checklist = _checklist(has_completed_booking=True)

    order = [
        (ITEM_RECURRING_CLIENT, dict(all_facts)),
        (ITEM_PASS, {**all_facts, "recurring_client": None}),
        (ITEM_GROUPS, {**all_facts, "recurring_client": None, "pass": None}),
        (ITEM_STATS, {**all_facts, "recurring_client": None, "pass": None, "groups": None}),
        (
            ITEM_CERTIFICATES,
            {**all_facts, "recurring_client": None, "pass": None, "groups": None, "stats": None},
        ),
        (
            ITEM_CLIENT_NOTES,
            {
                "recurring_client": None,
                "pass": None,
                "groups": None,
                "stats": None,
                "certificates": None,
            },
        ),
    ]
    for expected_id, facts in order:
        card = resolve_trainer_feature_moment(checklist, facts)
        assert card["item_id"] == expected_id


def test_admin_only_studio_silences_card() -> None:
    """EDGE-001: тренер центра не ведёт своё расписание."""
    card = resolve_trainer_feature_moment(
        _checklist(studio_access_mode="admin_only"),
        {"recurring_client": _recurring_fact()},
    )
    assert card is None


def test_lead_mode_silences_card() -> None:
    """AC-007: без подписки функция всё равно выключена — предлагать её обман."""
    card = resolve_trainer_feature_moment(
        _checklist(has_crm_subscription_access=False),
        {"recurring_client": _recurring_fact()},
    )
    assert card is None


def test_schedule_locked_silences_card() -> None:
    card = resolve_trainer_feature_moment(
        _checklist(schedule_unlocked=False),
        {"recurring_client": _recurring_fact()},
    )
    assert card is None


def test_dismissed_recurring_client_falls_through_to_pass() -> None:
    card = resolve_trainer_feature_moment(
        _checklist(),
        {"recurring_client": _recurring_fact(), "pass": _pass_fact()},
        dismissed_ids=frozenset({ITEM_RECURRING_CLIENT}),
    )
    assert card["item_id"] == ITEM_PASS


def test_dismissed_pass_with_no_other_fact_returns_none() -> None:
    card = resolve_trainer_feature_moment(
        _checklist(),
        {"recurring_client": None, "pass": _pass_fact()},
        dismissed_ids=frozenset({ITEM_PASS}),
    )
    assert card is None


# --- fetch_trainer_feature_moment_facts: интеграция на реальной БД ------------------


async def _seed_trainer(db_session) -> int:
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = int(r.scalar_one())
    return tid


async def _seed_client(db_session, *, first_name: str = "Тест", is_sandbox: bool = False) -> int:
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized, is_sandbox)
            VALUES (:tg, :fn, 'Clientov', :phone, :pn, :sandbox) RETURNING id
            """
        ),
        {"tg": tg, "fn": first_name, "phone": phone, "pn": phone_n, "sandbox": is_sandbox},
    )
    return int(r.scalar_one())


async def _seed_slot(db_session, trainer_id: int, slot_date: date, start: time, end: time) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked') RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date, "st": start, "et": end},
    )
    return int(r.scalar_one())


async def _seed_booking(
    db_session,
    *,
    trainer_id: int,
    client_id: int,
    slot_id: int,
    service_id: int,
    status: str = "confirmed",
    is_sandbox: bool = False,
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status, is_sandbox)
            VALUES (:tid, :cid, :sid, :svc, :status, :sandbox) RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "cid": client_id,
            "sid": slot_id,
            "svc": service_id,
            "status": status,
            "sandbox": is_sandbox,
        },
    )
    return int(r.scalar_one())


def _last_friday_on_or_before(d: date) -> date:
    return d - timedelta(days=(d.weekday() - 4) % 7)


async def test_recurring_client_fact_detected_for_three_same_slot_bookings(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Анна")
    service_id = await require_seed_service_id(db_session)
    friday = _last_friday_on_or_before(date.today())
    for i in range(3):
        d = friday - timedelta(days=7 * i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(18, 0), time(19, 0))
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=client_id, slot_id=slot_id, service_id=service_id
        )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    rc = facts["recurring_client"]
    assert rc is not None
    assert rc["client_id"] == client_id
    assert rc["client_name"] == "Анна"
    assert rc["day_of_week"] == 4  # пятница = Mon0
    assert rc["count"] == 3


async def test_recurring_client_fact_excludes_sandbox_client_and_booking(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    service_id = await require_seed_service_id(db_session)
    friday = _last_friday_on_or_before(date.today())

    sandbox_client = await _seed_client(db_session, first_name="Демо", is_sandbox=True)
    for i in range(3):
        d = friday - timedelta(days=7 * i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(9, 0), time(10, 0))
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=sandbox_client, slot_id=slot_id, service_id=service_id
        )

    real_client = await _seed_client(db_session, first_name="Реал")
    for i in range(3):
        d = friday - timedelta(days=7 * i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(11, 0), time(12, 0))
        await _seed_booking(
            db_session,
            trainer_id=trainer_id,
            client_id=real_client,
            slot_id=slot_id,
            service_id=service_id,
            is_sandbox=True,
        )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["recurring_client"] is None


async def test_recurring_client_fact_absent_when_active_recurring_slot_exists(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Анна")
    service_id = await require_seed_service_id(db_session)
    friday = _last_friday_on_or_before(date.today())
    for i in range(3):
        d = friday - timedelta(days=7 * i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(18, 0), time(19, 0))
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=client_id, slot_id=slot_id, service_id=service_id
        )
    await db_session.execute(
        text(
            """
            INSERT INTO recurring_client_slots (trainer_id, client_id, day_of_week, start_time, end_time, status)
            VALUES (:tid, :cid, 4, TIME '18:00', TIME '19:00', 'active')
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["recurring_client"] is None


async def test_pass_fact_detected_for_five_completed_bookings(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Борис")
    service_id = await require_seed_service_id(db_session)
    today = date.today()
    for i in range(5):
        slot_id = await _seed_slot(
            db_session, trainer_id, today - timedelta(days=i + 1), time(10, 0), time(11, 0)
        )
        await _seed_booking(
            db_session,
            trainer_id=trainer_id,
            client_id=client_id,
            slot_id=slot_id,
            service_id=service_id,
            status="completed",
        )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    pf = facts["pass"]
    assert pf is not None
    assert pf["client_id"] == client_id
    assert pf["client_name"] == "Борис"
    assert pf["count"] == 5


async def test_pass_fact_excludes_sandbox_client(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Демо", is_sandbox=True)
    service_id = await require_seed_service_id(db_session)
    today = date.today()
    for i in range(5):
        slot_id = await _seed_slot(
            db_session, trainer_id, today - timedelta(days=i + 1), time(10, 0), time(11, 0)
        )
        await _seed_booking(
            db_session,
            trainer_id=trainer_id,
            client_id=client_id,
            slot_id=slot_id,
            service_id=service_id,
            status="completed",
        )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["pass"] is None


async def test_certificates_fact_excludes_sandbox_client_pass(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Демо", is_sandbox=True)
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
            VALUES (:tid, 'Pack 5', 5, 5000, true) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    pass_product_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status)
            VALUES (:cid, :pid, 5, 5, 5000, 'active')
            """
        ),
        {"cid": client_id, "pid": pass_product_id},
    )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["certificates"] is None


async def test_pass_fact_absent_when_active_pass_exists(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Борис")
    service_id = await require_seed_service_id(db_session)
    today = date.today()
    for i in range(5):
        slot_id = await _seed_slot(
            db_session, trainer_id, today - timedelta(days=i + 1), time(10, 0), time(11, 0)
        )
        await _seed_booking(
            db_session,
            trainer_id=trainer_id,
            client_id=client_id,
            slot_id=slot_id,
            service_id=service_id,
            status="completed",
        )
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
            VALUES (:tid, 'Pack 5', 5, 5000, true) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    pass_product_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status)
            VALUES (:cid, :pid, 5, 5, 5000, 'active')
            """
        ),
        {"cid": client_id, "pid": pass_product_id},
    )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["pass"] is None


async def test_groups_fact_detected_when_pattern_repeats_across_two_weeks(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    service_id = await require_seed_service_id(db_session)
    client_a = await _seed_client(db_session, first_name="Клиент А")
    client_b = await _seed_client(db_session, first_name="Клиент Б")
    wednesday = date.today() - timedelta(days=(date.today().weekday() - 2) % 7)
    for i in range(2):
        d = wednesday - timedelta(days=7 * i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(19, 0), time(20, 0))
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=client_a, slot_id=slot_id, service_id=service_id
        )
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=client_b, slot_id=slot_id, service_id=service_id
        )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    gf = facts["groups"]
    assert gf is not None
    assert gf["day_of_week"] == 2  # среда
    assert gf["clients_n"] == 2


async def test_groups_fact_absent_on_a_single_occurrence(db_session) -> None:
    """EDGE-004: разовое совпадение двух клиентов в одном слоте — не группа."""
    trainer_id = await _seed_trainer(db_session)
    service_id = await require_seed_service_id(db_session)
    client_a = await _seed_client(db_session, first_name="Клиент А")
    client_b = await _seed_client(db_session, first_name="Клиент Б")
    slot_id = await _seed_slot(db_session, trainer_id, date.today() + timedelta(days=1), time(19, 0), time(20, 0))
    await _seed_booking(
        db_session, trainer_id=trainer_id, client_id=client_a, slot_id=slot_id, service_id=service_id
    )
    await _seed_booking(
        db_session, trainer_id=trainer_id, client_id=client_b, slot_id=slot_id, service_id=service_id
    )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["groups"] is None


async def test_groups_fact_excludes_sandbox_client(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    service_id = await require_seed_service_id(db_session)
    client_a = await _seed_client(db_session, first_name="Клиент А")
    sandbox_client = await _seed_client(db_session, first_name="Демо", is_sandbox=True)
    wednesday = date.today() - timedelta(days=(date.today().weekday() - 2) % 7)
    for i in range(2):
        d = wednesday - timedelta(days=7 * i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(19, 0), time(20, 0))
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=client_a, slot_id=slot_id, service_id=service_id
        )
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=sandbox_client, slot_id=slot_id, service_id=service_id
        )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["groups"] is None  # только 1 не-sandbox клиент на слот — меньше порога


async def test_groups_fact_absent_when_trainer_already_has_a_group(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    service_id = await require_seed_service_id(db_session)
    client_a = await _seed_client(db_session, first_name="Клиент А")
    client_b = await _seed_client(db_session, first_name="Клиент Б")
    wednesday = date.today() - timedelta(days=(date.today().weekday() - 2) % 7)
    for i in range(2):
        d = wednesday - timedelta(days=7 * i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(19, 0), time(20, 0))
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=client_a, slot_id=slot_id, service_id=service_id
        )
        await _seed_booking(
            db_session, trainer_id=trainer_id, client_id=client_b, slot_id=slot_id, service_id=service_id
        )
    await db_session.execute(
        text(
            "INSERT INTO training_groups (trainer_id, name, service_id) VALUES (:tid, 'Группа', :svc)"
        ),
        {"tid": trainer_id, "svc": service_id},
    )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["groups"] is None


async def test_stats_fact_detected_after_first_week_closed(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Клиент")
    service_id = await require_seed_service_id(db_session)
    today = date.today()
    for i in range(3):
        d = today - timedelta(days=8 + i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(10, 0), time(11, 0))
        await _seed_booking(
            db_session,
            trainer_id=trainer_id,
            client_id=client_id,
            slot_id=slot_id,
            service_id=service_id,
            status="completed",
        )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    sf = facts["stats"]
    assert sf is not None
    assert sf["completed_n"] == 3


async def test_stats_fact_absent_once_stats_opened(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Клиент")
    service_id = await require_seed_service_id(db_session)
    today = date.today()
    for i in range(3):
        d = today - timedelta(days=8 + i)
        slot_id = await _seed_slot(db_session, trainer_id, d, time(10, 0), time(11, 0))
        await _seed_booking(
            db_session,
            trainer_id=trainer_id,
            client_id=client_id,
            slot_id=slot_id,
            service_id=service_id,
            status="completed",
        )
    await db_session.execute(
        text(
            "INSERT INTO trainer_feature_first_use (trainer_id, feature) VALUES (:tid, 'stats_opened')"
        ),
        {"tid": trainer_id},
    )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["stats"] is None


async def test_certificates_fact_detected_after_first_pass_issued(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Клиент")
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
            VALUES (:tid, 'Pack 5', 5, 5000, true) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    pass_product_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status)
            VALUES (:cid, :pid, 5, 5, 5000, 'active')
            """
        ),
        {"cid": client_id, "pid": pass_product_id},
    )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["certificates"] == {"has_moment": True}


async def test_certificates_fact_absent_when_trainer_already_has_a_certificate_product(db_session) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, first_name="Клиент")
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
            VALUES (:tid, 'Pack 5', 5, 5000, true) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    pass_product_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status)
            VALUES (:cid, :pid, 5, 5, 5000, 'active')
            """
        ),
        {"cid": client_id, "pid": pass_product_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_certificate_products (trainer_id, name, amount_cents, is_active)
            VALUES (:tid, 'Gift', 10000, true)
            """
        ),
        {"tid": trainer_id},
    )
    await db_session.commit()

    facts = await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    assert facts["certificates"] is None


async def test_fetch_facts_issues_exactly_one_round_trip(db_session) -> None:
    """AC-008: сборка инбокса не добавляет более одного доп. SQL-запроса."""
    trainer_id = await _seed_trainer(db_session)
    await db_session.commit()
    real_execute = db_session.execute
    spy = AsyncMock(side_effect=real_execute)
    db_session.execute = spy
    try:
        await fetch_trainer_feature_moment_facts(db_session, trainer_id)
    finally:
        db_session.execute = real_execute
    assert spy.call_count == 1
