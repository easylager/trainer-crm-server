"""Клиентское API лиг друзей «Кто кого»: создать, вступить, таблица, выйти."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.api.routes.webapp_client_hockey import _player_name
from src.application import hockey_league_reports as league_reports
from src.application.hockey_league_images import (
    MAX_UPLOAD_BYTES,
    LeagueImageError,
    image_urls,
    release_image,
    store_league_image,
)
from src.application.hockey_leagues import (
    FEW_MATCHES,
    MONTHLY_CROWN_TERMS,
    AlreadyExtended,
    InvalidTerms,
    League,
    LeagueFull,
    LeagueRow,
    LeagueSummary,
    TooManyLeagues,
    build_terms,
    create_league,
    delete_league,
    extend_league,
    join_league,
    league_image_key,
    league_table,
    league_titles,
    leave_league,
    matches_in_terms,
    member_league,
    owned_league,
    own_active_league,
    player_display_name,
    player_leagues,
    quick_league,
    quick_name,
    set_league_image,
    term_options,
    update_league,
)
from src.application.hockey_league_captain import (
    AlreadyGiven,
    NotCaptain,
    OutfitRefused,
    RightClosed,
    captain_enabled,
    current_state,
    set_outfit,
)
from src.application.hockey_league_evening import (
    DayNotPlayed,
    GestureRefused,
    gestures_enabled,
    league_evening,
    period_marks,
    set_gesture,
)
from src.application.hockey_races import crown_counts, league_crown_wall, race_summary
from src.application.hockey_share import record_card_event
from src.application.hockey_slices import parse_period
from src.application.place_links import public_telegram_entry_link
from src.shared.config import Settings

router = APIRouter(tags=["webapp"])

_TOO_MANY = "Можно состоять максимум в 20 лигах"
_LEAGUE_FULL = "В лиге уже 100 человек"
_NOT_FOUND = "Лига не найдена"
_FORBIDDEN = "Нет доступа к этой лиге"
_ALREADY_EXTENDED = "Лига уже продлена — вы из продолжения вышли"
_OWN_LEAGUE_REPORT = "Это твоя лига — картинку и текст можно поменять в настройках"


class TermsBody(BaseModel):
    """Набор команд и срок лиги. Без них — «Динамо-Минск, до конца сезона»."""

    scope: Literal["all", "extraliga", "dinamo", "clubs"] = "dinamo"
    clubs: list[str] = []
    term: Literal["season", "month", "weeks4", "playoff", "dates"] = "season"
    month: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class CreateLeagueBody(BaseModel):
    name: str
    display_name: str | None = None
    terms: TermsBody | None = None
    stake_text: str | None = None  # «на что играем»; картинка грузится отдельно: POST .../{id}/image


class ExtendLeagueBody(BaseModel):
    terms: TermsBody | None = None


class JoinLeagueBody(BaseModel):
    code: str
    display_name: str | None = None
    # С какой карточки в чате пришёл: для воронки TASK-300.
    from_card: Literal["result", "league"] | None = None


class GestureBody(BaseModel):
    """Жест участнику за игровой день: ``to`` — его ``pid`` из «Вечера», ``kind`` пустой — снять."""

    to: str
    kind: Literal["stick", "pen"] | None = None


class OutfitBody(BaseModel):
    """Право капитана: кому (``pid`` из «Вечера», можно себе) и какую вещь из «Экипировки капитана»."""

    to: str
    item: str


class QuickLeagueBody(BaseModel):
    """«Лига готова» (TASK-431): какие матчи, «на что играем» и метка входа (``lg1``…) — для отчёта по входам."""

    scope: Literal["all", "dinamo", "clubs"] = "all"
    clubs: list[str] = []
    stake_text: str | None = None
    display_name: str | None = None
    src: str | None = None


class PatchLeagueBody(BaseModel):
    """Что поменять в лиге. Не переданное остаётся; ``stake_text`` пустой или ``null`` — убрать строку."""

    name: str | None = None
    stake_text: str | None = None


def invite_url_for_code(code: str) -> str | None:
    """Приглашение в лигу — публичный вход: при ``public_entry_via_start`` через ``/start``. Без бота ссылки нет."""
    return public_telegram_entry_link(Settings(), start_param=f"kk_{code}")  # type: ignore[call-arg]


def _raise_league(exc: Exception) -> NoReturn:
    if isinstance(exc, ValueError):  # в том числе InvalidTerms
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc
    if isinstance(exc, LeagueFull):
        raise HTTPException(status_code=409, detail=_LEAGUE_FULL) from exc
    if isinstance(exc, TooManyLeagues):
        raise HTTPException(status_code=409, detail=_TOO_MANY) from exc
    if isinstance(exc, AlreadyExtended):
        raise HTTPException(status_code=409, detail=_ALREADY_EXTENDED) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=_FORBIDDEN) from exc
    raise exc


def _identity_out(image_key: str | None, stake_text: str | None) -> dict:
    """Лицо лиги: адреса картинки (основной и для списка) и строка «на что играем»; нет — ``None``."""
    url, thumb = image_urls(image_key)
    return {"image_url": url, "image_thumb_url": thumb, "stake_text": stake_text}


def _summary_out(row: LeagueSummary) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "members": row.members,
        "is_owner": row.is_owner,
        "my_rank": row.my_rank,
        "my_points": row.my_points,
        "invite_url": invite_url_for_code(row.invite_code),
        **_terms_out(row.scope, row.clubs, row.term_kind, row.starts_at, row.ends_at),
        **_identity_out(row.image_key, row.stake_text),
        "active": row.active,
    }


def _terms_out(scope: str, clubs, term_kind: str, starts_at, ends_at) -> dict:
    return {
        "scope": scope,
        "clubs": list(clubs),
        "term": term_kind,
        "starts_at": None if starts_at is None else starts_at.isoformat(),
        "ends_at": None if ends_at is None else ends_at.isoformat(),
    }


def _terms_from(body: TermsBody | None, now: datetime):
    if body is None:
        return None
    return build_terms(
        scope=body.scope,
        clubs=body.clubs,
        term=body.term,
        now=now,
        month=body.month,
        starts_at=body.starts_on,
        ends_at=body.ends_on,
    )


def _table_row(row: LeagueRow, player_key: int, titles: dict | None = None) -> dict:
    return {
        "rank": row.rank,
        "display_name": row.display_name,
        "points": row.points,
        "exact": row.exact,
        "played": row.played,
        "correct_percent": None if not row.played else round(100 * row.correct / row.played),
        "is_me": row.player_key == player_key,
        "title": (titles or {}).get(row.player_key),
    }


async def _created_out(session: AsyncSession, league: League, player_key: int, now: datetime) -> dict:
    rows = await league_table(session, league_id=league.id, player_key=player_key, now=now)
    mine = next(row for row in rows if row.player_key == player_key)
    return {
        "id": league.id,
        "name": league.name,
        "members": len(rows),
        "is_owner": league.owner_key == player_key,
        "my_rank": mine.rank,
        "my_points": mine.points,
        "invite_url": invite_url_for_code(league.invite_code),
        **_terms_out(league.scope, league.clubs, league.term_kind, league.starts_at, league.ends_at),
        **_identity_out(league.image_key, league.stake_text),
        "active": _aware_end(league.ends_at) > now,
    }


def _aware_end(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _init_raw(init_data: str | None, header: str | None) -> str:
    return (init_data or header or "").strip()


@router.get("/client/hockey/leagues")
async def get_client_hockey_leagues(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    rows = await player_leagues(session, player_key=player_key, now=now)
    return {"items": [_summary_out(row) for row in rows]}


@router.post("/client/hockey/leagues")
async def post_client_hockey_league(
    body: CreateLeagueBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        terms = _terms_from(body.terms, now)
        league = await create_league(
            session,
            owner_key=player_key,
            owner_name=_player_name(body.display_name, _init_raw(init_data, x_telegram_init_data)),
            name=body.name,
            terms=terms,
            now=now,
            stake_text=body.stake_text,
        )
        payload = await _created_out(session, league, player_key, now)
        payload.update(await _terms_hint(session, league, now))
    except (ValueError, TooManyLeagues) as exc:
        _raise_league(exc)
    await session.commit()
    return payload


async def _terms_hint(session: AsyncSession, league: League, now: datetime) -> dict:
    """Сколько матчей ещё впереди в сроке; меньше пяти — предупреждаем (пауза, клуб вылетел)."""
    from src.application.hockey_leagues import Terms

    count = await matches_in_terms(
        session,
        Terms(league.scope, league.clubs, league.term_kind, league.starts_at, league.ends_at),  # type: ignore[arg-type]
        now=now,
    )
    return {"matches_in_term": count, "few_matches": count < FEW_MATCHES}


@router.post("/client/hockey/leagues/terms-preview")
async def post_client_hockey_league_terms_preview(
    body: TermsBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Перед созданием: окно дат и сколько матчей попадёт в срок."""
    now = datetime.now(timezone.utc)
    try:
        terms = _terms_from(body, now)
    except InvalidTerms as exc:
        _raise_league(exc)
    count = await matches_in_terms(session, terms, now=now)  # type: ignore[arg-type]
    return {
        **_terms_out(terms.scope, terms.clubs, terms.term_kind, terms.starts_at, terms.ends_at),  # type: ignore[union-attr]
        "matches_in_term": count,
        "few_matches": count < FEW_MATCHES,
        "monthly_crowns": terms.term_kind in MONTHLY_CROWN_TERMS,
    }


