"""Домашний матч Динамо как событие, на которое зовут друзей (TASK-304).

Приглашение — тот же движок, что «компания на лёд» (``ice_company``): карточка в чате с кнопками,
ответ без открытия приложения, правка карточки. Здесь — то, что нужно странице матча: кто из ваших
идёт, строка игры «Кто кого», ближайший лёд после матча, билеты, личная настройка игры.

Матч «домашний», если хозяева — «Динамо-Минск»; арена всегда Минск-Арена.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import STATUS_ACTIVE
from src.application.catalog_home_page import _session_card
from src.application.hockey_matches import DINAMO
from src.application.hockey_teams import team_card
from src.application.hub_home import _upcoming
from src.application.ice_city_day import DEFAULT_TIMEZONE, ICE_CITY_DAY_FROM_SQL, ICE_CITY_DAY_SESSION_WHERE_SQL
from src.application.ice_company.codes import tg_participant_key
from src.application.ice_company.copy import card_text
from src.application.ice_company.lifecycle import buttons_for
from src.application.ice_company.service import (
    MATCH_DURATION,
    MATCH_VENUE_LABEL,
    CompanyRejected,
    _load,
    _responses,
    _track,
    create_match_company,
    ice_slot_url,
    minsk_arena,
    respond,
    snap_from,
)
from src.application.place_links import place_start_param, telegram_open_link
from src.ingestion.hockey_sources import HCDINAMO_BASE
from src.shared.config import Settings
from src.shared.ice_discovery_scope import public_scope_params

logger = logging.getLogger(__name__)

STATUSES = ("going", "maybe", "cant")
ICE_AFTER_LIMIT = 2
_ICE_AFTER_DAYS = 7
TICKETS_FALLBACK_URL = f"{HCDINAMO_BASE}/tickets/"

_MATCH = text("""
    SELECT id, source_match_id, home_team, away_team, starts_at, status,
           home_score, away_score, decided_in, league, arena, city, tickets_url, details
    FROM hockey_matches
    WHERE id = :id AND (home_team = :home OR league = 'extraliga')
    """)
# Арена матча Экстралиги в каталоге: город клуба + первое слово названия с hockey.by («Чижовка-Арена»).
_EXTRALIGA_ARENA = text("""
    SELECT a.id, a.city_id, a.name, a.address, (lower(a.name) LIKE :pat) AS exact
    FROM arenas a
    JOIN cities c ON c.id = a.city_id
    WHERE lower(replace(c.name, 'ё', 'е')) = :city
    ORDER BY (lower(a.name) LIKE :pat) DESC, a.id
    LIMIT 1
    """)
_KK_SUBSCRIBED = text("SELECT 1 FROM extraliga_kk_subscriptions WHERE player_key = :player_key AND club = :club")
_KK_SUBSCRIBE = text("""
    INSERT INTO extraliga_kk_subscriptions (player_key, club) VALUES (:player_key, :club)
    ON CONFLICT DO NOTHING
    """)
_KK_SUBSCRIPTION_COUNTS = text("""
    SELECT club, COUNT(*) AS n FROM extraliga_kk_subscriptions GROUP BY club ORDER BY n DESC, club
    """)

# Люди из компаний на этот матч, где я организатор или отвечал сам. Ключи участников наружу не уходят.
_PEOPLE = text("""
    SELECT r.participant_key, r.display_name, r.status, r.updated_at
    FROM ice_companies c
    JOIN ice_company_events e ON e.id = c.event_id
    JOIN ice_company_responses r ON r.company_id = c.id
    WHERE e.source_ref = :src
      AND c.status = 'open'
      AND (
          c.organizer_ref = :me
          OR EXISTS (
              SELECT 1 FROM ice_company_responses mine
              WHERE mine.company_id = c.id AND mine.participant_key = :me
          )
      )
    ORDER BY r.updated_at, r.id
    """)

_MY_OTHER_COMPANIES = text("""
    SELECT c.public_code
    FROM ice_companies c
    JOIN ice_company_events e ON e.id = c.event_id
    JOIN ice_company_responses r ON r.company_id = c.id AND r.participant_key = :me
    WHERE e.source_ref = :src AND c.status = 'open'
    ORDER BY c.id
    """)

_PICKS_OF = text("""
    SELECT player_key, side, home_score, away_score, points
    FROM hockey_picks
    WHERE match_id = :match_id AND player_key = ANY(:keys)
    """)

# Сколько людей из Glide идут и смотрят дома: последний ответ каждого во всех компаниях матча.
# Без имён — это видно и тому, кто никого не звал (TASK-304, владелец: блок ответа должен иметь смысл).
_CROWD = text("""
    WITH latest AS (
        SELECT DISTINCT ON (r.participant_key) r.participant_key, r.status
        FROM ice_companies c
        JOIN ice_company_events e ON e.id = c.event_id
        JOIN ice_company_responses r ON r.company_id = c.id
        WHERE e.source_ref = :src AND c.status IN ('open', 'confirmed')
        ORDER BY r.participant_key, r.updated_at DESC, r.id DESC
    )
    SELECT COUNT(*) FILTER (WHERE status = 'going') AS going,
           COUNT(*) FILTER (WHERE status = 'maybe') AS maybe
    FROM latest
    """)

# Следующий домашний матч — для «Не смогу»: куда позвать в следующий раз.
_NEXT_HOME = text("""
    SELECT id, away_team, starts_at
    FROM hockey_matches
    WHERE home_team = :home AND status = 'scheduled' AND starts_at > :after AND id <> :id
    ORDER BY starts_at, id
    LIMIT 1
    """)

_PREFS = text("SELECT kk_hidden FROM hockey_player_prefs WHERE player_key = :player_key")

_PREFS_UPSERT = text("""
    INSERT INTO hockey_player_prefs (player_key, kk_hidden)
    VALUES (:player_key, :hidden)
    ON CONFLICT (player_key) DO UPDATE SET kk_hidden = EXCLUDED.kk_hidden, updated_at = now()
    """)

# Ближайший лёд арены после матча: тот же отбор сеансов, что у «Ближайшего льда» на главной.
_ICE_AFTER = text(f"""
    SELECT a.id AS arena_id,
           a.name AS arena_name,
           p.slug AS arena_slug,
           s.id AS session_id,
           s.starts_at_local,
           s.ends_at_local,
           s.local_date,
           s.schedule_basis,
           s.starts_at_utc,
           s.price_adult_minor,
           s.price_rental_minor,
           s.currency_code,
           COALESCE(p.timezone, '{DEFAULT_TIMEZONE}') AS city_timezone,
           (
               SELECT m.variants FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_variants
    {ICE_CITY_DAY_FROM_SQL}
    WHERE a.id = :arena_id
      AND s.starts_at_utc >= :starts_at
      AND s.starts_at_utc < :ends_at
      {ICE_CITY_DAY_SESSION_WHERE_SQL}
    ORDER BY s.starts_at_utc, s.id
    LIMIT :lim
    """)


class MatchNotFound(LookupError):
    """Нет такого матча или он не домашний."""


def enabled(settings: Settings | None = None) -> bool:
    """Всё новое живёт под флагом игры."""
    return bool((settings or Settings()).hockey_matches_enabled)  # type: ignore[call-arg]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_home(home_team: str) -> bool:
    return home_team == DINAMO


def event_href(match_id: int) -> str:
    """Страница матча в Mini App (маршрут ``/webapp/client-match``)."""
    return f"client-match?id={int(match_id)}"


def tickets_url(source_match_id: str | None) -> str:
    """Страница покупки именно этого матча у клуба; без номера — общая страница билетов."""
    raw = (source_match_id or "").strip()
    return f"{HCDINAMO_BASE}/tickets/?match={raw}" if raw.isdigit() else TICKETS_FALLBACK_URL


async def _home_match(session: AsyncSession, match_id: int) -> Any:
    """Домашний матч Динамо или (при включённой Экстралиге) любой матч Экстралиги."""
    row = (await session.execute(_MATCH, {"id": int(match_id), "home": DINAMO})).one_or_none()
    if row is None or (row.league == "extraliga" and not _extraliga_on()):
        raise MatchNotFound(match_id)
    return row


def _extraliga_on() -> bool:
    from src.application.extraliga import enabled_clubs

    cfg = Settings()  # type: ignore[call-arg]
    return bool(cfg.extraliga_enabled and enabled_clubs(cfg.extraliga_clubs))


async def _extraliga_arena(session: AsyncSession, row: Any) -> dict[str, Any] | None:
    word = ((row.arena or "").replace("-", " ").split() or [""])[0].lower()
    found = (
        (
            await session.execute(
                _EXTRALIGA_ARENA,
                {"city": (row.city or "").strip().lower().replace("ё", "е"), "pat": f"%{word}%" if word else "\x00"},
            )
        )
        .mappings()
        .first()
    )
    return dict(found) if found else None


async def _match_arena(session: AsyncSession, row: Any) -> dict[str, Any] | None:
    return await _extraliga_arena(session, row) if row.league == "extraliga" else await minsk_arena(session)


def _venue_label(row: Any) -> str:
    return (row.arena or row.city or "Арена") if row.league == "extraliga" else MATCH_VENUE_LABEL


def _host(url: str | None) -> str | None:
    from urllib.parse import urlparse

    host = urlparse(url or "").hostname or ""
    return host.removeprefix("www.") or None


async def kk_subscribe(session: AsyncSession, player_key: int, club: str) -> None:
    from src.application.extraliga import CLUBS

    if club not in {c.name for c in CLUBS.values()}:
        raise MatchNotFound(club)
    await session.execute(_KK_SUBSCRIBE, {"player_key": int(player_key), "club": club})


async def kk_subscription_counts(session: AsyncSession) -> list[dict[str, Any]]:
    return [{"club": r.club, "count": int(r.n)} for r in (await session.execute(_KK_SUBSCRIPTION_COUNTS)).all()]


async def _extraliga_extra(session: AsyncSession, row: Any, *, player_key: int, final: bool) -> dict[str, Any]:
    from src.application.extraliga import match_page_url
    from src.application.extraliga_preview import match_preview

    d = row.details or {}
    subscribed = (
        await session.execute(_KK_SUBSCRIBED, {"player_key": int(player_key), "club": row.home_team})
    ).first() is not None
    return {
        "league": "extraliga",
        # После финала с протоколом его место занимает «как прошёл матч»; до того — держим и в игре.
        "preview": None if final and d else await match_preview(session, int(row.id)),
        "details": (
            {k: d.get(k) for k in ("periods", "goals", "shots", "attendance", "best_players")} if final and d else None
        ),
        "tickets_url": row.tickets_url,
        "tickets_note": _host(row.tickets_url),
        "source_url": match_page_url(row.source_match_id),
        "kk_subscribe": {"club": row.home_team, "subscribed": subscribed},
    }


def _pick_out(row: Any) -> dict[str, Any]:
    return {
        "side": row.side,
        "home_score": row.home_score,
        "away_score": row.away_score,
        "points": row.points,
    }


def _phase(status: str, starts_at: datetime, *, now: datetime, picked: bool) -> str:
    if status in ("final", "cancelled"):
        return "final"
    if status == "scheduled" and now < starts_at:
        return "picked" if picked else "open"
    return "live"


def _key_number(participant_key: str) -> int | None:
    prefix, _, raw = participant_key.partition(":")
    return int(raw) if prefix == "tg" and raw.lstrip("-").isdigit() else None


async def _ice_after(
    session: AsyncSession, arena: dict[str, Any], *, after: datetime, settings: Settings
) -> list[dict]:
    """До двух ближайших сеансов льда Минск-Арены после матча — в виде «Ближайшего льда» главной."""
    try:
        async with session.begin_nested():
            rows = (
                (
                    await session.execute(
                        _ICE_AFTER,
                        {
                            "arena_id": int(arena["id"]),
                            "starts_at": after,
                            "ends_at": after + timedelta(days=_ICE_AFTER_DAYS),
                            "now": after,
                            "st": STATUS_ACTIVE,
                            "lim": ICE_AFTER_LIMIT,
                            **public_scope_params(),
                        },
                    )
                )
                .mappings()
                .all()
            )
    except Exception:  # noqa: BLE001 — лёд после матча не должен ронять страницу матча
        logger.exception("hockey event: ice after the match failed")
        return []
    if not rows:
        return []
    now = datetime.now(timezone.utc)
    cards = [_session_card(dict(row), now=now) for row in rows]
    place = {
        "id": int(arena["id"]),
        "slug": str(rows[0]["arena_slug"] or ""),
        "photo_variants": rows[0]["photo_variants"],
    }

    def invite(arena_id: int, session_id: int | None) -> str | None:
        return telegram_open_link(
            client_bot_username=settings.client_bot_username,
            mini_app_short_name=settings.client_mini_app_short_name,
            main_mini_app=settings.client_bot_main_mini_app,
            start_param=place_start_param(arena_id, session_id),
        )

    view = {
        "upcoming": cards,
        "places": [place],
        "today": now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date(),
    }
    return _upcoming(view, invite)


async def kk_hidden(session: AsyncSession, player_key: int) -> bool:
    return bool((await session.execute(_PREFS, {"player_key": player_key})).scalar_one_or_none())


async def set_kk_hidden(session: AsyncSession, player_key: int, hidden: bool) -> bool:
    await session.execute(_PREFS_UPSERT, {"player_key": player_key, "hidden": bool(hidden)})
    return bool(hidden)


async def event_view(
    session: AsyncSession,
    *,
    player_key: int,
    match_id: int,
    now: datetime,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Всё для страницы матча. ``MatchNotFound`` — матч выездной или чужой id."""
    cfg = settings or Settings()  # type: ignore[call-arg]
    now = _utc(now)
    row = await _home_match(session, match_id)
    starts_at = _utc(row.starts_at)
    me = tg_participant_key(player_key)

    seen: dict[str, dict[str, Any]] = {}
    for person in (await session.execute(_PEOPLE, {"src": f"hockey_match:{row.id}", "me": me})).mappings():
        seen[str(person["participant_key"])] = dict(person)  # поздний ответ перекрывает ранний
    mine = seen.get(me)
    others = [p for key, p in seen.items() if key != me]
    # Один я в списке — это не «кто из ваших»: блок нужен, когда есть с кем идти.
    people = (
        [{"name": p["display_name"], "status": p["status"], "is_me": key == me} for key, p in seen.items()]
        if others
        else []
    )

    picks = {
        int(r.player_key): r
        for r in (
            await session.execute(
                _PICKS_OF,
                {
                    "match_id": row.id,
                    "keys": [player_key, *[n for n in (_key_number(k) for k in seen if k != me) if n is not None]],
                },
            )
        ).all()
    }
    my_pick = picks.get(player_key)
    company_names = [
        str(p["display_name"])
        for key, p in seen.items()
        if key != me and (n := _key_number(key)) is not None and n in picks
    ][:2]

    # Компания уже собрана, но ответов ещё нет — страница показывает «ждём ответов», а не пустоту.
    my_companies = (
        (await session.execute(_MY_OTHER_COMPANIES, {"src": f"hockey_match:{row.id}", "me": me})).scalars().all()
    )
    crowd = (await session.execute(_CROWD, {"src": f"hockey_match:{row.id}"})).one()
    nxt = (
        await session.execute(_NEXT_HOME, {"home": row.home_team, "after": max(now, starts_at), "id": row.id})
    ).one_or_none()

    arena = await _match_arena(session, row)
    extraliga = row.league == "extraliga"
    final = row.status == "final"
    if extraliga and arena is not None and not arena.get("exact"):
        arena = None  # чужой каток города не выдаём за арену матча
    out = {
        "match": {
            "id": row.id,
            "home": team_card(row.home_team),
            "away": team_card(row.away_team),
            "starts_at": starts_at.isoformat(),
            "status": row.status,
            "result": (
                {"home_score": row.home_score, "away_score": row.away_score, "decided_in": row.decided_in}
                if final
                else None
            ),
            "is_home": not extraliga,
            "league": row.league,
        },
        "arena": {
            "name": _venue_label(row),
            "arena_id": int(arena["id"]) if arena else None,
            "address": (arena or {}).get("address") or None,
        },
        "my_status": mine["status"] if mine else None,
        "people": people,
        "kk": {
            "hidden": await kk_hidden(session, player_key),
            "phase": _phase(row.status, starts_at, now=now, picked=my_pick is not None),
            "my_pick": _pick_out(my_pick) if my_pick else None,
            "points": my_pick.points if my_pick else None,
            "company_names": company_names,
        },
        "crowd": {"going": int(crowd.going or 0), "maybe": int(crowd.maybe or 0)},
        "company_open": bool(my_companies),
        "next_home": (
            {
                "id": nxt.id,
                "away": team_card(nxt.away_team),
                "starts_at": _utc(nxt.starts_at).isoformat(),
                "event_href": event_href(nxt.id),
            }
            if nxt
            else None
        ),
        "tickets_url": tickets_url(row.source_match_id),
        "ice_after": (
            await _ice_after(session, arena, after=max(now, starts_at + MATCH_DURATION), settings=cfg) if arena else []
        ),
    }
    if extraliga:
        out["arena"]["city"] = row.city
        out.update(await _extraliga_extra(session, row, player_key=player_key, final=final))
    else:
        from src.application.extraliga_preview import match_preview

        out["preview"] = await match_preview(session, int(row.id))
    return out


async def rsvp(
    session: AsyncSession,
    *,
    player_key: int,
    match_id: int,
    status: str,
    display_name: str,
    company_code: str | None = None,
    now: datetime,
    settings: Settings | None = None,
) -> None:
    """Ответ клиента на матч: в его компании (создаётся при первом ответе) и во всех, где он уже отвечал.

    ``company_code`` — приглашение друга: ответ ложится и в его компанию, чтобы он увидел ответ.
    """
    cfg = settings or Settings()  # type: ignore[call-arg]
    if status not in STATUSES:
        raise CompanyRejected("Ответ: иду, смотрю дома или не смогу.")
    row = await _home_match(session, match_id)
    arena = await _match_arena(session, row)
    view = await create_match_company(
        session,
        telegram_user_id=player_key,
        match_id=match_id,
        home_team=row.home_team,
        arena=arena,
        venue_label=_venue_label(row),
        display_name=display_name,
        now=now,
        settings=cfg,
    )
    me = tg_participant_key(player_key)
    source = f"hockey_match:{int(match_id)}"
    codes = [str(view["public_code"])]
    codes += [
        str(code)
        for code in (await session.execute(_MY_OTHER_COMPANIES, {"me": me, "src": source})).scalars().all()
        if str(code) not in codes
    ]
    invited = (company_code or "").strip().lower()
    if invited and invited not in codes:
        joined = await _load(session, invited)
        if joined is not None and joined["source_ref"] == source and joined["status"] == "open":
            codes.append(invited)
    for code in codes:
        try:
            await respond(
                session,
                code=code,
                status=status,
                display_name=display_name,
                participant_key=me,
                source="tg",
                consent=True,
                now=now,
                settings=cfg,
            )
        except CompanyRejected:
            # Чужая компания может быть закрыта или переполнена — свой ответ от этого не пропадает.
            if code == codes[0]:
                raise
            logger.info("hockey rsvp skipped company code=%s", code)


async def invite(
    session: AsyncSession,
    *,
    player_key: int,
    match_id: int,
    display_name: str,
    now: datetime,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Карточка компании клиента на матч для чата: код, текст, кнопки и ссылка на страницу матча."""
    cfg = settings or Settings()  # type: ignore[call-arg]
    row = await _home_match(session, match_id)
    arena = await _match_arena(session, row)
    view = await create_match_company(
        session,
        telegram_user_id=player_key,
        match_id=match_id,
        home_team=row.home_team,
        arena=arena,
        venue_label=_venue_label(row),
        display_name=display_name,
        now=now,
        settings=cfg,
    )
    code = str(view["public_code"])
    company = await _load(session, code)
    assert company is not None
    snap = snap_from(company, await _responses(session, int(company["id"])))
    page = ice_slot_url(company, cfg)
    return {
        "code": code,
        "text": card_text(snap),
        "buttons": buttons_for(company, snap, page),
        "url": page,
        "city_id": int(company["city_id"]),
    }


async def track_shared(session: AsyncSession, *, city_id: int, prepared: bool) -> None:
    """Счётчик отправленных приглашений. Без ключей игроков."""
    await _track(
        session,
        kind="card_shared",
        city_id=city_id,
        arena_id=None,
        payload={"surface": "hockey_match", "prepared": prepared},
        actor_hash=None,
    )


__all__ = [
    "ICE_AFTER_LIMIT",
    "STATUSES",
    "MatchNotFound",
    "enabled",
    "event_href",
    "event_view",
    "invite",
    "is_home",
    "kk_hidden",
    "rsvp",
    "set_kk_hidden",
    "tickets_url",
    "track_shared",
]
