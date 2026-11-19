"""TASK-431: пятничное приглашение собрать лигу — аудитория, окно, серия 1→2→3, стоп, «Не присылать», фото."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from kk_notify_helpers import (
    KATYA,
    LESHA,
    SASHA,
    at,
    make_factory,
    seed_final,
    seed_notice,
    seed_pick,
    seed_player,
    seed_scored,
)
from sqlalchemy import text

from src.application import hockey_notices as hn
from src.application import kk_league_invite as li
from src.application import kk_notify_gate as gate
from src.application.kk_notify import dispatch, run_tick
from src.application.kk_notify_gate import GateConfig

FRI = at(12, 0, day=20)  # пятница 20.11.2026, 12:00 по Минску
CFG = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=frozenset({"lginvite"}))


class PhotoOutbox:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, list, str | None]] = []

    async def __call__(self, chat_id: int, body: str, buttons, photo: str | None = None) -> str:
        self.sent.append((chat_id, body, buttons, photo))
        return "ok"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)
    monkeypatch.setenv("KK_LEAGUE_INVITE_ENABLED", "1")
    for week in (1, 2, 3):
        (tmp_path / f"kk-league-invite-{week}.png").write_bytes(b"\x89PNG")
    monkeypatch.setattr(li, "COVERS", tmp_path)
    hn._RETRIES.clear()


@pytest.fixture
def factory(db_session):
    return make_factory(db_session)


async def player(db, key=SASHA, *, picked=FRI - timedelta(days=2), consent=True) -> None:
    await seed_player(db, key, registered=at(10, day=1), notify_consent=consent)
    await seed_pick(db, key, picked)


async def league_with(db, key: int, *, member: bool = True) -> None:
    league_id = (
        await db.execute(
            text("""INSERT INTO hockey_leagues (name, invite_code, owner_key, scope, term_kind, starts_at, ends_at)
                    VALUES ('Л', :c, :o, 'all', 'season', :s, :e) RETURNING id"""),
            {"c": f"LI{key}", "o": key, "s": at(0, day=1), "e": at(0, day=28, month=12)},
        )
    ).scalar_one()
    if member:
        await db.execute(
            text("INSERT INTO hockey_league_members (league_id, player_key) VALUES (:l, :k)"),
            {"l": league_id, "k": key},
        )


def test_week_one_text_is_the_owners_and_drafts_have_no_banned_words() -> None:
    assert li.WEEK_TEXTS[1].startswith("Собери лигу и договоритесь, на что играете — на пиво, на шашлык или на честь.")
    assert li.WEEK_TEXTS[1].endswith("В конце месяца — корона и расплата.")
    assert "2 минуты" not in li.WEEK_TEXTS[1]  # жесты в релиз не вошли
    for body in li.WEEK_TEXTS.values():
        for bad in ("ставк", "постав", "срок", "×"):
            assert bad not in body.lower()
    assert li.invite_caption(week=1, hits=5, played=8).startswith(
        "За неделю ты угадал <b>5 из 8</b>. А твои друзья?\n\n"
    )
    assert li.invite_caption(week=2, hits=0, played=0) == li.WEEK_TEXTS[2]  # сыгранных ходов нет — без личной строки


def test_kind_is_registered_lowest_priority_with_its_own_off_switch() -> None:
    policy = gate.KIND_POLICY["lginvite"]
    assert policy.new and policy.budgeted and policy.weekly and policy.type_column == "notify_lginvite"
    others = [
        p.priority for k, p in gate.KIND_POLICY.items() if p.new and p.family == gate.FAMILY_KK and k != "lginvite"
    ]
    assert policy.priority > max(others)
    assert li.CB_OFF_INVITE == "kk:off:li" and hn.TYPE_CODES["li"] == "lginvite"


@pytest.mark.asyncio
async def test_audience_active_without_league(db_session) -> None:
    db = db_session
    await player(db, SASHA)
    await player(db, KATYA)
    await league_with(db, KATYA)  # своя лига — не зовём
    await player(db, LESHA, picked=FRI - timedelta(days=40))  # ходил давно — тоже зовём: прогреть
    got = await li.produce_league_invite(db, now=FRI)
    assert sorted(p.notice.player_key for p in got) == sorted([SASHA, LESHA])
    lesha = next(p for p in got if p.notice.player_key == LESHA)
    assert not lesha.notice.text.startswith("За неделю")  # за неделю ходов нет — без личной строки


@pytest.mark.asyncio
async def test_member_of_a_friends_league_is_invited_to_create_own(db_session) -> None:
    """Владелец 2026-11-19: зовём, если нет СВОЕЙ лиги — в чужой состоять можно."""
    await player(db_session, SASHA)
    await player(db_session, KATYA)
    await league_with(db_session, KATYA)
    katya_league = (
        await db_session.execute(text("SELECT id FROM hockey_leagues WHERE owner_key = :k"), {"k": KATYA})
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO hockey_league_members (league_id, player_key) VALUES (:l, :k)"),
        {"l": katya_league, "k": SASHA},
    )
    assert [p.notice.player_key for p in await li.produce_league_invite(db_session, now=FRI)] == [SASHA]


@pytest.mark.asyncio
async def test_owner_of_an_archived_league_is_not_invited(db_session) -> None:
    await player(db_session, SASHA)
    await league_with(db_session, SASHA, member=False)
    assert await li.produce_league_invite(db_session, now=FRI) == []


@pytest.mark.asyncio
async def test_friday_noon_window_and_switch(db_session, monkeypatch) -> None:
    await player(db_session, SASHA)
    assert await li.produce_league_invite(db_session, now=at(12, 0, day=19)) == []  # четверг
    assert await li.produce_league_invite(db_session, now=at(11, 59, day=20)) == []
    assert len(await li.produce_league_invite(db_session, now=at(12, 0, day=20))) == 1
    assert len(await li.produce_league_invite(db_session, now=at(19, 59, day=20))) == 1  # деплой в обед — успеем
    assert await li.produce_league_invite(db_session, now=at(20, 0, day=20)) == []
    monkeypatch.setenv("KK_LEAGUE_INVITE_ENABLED", "0")
    assert await li.produce_league_invite(db_session, now=FRI) == []  # выключено по умолчанию и здесь


def test_disabled_by_default(monkeypatch) -> None:
    from src.shared.config import Settings

    monkeypatch.delenv("KK_LEAGUE_INVITE_ENABLED", raising=False)
    assert Settings(_env_file=None).kk_league_invite_enabled is False  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_photo_caption_buttons_and_personal_line(db_session, factory) -> None:
    db = db_session
    await player(db, SASHA)
    for pts in (50, 20, 0):
        m = await seed_final(db, "Юность", "Неман", FRI - timedelta(days=3))
        await seed_scored(db, SASHA, m, pts)
    [p] = await li.produce_league_invite(db, now=FRI)
    n = p.notice
    assert n.kind == "lginvite" and n.photo.endswith("kk-league-invite-1.png")
    assert n.text.startswith("За неделю ты угадал <b>2 из 3</b>. А твои друзья?\n\nСобери лигу")
    labels = [b["text"] for row in n.buttons for b in row]
    assert labels == ["Создать лигу друзей", "Не присылать"]
    assert (
        "kkg_lg1" in n.buttons[0][0]["url"]
    )  # метка входа недели → hockey_entry_events, first_src, hockey_leagues.src
    out = PhotoOutbox()
    result = await dispatch(factory, p, phase="active", tick_at=FRI, send=out, config=CFG, clock=lambda: FRI)
    assert (result.decision, result.result) == ("send", "ok")
    assert out.sent[0][3] == n.photo


@pytest.mark.asyncio
async def test_series_one_two_three_then_stop(db_session) -> None:
    db = db_session
    await player(db, SASHA)
    [p] = await li.produce_league_invite(db, now=FRI)
    assert "kkg_lg1" in p.notice.buttons[0][0]["url"]
    await seed_notice(db, SASHA, "lginvite", FRI - timedelta(days=7))
    [p] = await li.produce_league_invite(db, now=FRI)
    assert p.notice.photo.endswith("kk-league-invite-2.png") and li.WEEK_TEXTS[2] in p.notice.text
    assert "kkg_lg2" in p.notice.buttons[0][0]["url"]
    await seed_notice(db, SASHA, "lginvite", FRI - timedelta(days=14))
    [p] = await li.produce_league_invite(db, now=FRI)
    assert "kkg_lg3" in p.notice.buttons[0][0]["url"]
    await seed_notice(db, SASHA, "lginvite", FRI - timedelta(days=21))
    assert await li.produce_league_invite(db, now=FRI) == []  # отправлено три — серия кончилась


@pytest.mark.asyncio
async def test_not_twice_a_week(db_session) -> None:
    await player(db_session, SASHA)
    await seed_notice(db_session, SASHA, "lginvite", FRI - timedelta(days=2))
    assert await li.produce_league_invite(db_session, now=FRI) == []


@pytest.mark.asyncio
async def test_missing_cover_skips_the_week_and_warns(db_session, tmp_path, caplog) -> None:
    await player(db_session, SASHA)
    (tmp_path / "kk-league-invite-1.png").unlink()
    with caplog.at_level(logging.WARNING, logger=li.__name__):
        assert await li.produce_league_invite(db_session, now=FRI) == []
    assert "kk-league-invite-1.png" in caplog.text


@pytest.mark.asyncio
async def test_stops_when_player_creates_own_league_before_sending(db_session, factory) -> None:
    await player(db_session, SASHA)
    [p] = await li.produce_league_invite(db_session, now=FRI)
    await league_with(db_session, SASHA)
    out = PhotoOutbox()
    result = await dispatch(factory, p, phase="active", tick_at=FRI, send=out, config=CFG, clock=lambda: FRI)
    assert result.reason == "stale:in_league" and out.sent == []


@pytest.mark.asyncio
async def test_do_not_send_button_turns_the_type_off(db_session, factory) -> None:
    await player(db_session, SASHA)
    [p] = await li.produce_league_invite(db_session, now=FRI)
    await hn.set_type(db_session, SASHA, "lginvite", False)
    out = PhotoOutbox()
    result = await dispatch(factory, p, phase="active", tick_at=FRI, send=out, config=CFG, clock=lambda: FRI)
    assert result.reason == gate.TYPE_OFF and out.sent == []
    assert await li.produce_league_invite(db_session, now=FRI)  # повод есть, но допуск его не пропустит


@pytest.mark.asyncio
async def test_tick_sends_once_within_budget_and_needs_the_kind_flag(db_session, factory) -> None:
    await player(db_session, SASHA)
    out = PhotoOutbox()
    off = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=frozenset({"week"}))
    assert (
        await run_tick(factory, now=FRI, send=out, producers={"lginvite": li.produce_league_invite}, config=off) == {}
    )
    counts = await run_tick(
        factory, now=FRI, send=out, producers={"lginvite": li.produce_league_invite}, config=CFG, clock=lambda: FRI
    )
    reasons = (await db_session.execute(text("SELECT decision, reason FROM kk_notify_decisions ORDER BY id"))).all()
    assert counts == {"ok": 1} and len(out.sent) == 1, reasons
    later = FRI + timedelta(minutes=30)
    await run_tick(
        factory, now=later, send=out, producers={"lginvite": li.produce_league_invite}, config=CFG, clock=lambda: later
    )
    assert len(out.sent) == 1  # в эту пятницу второго нет


@pytest.mark.asyncio
async def test_poster_uploads_once_then_goes_by_file_id(tmp_path) -> None:
    """Сотни одинаковых постеров: файл грузится один раз, дальше — file_id; устаревший file_id — загрузим снова."""
    from types import SimpleNamespace

    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendPhoto
    from aiogram.types import FSInputFile

    poster = tmp_path / "p.png"
    poster.write_bytes(b"png")
    calls: list[str] = []

    class Bot:
        stale = False

        async def send_photo(self, *, chat_id, photo, caption, reply_markup):
            if isinstance(photo, FSInputFile):
                calls.append("upload")
                return SimpleNamespace(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")])
            calls.append(photo)
            if self.stale:
                raise TelegramBadRequest(method=SendPhoto(chat_id=1, photo="x"), message="wrong file identifier")
            return SimpleNamespace(photo=[])

    hn._PHOTO_IDS.clear()
    bot = Bot()
    for _ in range(3):
        await hn._send_photo(bot, 1, str(poster), "c", None)
    assert calls == ["upload", "big", "big"]
    bot.stale = True
    await hn._send_photo(bot, 1, str(poster), "c", None)
    assert calls[-2:] == ["big", "upload"]