@router.get("/client/hockey/leagues/term-options")
async def get_client_hockey_league_term_options(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    """Окна сроков «до конца сезона / месяц / 4 недели / плей-офф», правило корон и лимит команд для новой лиги."""
    return term_options(now=datetime.now(timezone.utc))


@router.get("/client/hockey/leagues/quick")
async def get_client_hockey_league_quick(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Экран «Лига готова»: имя будущей лиги или своя действующая лига (тогда экран открывает её «Вечер»).
    Лигу здесь не создаём — только по кнопке «Позвать друзей»."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    existing = await own_active_league(session, player_key=player_key, now=now)
    if existing is not None:
        return {"league_id": existing.id, "name": existing.name}
    known = await player_display_name(session, player_key)
    return {
        "league_id": None,
        "name": quick_name(known or _player_name(None, _init_raw(init_data, x_telegram_init_data))),
    }


@router.post("/client/hockey/leagues/quick")
async def post_client_hockey_league_quick(
    body: QuickLeagueBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Позвать друзей»: своя лига до конца сезона в один тап. Своя действующая уже есть — вернём её (``created``)."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        league, created = await quick_league(
            session,
            player_key=player_key,
            display_name=_player_name(body.display_name, _init_raw(init_data, x_telegram_init_data)),
            now=now,
            scope=body.scope,
            clubs=body.clubs,
            stake_text=body.stake_text,
            src=body.src,
        )
        payload = await _created_out(session, league, player_key, now)
    except (ValueError, TooManyLeagues) as exc:
        _raise_league(exc)
    await session.commit()
    return {**payload, "created": created}


@router.post("/client/hockey/leagues/join")
async def post_client_hockey_league_join(
    body: JoinLeagueBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        league, added = await join_league(
            session,
            player_key=player_key,
            display_name=_player_name(body.display_name, _init_raw(init_data, x_telegram_init_data)),
            code=body.code,
        )
        payload = await _created_out(session, league, player_key, now)
    except (LookupError, LeagueFull, TooManyLeagues) as exc:
        _raise_league(exc)
    if body.from_card and added:  # двойной тап «Вступить» событие не дублирует
        await record_card_event(session, kind="joined", card=body.from_card, league_id=league.id)
    await session.commit()
    return payload


@router.get("/client/hockey/leagues/{league_id}")
async def get_client_hockey_league(
    league_id: int,
    period: str | None = Query(None, description="month | 2026-11 — часть периода; пусто — вся лига"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    chosen = None
    if period:
        try:
            chosen = parse_period(period, now)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неизвестный период") from None
    try:
        rows = await league_table(session, league_id=league_id, player_key=player_key, now=now, period=chosen)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    # Нужна только эта лига и без места: таблицу мы уже посчитали выше, остальные лиги игрока не считаем.
    summary = next(
        iter(
            await player_leagues(
                session, player_key=player_key, now=now, league_ids=[league_id], ends_after=None, with_rank=False
            )
        )
    )
    titles = await league_titles(session, league_id=league_id, now=now)
    crowns = await crown_counts(session, league_id=league_id, player_keys=[row.player_key for row in rows])
    # Минуты штрафа, стуки и кепки дня — за показанный период (месяц или весь срок лиги).
    league = await member_league(session, league_id=league_id, player_key=player_key)
    since, until = (chosen.since, chosen.until) if chosen else (league.starts_at, league.ends_at)
    marks = await period_marks(session, league, since=since, until=until, now=now)  # type: ignore[arg-type]
    # Голова и нашивка «C» — по последнему сыгранному вечеру лиги (TASK-432), в любой вкладке таблицы.
    state = await current_state(session, league, now=now)
    heads_on = captain_enabled(league.id) and state is not None and state.current
    return {
        "id": summary.id,
        "name": summary.name,
        "is_owner": summary.is_owner,
        "invite_url": invite_url_for_code(summary.invite_code),
        **_terms_out(summary.scope, summary.clubs, summary.term_kind, summary.starts_at, summary.ends_at),
        **_identity_out(summary.image_key, summary.stake_text),
        "active": summary.active,
        "period": None if chosen is None else {"key": chosen.key, "title": chosen.title},
        "race": await race_summary(session, now=now),
        "wall": await league_crown_wall(session, league_id=league_id, now=now),
        "items": [
            {
                **_table_row(row, player_key, titles),
                "crowns": crowns.get(row.player_key, 0),
                **_marks_out(marks, row),
                "head": None if state is None else state.head(row.player_key, enabled=heads_on),
                "captain": state is not None and row.player_key in state.cap.captains,
            }
            for row in rows
        ],
    }


def _marks_out(marks: dict, row: LeagueRow) -> dict:
    found = marks.get(row.player_key)
    if found is None:
        return {"penalty_minutes": 0, "sticks": 0, "caps": 0}
    return {"penalty_minutes": found.penalty_minutes, "sticks": found.sticks, "caps": found.caps}


@router.get("/client/hockey/leagues/{league_id}/evening")
async def get_client_hockey_league_evening(
    league_id: int,
    day: date | None = Query(None, description="игровой день 2026-11-18; пусто — сегодня или последний с матчами"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Вечер» лиги: матчи игрового дня, строка каждого участника, соседние дни с матчами. Только для участника."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        league = await member_league(session, league_id=league_id, player_key=player_key)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    return await league_evening(session, league=league, player_key=player_key, now=now, day=day)


@router.put("/client/hockey/leagues/{league_id}/evening/{day}/gesture")
async def put_client_hockey_league_gesture(
    league_id: int,
    day: date,
    body: GestureBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Жест другу за сыгранный день лиги: дать, сменить или снять. Пушей нет — ответ: «Вечер» этого дня."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        league = await member_league(session, league_id=league_id, player_key=player_key)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    if not gestures_enabled():
        raise HTTPException(status_code=404, detail="Жестов в лиге пока нет")
    try:
        await set_gesture(session, league=league, from_key=player_key, to_pid=body.to, day=day, kind=body.kind, now=now)
    except GestureRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DayNotPlayed as exc:
        raise HTTPException(status_code=409, detail="Жесты откроются, когда сыграют все матчи вечера") from exc
    await session.commit()
    return await league_evening(session, league=league, player_key=player_key, now=now, day=day)


@router.put("/client/hockey/leagues/{league_id}/evening/{day}/outfit")
async def put_client_hockey_league_outfit(
    league_id: int,
    day: date,
    body: OutfitBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Право капитана: выдать или поменять экипировку вечера. Пушей нет — ответ: «Вечер» этого дня."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        league = await member_league(session, league_id=league_id, player_key=player_key)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    if not captain_enabled(league.id):
        raise HTTPException(status_code=404, detail="Экипировки в лиге пока нет")
    try:
        await set_outfit(
            session, league=league, captain_key=player_key, to_pid=body.to, item=body.item, day=day, now=now
        )
    except OutfitRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotCaptain as exc:
        raise HTTPException(status_code=403, detail="Выдаёт только капитан вечера") from exc
    except RightClosed as exc:
        raise HTTPException(status_code=409, detail="Право капитана — до следующего вечера лиги") from exc
    except AlreadyGiven as exc:
        raise HTTPException(status_code=409, detail=f"Экипировку этого вечера уже выдаёт {exc.name}") from exc
    await session.commit()
    return await league_evening(session, league=league, player_key=player_key, now=now, day=day)


@router.patch("/client/hockey/leagues/{league_id}")
async def patch_client_hockey_league(
    league_id: int,
    body: PatchLeagueBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Название и «на что играем» — только владелец; в теле только то, что меняем."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    changes = {field: getattr(body, field) for field in ("name", "stake_text") if field in body.model_fields_set}
    if "name" in changes and changes["name"] is None:
        changes["name"] = ""  # «null» вместо названия — то же, что пустое: «Назови лигу»
    try:
        league = await update_league(session, league_id=league_id, player_key=player_key, **changes)
        payload = await _created_out(session, league, player_key, now)
    except (ValueError, LookupError, PermissionError) as exc:
        _raise_league(exc)
    await session.commit()
    return payload


@router.post("/client/hockey/leagues/{league_id}/image")
async def post_client_hockey_league_image(
    league_id: int,
    file: UploadFile = File(...),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Картинка лиги (JPEG, PNG или WEBP до 5 МБ) — только владелец. Заменяет прежнюю; без премодерации."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        await owned_league(session, league_id=league_id, player_key=player_key)  # чужому файл даже не читаем
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        new_key = await store_league_image(league_id, raw)
    except LeagueImageError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    try:
        league, previous = await set_league_image(
            session, league_id=league_id, player_key=player_key, image_key=new_key
        )
        payload = await _created_out(session, league, player_key, now)
    except (LookupError, PermissionError) as exc:
        await release_image(session, new_key)  # пока файл ждал, лигу удалили или передали: он никому не нужен
        _raise_league(exc)
    await session.commit()
    await release_image(session, previous)
    return payload


@router.delete("/client/hockey/leagues/{league_id}/image")
async def delete_client_hockey_league_image(
    league_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Убрать картинку лиги — только владелец. Нет картинки — ничего не меняется."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        league, previous = await set_league_image(session, league_id=league_id, player_key=player_key, image_key=None)
        payload = await _created_out(session, league, player_key, now)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    await session.commit()
    await release_image(session, previous)
    return payload


@router.post("/client/hockey/leagues/{league_id}/report")
async def post_client_hockey_league_report(
    league_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Пожаловаться на лигу: участник, не владелец. Админам уходит одно сообщение в сутки на лигу."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        report = await league_reports.report_league(session, league_id=league_id, reporter_key=player_key, now=now)
    except league_reports.OwnLeagueReport as exc:
        raise HTTPException(status_code=403, detail=_OWN_LEAGUE_REPORT) from exc
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    await session.commit()
    if report.alert and await league_reports.notify_admins(report) is False:
        # Не дошло до админов: пусть следующая жалоба попробует ещё раз, а не ждёт суток.
        await league_reports.unmark_alerted(session, report.id)
        await session.commit()
    return {"ok": True}


@router.delete("/client/hockey/leagues/{league_id}/membership")
async def delete_client_hockey_league_membership(
    league_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    player_key = client_catalog_telegram_key(principal)
    image_key = await league_image_key(session, league_id)
    try:
        result = await leave_league(session, league_id=league_id, player_key=player_key)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    await session.commit()
    if result == "deleted":  # лигу удалили вместе с последним участником: картинка больше никому не нужна
        await release_image(session, image_key)
    return {"result": result}


@router.delete("/client/hockey/leagues/{league_id}")
async def delete_client_hockey_league(
    league_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Удалить лигу для всех — только владелец. С коронами лига уходит в архив без участников."""
    player_key = client_catalog_telegram_key(principal)
    image_key = await league_image_key(session, league_id)
    try:
        result = await delete_league(session, league_id=league_id, player_key=player_key)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    await session.commit()
    if result == "deleted":
        await release_image(session, image_key)
    return {"result": result}


@router.post("/client/hockey/leagues/{league_id}/extend")
async def post_client_hockey_league_extend(
    league_id: int,
    body: ExtendLeagueBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Продлить»: новая лига с теми же людьми на следующий срок. У лиги одно продолжение — повтор вернёт его."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        terms = _terms_from(body.terms, now)
        league, created = await extend_league(session, league_id=league_id, player_key=player_key, now=now, terms=terms)
        payload = await _created_out(session, league, player_key, now)
        payload.update(await _terms_hint(session, league, now))
    except (ValueError, LookupError, PermissionError, TooManyLeagues, AlreadyExtended) as exc:
        _raise_league(exc)
    await session.commit()
    return {**payload, "created": created}
