"""TASK-428: поводы прогрева — кто получает что и когда. Отправка подменена, Telegram не вызывается."""

from __future__ import annotations

from datetime import timedelta

import pytest
from kk_notify_helpers import Outbox, make_factory, seed_notice, seed_player
from sqlalchemy import text
from warm_helpers import (
    ANNA,
    BORIS,
    VERA,
    at,
    seed_arena,
    seed_client,
    seed_session,
    seed_visit,
    seed_warm_notice,
    seed_watch,
)

from src.application import hockey_notices as hn
from src.application import kk_notify_gate as gate
from src.application import warm_notify as wn
from src.application.catalog_consumer_events import telegram_actor_hash
from src.application.kk_notify_gate import FAMILY_WARM, GateConfig

NB = " "
CFG = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=frozenset(gate.WARM_KINDS), family=FAMILY_WARM)
SECRET = "w" * 40


@pytest.fixture(autouse=True)
def _env(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", SECRET)
    hn._RETRIES.clear()


@pytest.fixture
def factory(db_session):
    return make_factory(db_session)


async def _tick(factory, now, out, *, kinds=None, cfg=CFG):
    producers = {k: wn.PRODUCERS[k] for k in (kinds or gate.WARM_KINDS)}
    return await wn.run_tick(factory, now=now, send=out, producers=producers, config=cfg, clock=lambda: now)


# ---------- приветствие ----------


@pytest.mark.asyncio
async def test_welcome_once_with_nearest_sessions(db_session, factory) -> None:
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=18))
    await seed_session(db_session, arena, at(19, 30, day=19))
    await seed_session(db_session, arena, at(12, day=21))
    await seed_session(db_session, arena, at(15, day=22))
    out = Outbox()
    await _tick(factory, at(12, day=18), out, kinds=[gate.KIND_WARM_WELCOME])
    assert len(out.sent) == 1
    chat, body, buttons = out.sent[0]
    assert chat == ANNA
    assert (
        body == f"На{NB}катке «Чижовка-арена» ближайшие сеансы{NB}— завтра в{NB}19:30{NB}и{NB}в{NB}субботу в{NB}12:00."
    )
    assert [b["text"] for row in buttons for b in row] == ["Открыть расписание", "Не присылать"]
    await _tick(factory, at(12, day=19), out, kinds=[gate.KIND_WARM_WELCOME])
    assert len(out.sent) == 1  # один раз


@pytest.mark.asyncio
async def test_welcome_one_per_person_and_only_fresh_subscriptions(db_session, factory) -> None:
    a, b = await seed_arena(db_session), await seed_arena(db_session, "Минск-Арена")
    await seed_watch(db_session, ANNA, a, created_at=at(10, day=18))
    await seed_watch(db_session, ANNA, b, created_at=at(11, day=18))
    await seed_watch(db_session, BORIS, a, created_at=at(10, day=15))  # подписка старше двух суток
    for arena in (a, b):
        await seed_session(db_session, arena, at(19, day=20))
    proposals = await wn.produce_welcome(db_session, now=at(12, day=18))
    assert [(p.notice.player_key, p.notice.arena_id) for p in proposals] == [(ANNA, a)]


@pytest.mark.asyncio
async def test_welcome_without_sessions_is_not_sent(db_session) -> None:
    """Ревью п. 3: сказать нечего — не пишем; подтверждение подписки человек уже получил от бота или Mini App."""
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=18))
    assert await wn.produce_welcome(db_session, now=at(12, day=18)) == []


@pytest.mark.asyncio
async def test_unsubscribed_before_send_is_stale(db_session, factory) -> None:
    arena = await seed_arena(db_session)
    watch = await seed_watch(db_session, ANNA, arena, created_at=at(10, day=18))
    await seed_session(db_session, arena, at(19, day=20))
    [proposal] = await wn.produce_welcome(db_session, now=at(12, day=18))
    await db_session.execute(text("UPDATE client_ice_watches SET active = false WHERE id = :w"), {"w": watch})
    reason = await proposal.recheck(db_session, ANNA, at(12, day=18))
    assert reason == "no_subscription"


# ---------- сегодня ----------


