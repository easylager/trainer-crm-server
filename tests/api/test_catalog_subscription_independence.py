"""
Что происходит с карточкой, когда подписка кончилась (TASK-140).

Экран обещает тренеру ровно одно: «Подписка на каталог не влияет: если она закончится,
карточка останется — отключится только самозапись». Обещание на экране ничего не стоит, пока
его не держит код, поэтому здесь оно проверяется как инвариант: истечение подписки не является
переходом состояния карточки и не трогает публичную выдачу.

Зависимость направлена в одну сторону: lifecycle читает состояние карточки
(``_derive_stage``: active + нет подписки + карточка в выдаче → LEAD_MODE), а не наоборот.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.lifecycle_use_cases import LifecycleStage, resolve_lifecycle_stage
from src.shared.catalog_visibility import CATALOG_STATE_HIDDEN, CATALOG_STATE_PUBLISHED
from tests.api.test_catalog_lifecycle_transparency import (  # noqa: F401 — фикстуры
    _act,
    _approve_as_moderator,
    _listed_publicly,
    _new_trainer,
    _screen,
    admin_pings,
    pushes,
)


async def _expire_all_subscriptions(db_session, trainer_id: int) -> None:
    await db_session.execute(
        text(
            "UPDATE trainer_subscriptions SET status = 'expired', "
            "expires_at = now() - interval '1 day' WHERE trainer_id = :t"
        ),
        {"t": trainer_id},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_an_expired_subscription_leaves_the_card_exactly_where_it_was(
    app_use_test_db, db_session, admin_pings, pushes
) -> None:
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    await _approve_as_moderator(db_session, tid)
    assert await _listed_publicly(tid) is True

    events_before = len((await _screen(tg))["events"])
    pushes.clear()

    await _expire_all_subscriptions(db_session, tid)

    screen = await _screen(tg)
    assert screen["state"] == CATALOG_STATE_PUBLISHED, "подписка не является переходом состояния"
    assert await _listed_publicly(tid) is True, "карточка обязана остаться в выдаче"
    assert len(screen["events"]) == events_before, "в журнале не должно появиться записи"
    assert pushes == [], "пугать тренера пушем про каталог тут не за что"
    # Фраза, ради которой всё это и проверяется, на экране есть.
    assert "подписка" in screen["subscription_note"].lower()
    assert "останется" in screen["subscription_note"].lower()


@pytest.mark.asyncio
async def test_a_published_card_without_a_subscription_is_lead_mode_not_churn(
    app_use_test_db, db_session, admin_pings
) -> None:
    """
    Тренер без подписки, но в каталоге — LEAD_MODE: заявки к нему идут, самозапись выключена.
    Именно эта комбинация и есть смысл обещания «карточка останется».
    """
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    await _approve_as_moderator(db_session, tid)
    await _expire_all_subscriptions(db_session, tid)

    assert await resolve_lifecycle_stage(db_session, tid) == LifecycleStage.LEAD_MODE


@pytest.mark.asyncio
async def test_hiding_the_card_without_a_subscription_is_churn_not_a_catalog_bug(
    app_use_test_db, db_session, admin_pings
) -> None:
    """
    Обратная сторона: снял карточку сам и не платит — это CHURNED, но снял её **он**, а не
    подписка. Состояние карточки при этом остаётся ``hidden`` со своей причиной и автором.
    """
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    await _approve_as_moderator(db_session, tid)
    await _expire_all_subscriptions(db_session, tid)
    assert (await _act(tg, "hide"))[0] == 200

    screen = await _screen(tg)
    assert screen["state"] == CATALOG_STATE_HIDDEN
    assert screen["events"][0]["actor_type"] == "trainer", "автор снятия — тренер, не система"
    assert await resolve_lifecycle_stage(db_session, tid) == LifecycleStage.CHURNED
    # И вернуть её можно в один тап, платит тренер или нет.
    assert screen["actions"] == ["restore"]
    assert (await _act(tg, "restore"))[0] == 200
    assert await _listed_publicly(tid) is True


@pytest.mark.asyncio
async def test_no_subscription_code_path_writes_the_catalog_column(
    app_use_test_db, db_session
) -> None:
    """
    Сторож направления зависимости: единственный писатель ``catalog_state`` —
    ``set_catalog_state``, и ни один его вызов не живёт в подписочном коде.
    """
    import pathlib
    import re

    src = pathlib.Path("src")
    callers = {
        str(p)
        for p in src.rglob("*.py")
        if re.search(r"\bset_catalog_state\(", p.read_text())
        and "trainer_catalog_state.py" not in str(p)
    }
    for path in callers:
        assert "subscription" not in path, f"подписка не должна двигать карточку: {path}"
    # И наоборот — публичный гейт не спрашивает про подписку.
    gate = (src / "shared" / "catalog_visibility.py").read_text()
    assert "subscription" not in gate.lower()
