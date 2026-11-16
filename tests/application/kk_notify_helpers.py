"""Общие заготовки тестов уведомлений игрокам (TASK-426): подставные часы, посев игроков, ходов и сообщений."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from sqlalchemy import text

from src.ingestion.hockey_sources import MINSK_TZ

SASHA, KATYA, LESHA = 9420001, 9420002, 9420003


def at(hour: int, minute: int = 0, *, day: int = 10, month: int = 11, year: int = 2026) -> datetime:
    """Момент по Минску."""
    return datetime(year, month, day, hour, minute, tzinfo=MINSK_TZ)


def make_factory(db_session):
    @asynccontextmanager
    async def make():
        yield db_session

    return make


class Outbox:
    def __init__(self, answer="ok") -> None:
        self.sent: list[tuple[int, str, list]] = []
        self.answer = answer

    async def __call__(self, chat_id: int, body: str, buttons) -> str:
        self.sent.append((chat_id, body, buttons))
        return self.answer


_match_seq = [0]


async def seed_match(db, starts_at: datetime, home="Юность", away="Шахтер") -> int:
    _match_seq[0] += 1
    return (
        await db.execute(
            text("""
                INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                VALUES ('hockeyby', 'extraliga', :mid, :home, :away, :starts_at) RETURNING id
                """),
            {"mid": f"kk426-{_match_seq[0]}", "home": home, "away": away, "starts_at": starts_at},
        )
    ).scalar_one()


async def seed_player(
    db,
    key: int,
    *,
    registered: datetime | None = None,
    remind: bool | None = None,
    blocked_at: datetime | None = None,
    paused_until: datetime | None = None,
    **type_flags: bool,
) -> None:
    await db.execute(
        text("""
            INSERT INTO hockey_players (player_key, display_name, created_at)
            VALUES (:k, 'Игрок', COALESCE(:reg, now())) ON CONFLICT (player_key) DO NOTHING
            """),
        {"k": key, "reg": registered},
    )
    if remind is not None or blocked_at or paused_until or type_flags:
        await db.execute(text("INSERT INTO hockey_player_prefs (player_key) VALUES (:k) ON CONFLICT DO NOTHING"), {"k": key})
        if remind is not None:
            await db.execute(text("UPDATE hockey_player_prefs SET remind = :v WHERE player_key = :k"), {"k": key, "v": remind})
        await db.execute(
            text("UPDATE hockey_player_prefs SET bot_blocked_at = :b, notify_paused_until = :p WHERE player_key = :k"),
            {"k": key, "b": blocked_at, "p": paused_until},
        )
        for name, value in type_flags.items():
            await db.execute(
                text(f"UPDATE hockey_player_prefs SET {name} = :v WHERE player_key = :k"), {"k": key, "v": value}
            )


async def seed_pick(db, key: int, picked_at: datetime, *, match_id: int | None = None) -> int:
    mid = match_id or await seed_match(db, picked_at + timedelta(days=1))
    await db.execute(
        text("INSERT INTO hockey_picks (match_id, player_key, side, picked_at) VALUES (:m, :k, 'home', :t)"),
        {"m": mid, "k": key, "t": picked_at},
    )
    return mid


async def seed_notice(
    db, key: int, kind: str, sent_at: datetime | None, *, failed: bool = False, created_at: datetime | None = None
) -> int:
    mid = await seed_match(db, (sent_at or created_at or at(12)) + timedelta(days=1))
    await db.execute(
        text("""
            INSERT INTO hockey_notices (player_key, match_id, kind, sent_at, failed, created_at)
            VALUES (:k, :m, :kind, :s, :f, COALESCE(:c, :s, now()))
            """),
        {"k": key, "m": mid, "kind": kind, "s": sent_at, "f": failed, "c": created_at},
    )
    return mid