@pytest.mark.asyncio
async def test_today_in_the_morning_only(db_session) -> None:
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=1))
    await seed_session(db_session, arena, at(12, day=20))
    await seed_session(db_session, arena, at(19, 30, day=20))
    [p] = await wn.produce_today(db_session, now=at(9, 30, day=20))
    assert p.notice.text == f"Сегодня на{NB}катке «Чижовка-арена» лёд в{NB}12:00{NB}и{NB}19:30."
    assert p.notice.ref == "d2026-11-20"
    assert await wn.produce_today(db_session, now=at(11, 0, day=20)) == []  # окно закрылось
    assert await wn.produce_today(db_session, now=at(9, 30, day=21)) == []  # сеансов в этот день нет


@pytest.mark.asyncio
async def test_today_skips_session_too_close_and_unsubscribed(db_session) -> None:
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=1))
    await seed_watch(db_session, BORIS, arena, created_at=at(10, day=1), active=False)
    await seed_session(db_session, arena, at(10, 15, day=20))  # меньше часа до начала
    assert await wn.produce_today(db_session, now=at(9, 30, day=20)) == []


# ---------- неделя ----------


@pytest.mark.asyncio
async def test_week_on_thursday_and_wins_over_today(db_session, factory) -> None:
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=1))
    await seed_session(db_session, arena, at(19, 30, day=19))
    await seed_session(db_session, arena, at(12, day=21))
    await seed_session(db_session, arena, at(15, 30, day=21))
    assert await wn.produce_week(db_session, now=at(9, 30, day=18)) == []  # среда
    out = Outbox()
    counts = await _tick(factory, at(9, 30, day=19), out, kinds=[gate.KIND_WARM_TODAY, gate.KIND_WARM_WEEK])
    assert counts == {"ok": 1} and len(out.sent) == 1
    body = out.sent[0][1]
    assert body.startswith("<b>«Чижовка-арена»: сеансы на")
    assert f"• сегодня{NB}— 19:30" in body and f"• в{NB}субботу{NB}— 12:00{NB}и{NB}15:30" in body


@pytest.mark.asyncio
async def test_week_without_sessions_is_silent(db_session) -> None:
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=1))
    await seed_session(db_session, arena, at(12, day=29))  # дальше недели
    assert await wn.produce_week(db_session, now=at(9, 30, day=19)) == []


# ---------- общий бюджет с игрой в проходе ----------


@pytest.mark.asyncio
async def test_game_message_today_holds_warm_until_tomorrow(db_session, factory) -> None:
    arena = await seed_arena(db_session)
    await seed_player(db_session, ANNA)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=18))
    await seed_session(db_session, arena, at(19, day=21))
    await seed_notice(db_session, ANNA, "nomove", at(10, day=18))
    out = Outbox()
    counts = await _tick(factory, at(12, day=18), out, kinds=[gate.KIND_WARM_WELCOME])
    assert out.sent == [] and counts == {"skip": 1}
    await _tick(factory, at(9, 5, day=19), out, kinds=[gate.KIND_WARM_WELCOME])
    assert len(out.sent) == 1  # на следующий день, в окне двух суток


# ---------- напоминание «знающим нас» ----------


async def _known(db, tid: int, visit, *, arena: int | None) -> None:
    await seed_client(db, tid)
    await seed_visit(db, telegram_actor_hash(tid), visit, arena_id=arena)


@pytest.mark.asyncio
async def test_nudge_three_to_seven_days_after_single_visit(db_session) -> None:
    arena = await seed_arena(db_session)
    await _known(db_session, ANNA, at(18, day=15), arena=arena)  # 4 дня назад
    await _known(db_session, BORIS, at(18, day=17), arena=arena)  # 2 дня назад — рано
    await _known(db_session, VERA, at(18, day=11), arena=arena)  # 8 дней назад — поздно
    proposals = await wn.produce_nudge(db_session, now=at(9, 30, day=19))
    assert [p.notice.player_key for p in proposals] == [ANNA]
    notice = proposals[0].notice
    assert notice.ref == "once" and notice.kind == gate.KIND_WARM_NUDGE
    assert "Спрашиваем один раз." in notice.text
    assert notice.buttons == [
        [{"text": "Сообщать о сеансах", "callback_data": f"warm:sub:{arena}"}],
        [{"text": "Не присылать", "callback_data": "warm:off"}],
    ]


@pytest.mark.asyncio
async def test_nudge_skips_returning_subscribed_optout_and_already_nudged(db_session) -> None:
    arena = await seed_arena(db_session)
    await _known(db_session, ANNA, at(18, day=14), arena=arena)
    await seed_visit(db_session, telegram_actor_hash(ANNA), at(18, day=15), arena_id=arena)  # два дня — не разовый
    await _known(db_session, BORIS, at(18, day=15), arena=arena)
    await seed_watch(db_session, BORIS, arena, created_at=at(19, day=15))  # подписан
    await _known(db_session, VERA, at(18, day=15), arena=arena)
    await seed_warm_notice(db_session, VERA, gate.KIND_WARM_NUDGE, at(10, day=16), ref="once")
    assert await wn.produce_nudge(db_session, now=at(9, 30, day=19)) == []


@pytest.mark.asyncio
async def test_nudge_needs_arena_and_actor_secret(db_session, monkeypatch) -> None:
    arena = await seed_arena(db_session)
    await _known(db_session, ANNA, at(18, day=15), arena=None)  # смотрел только оболочку
    await _known(db_session, BORIS, at(18, day=15), arena=arena)
    assert [p.notice.player_key for p in await wn.produce_nudge(db_session, now=at(9, 30, day=19))] == [BORIS]
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "")
    monkeypatch.setattr("src.shared.config.get_settings", lambda: type("S", (), {"catalog_actor_hmac_secret": ""})())
    assert await wn.produce_nudge(db_session, now=at(9, 30, day=19)) == []  # без секрета — закрыто


@pytest.mark.asyncio
async def test_nudge_recheck_when_person_came_back(db_session) -> None:
    arena = await seed_arena(db_session)
    await _known(db_session, ANNA, at(18, day=15), arena=arena)
    [p] = await wn.produce_nudge(db_session, now=at(9, 30, day=19))
    await seed_visit(db_session, telegram_actor_hash(ANNA), at(9, 0, day=19), arena_id=arena)
    assert await p.recheck(db_session, ANNA, at(9, 31, day=19)) == "visited_again"


@pytest.mark.asyncio
async def test_no_mapping_is_stored(db_session, factory) -> None:
    """Соответствие actor_hash и Telegram не пишется никуда: в журнале — только telegram_id и вид."""
    arena = await seed_arena(db_session)
    await _known(db_session, ANNA, at(18, day=15), arena=arena)
    await _tick(factory, at(9, 30, day=19), Outbox(), kinds=[gate.KIND_WARM_NUDGE])
    actor = telegram_actor_hash(ANNA)
    for table in ("kk_notify_decisions", "warm_notices", "warm_prefs"):
        rows = (await db_session.execute(text(f"SELECT * FROM {table}"))).all()
        assert all(actor not in str(tuple(r)) for r in rows), table


@pytest.mark.asyncio
async def test_opt_out_button_reply_stops_everything(db_session, factory) -> None:
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=18))
    await seed_session(db_session, arena, at(19, 30, day=19))
    await wn.set_opt_out(db_session, ANNA, True, now=at(11, day=18))
    out = Outbox()
    for day, hour in ((18, 12), (19, 9)):
        await _tick(factory, at(hour, 30, day=day), out)
    assert out.sent == []


@pytest.mark.asyncio
async def test_subscribe_callback_roundtrip() -> None:
    assert wn.parse_subscribe_callback(wn.subscribe_callback(42)) == 42
    for bad in (None, "", "warm:sub:", "warm:sub:x", "warm:sub:0", "warm:off", f"warm:sub:{2**31}"):
        assert wn.parse_subscribe_callback(bad) is None


@pytest.mark.asyncio
async def test_cleanup_keeps_once_rows(db_session, factory) -> None:
    await seed_warm_notice(db_session, ANNA, gate.KIND_WARM_NUDGE, at(10, day=1, month=6), ref="once")
    await seed_warm_notice(db_session, ANNA, gate.KIND_WARM_TODAY, at(10, day=1, month=6), ref="d2026-06-01")
    await seed_warm_notice(db_session, BORIS, gate.KIND_WARM_TODAY, at(10, day=10), ref="d2026-11-10")
    deleted = await wn.cleanup_old_notices(factory, now=at(12, day=19))
    left = (await db_session.execute(text("SELECT telegram_id, ref FROM warm_notices ORDER BY 1, 2"))).all()
    assert deleted == 1 and [tuple(r) for r in left] == [(ANNA, "once"), (BORIS, "d2026-11-10")]


def test_today_window_boundaries() -> None:
    assert wn.in_morning(at(9, 0)) and wn.in_morning(at(10, 59))
    assert not wn.in_morning(at(8, 59)) and not wn.in_morning(at(11, 0))
    assert wn.nudge_due(at(1, day=16).date(), at(9, day=19)) and not wn.nudge_due(at(1, day=17).date(), at(9, day=19))
    assert wn.week_ref(at(9, day=19)) == "w2026-W47" and wn.day_ref(at(0, 5, day=19) - timedelta(minutes=10)) == (
        "d2026-11-18"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("column", ["remind", "notify_consent"])
async def test_nudge_skips_game_opt_out(db_session, column) -> None:
    """Ревью п. 1: нажал «Не присылать» в игре — напоминание C не планируется."""
    arena = await seed_arena(db_session)
    await _known(db_session, ANNA, at(18, day=15), arena=arena)
    await seed_player(db_session, ANNA, remind=True)
    assert [p.notice.player_key for p in await wn.produce_nudge(db_session, now=at(9, 30, day=19))] == [ANNA]
    await db_session.execute(
        text(f"UPDATE hockey_player_prefs SET {column} = false WHERE player_key = :k"), {"k": ANNA}
    )
    assert await wn.produce_nudge(db_session, now=at(9, 30, day=19)) == []


@pytest.mark.asyncio
async def test_nudge_skips_cancelled_subscription_and_closed_offer(db_session) -> None:
    """Ревью п. 2: отменил подписку на этот каток или закрыл предложение A — напоминания нет, и закрытое не вернётся."""
    arena, other = await seed_arena(db_session), await seed_arena(db_session, "Минск-Арена")
    await _known(db_session, ANNA, at(18, day=15), arena=arena)
    await seed_watch(db_session, ANNA, arena, created_at=at(18, day=15), active=False)  # отменил
    await _known(db_session, BORIS, at(18, day=15), arena=arena)
    await db_session.execute(
        text("""INSERT INTO catalog_consumer_events (kind, surface, actor_hash, arena_id, occurred_at)
                VALUES ('watch_offer_closed', 'miniapp_arena', :h, :a, :w)"""),
        {"h": telegram_actor_hash(BORIS), "a": other, "w": at(18, day=15)},
    )
    await _known(db_session, VERA, at(18, day=15), arena=arena)
    await seed_watch(db_session, VERA, other, created_at=at(18, day=15), active=False)  # отменил другой каток
    proposals = await wn.produce_nudge(db_session, now=at(9, 30, day=19))
    assert [p.notice.player_key for p in proposals] == [VERA]
    # закрыл предложение уже после того, как напоминание собрали — перед отправкой оно отменяется
    await db_session.execute(
        text("""INSERT INTO catalog_consumer_events (kind, surface, actor_hash, arena_id, occurred_at)
                VALUES ('watch_offer_closed', 'place_page', :h, :a, :w)"""),
        {"h": telegram_actor_hash(VERA), "a": arena, "w": at(9, 31, day=19)},
    )
    assert await proposals[0].recheck(db_session, VERA, at(9, 32, day=19)) == "offer_closed"


@pytest.mark.asyncio
async def test_today_recheck_requires_morning(db_session) -> None:
    """Ревью п. 11: «сегодня лёд», собранное в 10:59, после 11:00 уже не уходит."""
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(10, day=1))
    await seed_session(db_session, arena, at(19, 30, day=20))
    [p] = await wn.produce_today(db_session, now=at(10, 59, day=20))
    assert await p.recheck(db_session, ANNA, at(10, 59, day=20)) is None
    assert await p.recheck(db_session, ANNA, at(11, 0, day=20)) == "out_of_window"


@pytest.mark.asyncio
async def test_known_excludes_blocked_optout_sandbox(db_session) -> None:
    """Ревью п. 11: напоминание C не планируется заблокировавшим бота (прогрев или игра), нажавшим «Не присылать»,
    песочнице."""
    from warm_helpers import seed_warm_prefs

    arena = await seed_arena(db_session)
    people = [ANNA, BORIS, VERA, 9428004, 9428005]
    for tid in people:
        await _known(db_session, tid, at(18, day=15), arena=arena)
    await seed_warm_prefs(db_session, ANNA, bot_blocked_at=at(9, day=16))
    await seed_warm_prefs(db_session, BORIS, opted_out_at=at(9, day=16))
    await seed_player(db_session, VERA, blocked_at=at(9, day=16))
    await db_session.execute(text("UPDATE clients SET is_sandbox = true WHERE telegram_id = 9428004"))
    assert [p.notice.player_key for p in await wn.produce_nudge(db_session, now=at(9, 30, day=19))] == [9428005]
