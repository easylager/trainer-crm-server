"""Invite cards for a real public session («Пойдёшь со мной на каток?», TASK-231).

One card, many answers. The session row may disappear when the schedule is
republished, so the card keeps a snapshot. ``projected`` sessions are not marked.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.place_links import place_path
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.notification_hours import NOTIFICATION_TZ

# 0/1/i/l/o are left out so a code read aloud is not confused with another.
INVITE_CODE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
INVITE_CODE_LENGTH = 8
INVITE_KINDS = ("public_skate", "open_ice", "hockey_practice")
_INVITE_KIND_SET = frozenset(INVITE_KINDS)
_CODE_RE = re.compile(rf"^[{re.escape(INVITE_CODE_ALPHABET)}]{{{INVITE_CODE_LENGTH}}}$")
_CODE_ATTEMPTS = 8

NAME_MAX_LENGTH = 20
# Базовый фильтр имён на открытке (Q-2 эпика). Владелец дополняет списки.
# Регистр не важен, «ё» = «е».
# Корни — подстрокой имени без пробелов и дефисов: их не обойти склейкой.
INVITE_NAME_STOP_ROOTS: tuple[str, ...] = (
    "хуй",
    "пизд",
    "бляд",
    "блять",
    "ебат",
    "ебан",
    "мудак",
    "гандон",
    "пидор",
    "пидар",
    "нацист",
    "fuck",
    "bitch",
    "cunt",
)
# Слова — только целым словом: подстрокой они задевают настоящие имена
# (nazi → Nazim, Nazira; shit → Rashit; сука → Сукачёв).
INVITE_NAME_STOP_WORDS: tuple[str, ...] = (
    "сука",
    "shit",
    "nazi",
)

NOT_FOUND_DETAIL = "Приглашение не найдено."
CLOSED_DETAIL = "Этот сеанс уже нельзя принять."

_MINSK = ZoneInfo(NOTIFICATION_TZ)
_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁёІіЎў'’ʼ -]+$")
_LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁёІіЎў]")
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-"})
_FOLD = str.maketrans({"ё": "е", "і": "и", "ў": "у"})
_STATUS_ACTIVE = "active"
_DUMMY_HASH = "0" * 64

_LOAD_SESSION_FOR_CREATE = f"""
SELECT
    s.id,
    s.arena_id,
    s.kind,
    s.starts_at_utc,
    s.ends_at_utc,
    s.status,
    ({PUBLIC_ARENA_VISIBLE_SQL}) AS arena_visible
FROM ice_sessions s
JOIN arenas a ON a.id = s.arena_id
LEFT JOIN arena_profiles p ON p.arena_id = a.id
JOIN cities c ON c.id = a.city_id
WHERE s.id = :session_id
"""

_INSERT_INVITE = """
INSERT INTO ice_invites (
    code, status_key_hash, session_id, arena_id, kind,
    starts_at_utc, ends_at_utc, to_name, from_name, show_price,
    parent_code, creator_actor_hash, created_at
) VALUES (
    :code, :status_key_hash, :session_id, :arena_id, :kind,
    :starts_at_utc, :ends_at_utc, :to_name, :from_name, :show_price,
    :parent_code, :creator_actor_hash, :created_at
)
"""

_LOAD_INVITE = """
SELECT
    i.id,
    i.code,
    i.to_name,
    i.from_name,
    i.kind,
    i.show_price,
    i.session_id,
    i.arena_id,
    i.starts_at_utc,
    i.ends_at_utc,
    i.first_opened_at,
    i.status_key_hash,
    s.status AS session_status,
    s.price_adult_minor,
    s.currency_code,
    a.name AS arena_name,
    a.address AS arena_address,
    c.name AS city_name,
    p.slug AS arena_slug
FROM ice_invites i
JOIN arenas a ON a.id = i.arena_id
JOIN cities c ON c.id = a.city_id
LEFT JOIN arena_profiles p ON p.arena_id = a.id
LEFT JOIN ice_sessions s ON s.id = i.session_id
WHERE i.code = :code
"""

_NEXT_SESSION = """
SELECT
    s.id,
    s.kind,
    s.starts_at_utc,
    s.ends_at_utc,
    s.price_adult_minor,
    s.currency_code
FROM ice_sessions s
WHERE s.arena_id = :arena_id
  AND s.kind = :kind
  AND s.status = :status
  AND s.starts_at_utc > :now
  {exclude}
ORDER BY s.starts_at_utc, s.id
LIMIT 1
"""


class InviteRejected(Exception):
    """A public invite call that should become an HTTP error with a Russian ``detail``."""

    def __init__(self, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def generate_invite_code() -> str:
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_invite_name(raw: str | None, *, field: str, required: bool) -> str | None:
    """Collapse spaces. 1–20 letters, space, hyphen, apostrophe. Stop-words refused."""
    collapsed = re.sub(r"\s+", " ", (raw or "").translate(_DASHES).strip())
    if not collapsed:
        if required:
            raise InviteRejected(f"{field}: укажите имя — от 1 до {NAME_MAX_LENGTH} символов.")
        return None
    if len(collapsed) > NAME_MAX_LENGTH:
        raise InviteRejected(f"{field}: не длиннее {NAME_MAX_LENGTH} символов.")
    if _LETTER_RE.search(collapsed) is None or _NAME_RE.fullmatch(collapsed) is None:
        raise InviteRejected(f"{field}: только буквы, пробел, дефис и апостроф.")
    if _name_has_stop_word(collapsed):
        raise InviteRejected(f"{field}: это имя нельзя использовать.")
    return collapsed


def validate_answer_payload(
    *,
    device_token: str,
    tries: int,
    resist_ms: int,
    falls: int,
    tricked: bool,
) -> dict[str, Any]:
    if not isinstance(device_token, str) or not 16 <= len(device_token) <= 128:
        raise InviteRejected("device_token: от 16 до 128 символов.")
    tries_value = _bounded_int(tries, field="tries", low=0, high=10)
    resist_value = _bounded_int(resist_ms, field="resist_ms", low=0, high=600_000)
    falls_value = _bounded_int(falls, field="falls", low=0, high=5)
    if not isinstance(tricked, bool):
        raise InviteRejected("tricked: нужно да или нет.")
    return {
        "device_token": device_token,
        "tries": tries_value,
        "resist_ms": resist_value,
        "falls": falls_value,
        "tricked": tricked,
    }


async def create_invite(
    session: AsyncSession,
    *,
    session_id: int,
    to_name: str | None,
    from_name: str,
    show_price: bool,
    parent_code: str | None,
    creator_actor_hash: str | None,
    now: datetime | None = None,
) -> dict[str, str]:
    moment = _as_utc(now or datetime.now(timezone.utc))
    to_value = normalize_invite_name(to_name, field="to_name", required=False)
    from_value = normalize_invite_name(from_name, field="from_name", required=True)
    if from_value is None:
        raise InviteRejected(f"from_name: укажите имя — от 1 до {NAME_MAX_LENGTH} символов.")
    slot = await _load_session_for_create(session, session_id=session_id, now=moment)
    parent = await _existing_parent_code(session, parent_code)
    status_key = secrets.token_urlsafe(24)
    params = {
        "status_key_hash": sha256_hex(status_key),
        "session_id": int(slot["id"]),
        "arena_id": int(slot["arena_id"]),
        "kind": str(slot["kind"]),
        "starts_at_utc": _as_utc(slot["starts_at_utc"]),
        "ends_at_utc": _as_utc(slot["ends_at_utc"]),
        "to_name": to_value,
        "from_name": from_value,
        "show_price": bool(show_price),
        "parent_code": parent,
        "creator_actor_hash": creator_actor_hash,
        "created_at": moment,
    }
    code = await _insert_invite(session, params)
    await session.commit()
    return {
        "code": code,
        "status_key": status_key,
        "invite_path": f"/zovi/{code}",
        "status_path": f"/zovi/{code}/s/{status_key}",
    }


async def get_invite(
    session: AsyncSession,
    code: str,
    *,
    device_token: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = _as_utc(now or datetime.now(timezone.utc))
    row = await _load_invite(session, code)
    if row is None:
        raise InviteRejected(NOT_FOUND_DETAIL, 404)
    await session.execute(
        text("""
            UPDATE ice_invites
            SET first_opened_at = :now
            WHERE id = :id AND first_opened_at IS NULL
            """),
        {"id": int(row["id"]), "now": moment},
    )
    state = _invite_state(row, now=moment)
    payload: dict[str, Any] = {
        "code": row["code"],
        "to_name": row["to_name"],
        "from_name": row["from_name"],
        "kind": row["kind"],
        "state": state,
        "session": _snapshot_session(row),
        "next_session": None,
    }
    if state in ("gone", "past"):
        payload["next_session"] = await _next_session(session, row, now=moment)
    mine = await _my_answer(session, invite_id=int(row["id"]), device_token=device_token)
    if mine is not None:
        payload["my_answer"] = mine
    await session.commit()
    return payload


async def answer_invite(
    session: AsyncSession,
    code: str,
    *,
    device_token: str,
    tries: int,
    resist_ms: int,
    falls: int,
    tricked: bool,
    responder_actor_hash: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = _as_utc(now or datetime.now(timezone.utc))
    cleaned = validate_answer_payload(
        device_token=device_token,
        tries=tries,
        resist_ms=resist_ms,
        falls=falls,
        tricked=tricked,
    )
    row = await _load_invite(session, code)
    if row is None:
        raise InviteRejected(NOT_FOUND_DETAIL, 404)
    if _invite_state(row, now=moment) != "ok":
        raise InviteRejected(CLOSED_DETAIL, 409)
    responder_key = sha256_hex(str(cleaned["device_token"]))
    inserted = await session.execute(
        text("""
            INSERT INTO ice_invite_answers (
                invite_id, responder_key, responder_actor_hash, answered_at,
                tries, resist_ms, falls, tricked
            ) VALUES (
                :invite_id, :responder_key, :actor, :answered_at,
                :tries, :resist_ms, :falls, :tricked
            )
            ON CONFLICT (invite_id, responder_key) DO NOTHING
            RETURNING tries, resist_ms, falls, tricked, answered_at
            """),
        {
            "invite_id": int(row["id"]),
            "responder_key": responder_key,
            "actor": responder_actor_hash,
            "answered_at": moment,
            "tries": cleaned["tries"],
            "resist_ms": cleaned["resist_ms"],
            "falls": cleaned["falls"],
            "tricked": cleaned["tricked"],
        },
    )
    answer = inserted.mappings().first()
    if answer is None:
        answer = (
            (
                await session.execute(
                    text("""
                    SELECT tries, resist_ms, falls, tricked, answered_at
                    FROM ice_invite_answers
                    WHERE invite_id = :invite_id AND responder_key = :responder_key
                    """),
                    {"invite_id": int(row["id"]), "responder_key": responder_key},
                )
            )
            .mappings()
            .one()
        )
    await session.commit()
    return _answer_payload(answer)


async def get_invite_status(
    session: AsyncSession,
    code: str,
    *,
    key: str | None,
) -> dict[str, Any]:
    """Wrong key and unknown code are the same 404. The body does not say which."""
    if _CODE_RE.fullmatch(code or "") is None:
        _status_key_ok(_DUMMY_HASH, key)
        raise InviteRejected(NOT_FOUND_DETAIL, 404)
    row = await _load_invite(session, code)
    stored = str(row["status_key_hash"]) if row is not None else _DUMMY_HASH
    if row is None or not _status_key_ok(stored, key):
        raise InviteRejected(NOT_FOUND_DETAIL, 404)
    answers = (
        (
            await session.execute(
                text("""
                SELECT tries, resist_ms, falls, tricked, answered_at
                FROM ice_invite_answers
                WHERE invite_id = :invite_id
                ORDER BY answered_at, id
                """),
                {"invite_id": int(row["id"])},
            )
        )
        .mappings()
        .all()
    )
    items = [_answer_payload(item) for item in answers]
    opened = row["first_opened_at"]
    return {
        "first_opened_at": _iso(opened) if opened is not None else None,
        "answer_count": len(items),
        "answers": items,
    }


def _bounded_int(value: object, *, field: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low or value > high:
        raise InviteRejected(f"{field}: нужно целое число от {low} до {high}.")
    return value


def _compact_name(value: str) -> str:
    folded = value.casefold().translate(_FOLD)
    return re.sub(r"[^a-zа-я]+", "", folded)


def _name_has_stop_word(name: str) -> bool:
    compact = _compact_name(name)
    if not compact:
        return False
    if any(_compact_name(root) in compact for root in INVITE_NAME_STOP_ROOTS):
        return True
    words = {_compact_name(part) for part in re.split(r"[\s\-'’ʼ]+", name) if part}
    return any(_compact_name(word) in words for word in INVITE_NAME_STOP_WORDS)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _local_parts(starts: datetime, ends: datetime) -> dict[str, str]:
    start_local = _as_utc(starts).astimezone(_MINSK)
    end_local = _as_utc(ends).astimezone(_MINSK)
    return {
        "starts_at_utc": _iso(starts),
        "ends_at_utc": _iso(ends),
        "starts_at_local": start_local.strftime("%H:%M"),
        "ends_at_local": end_local.strftime("%H:%M"),
        "local_date": start_local.date().isoformat(),
    }


def _format_price(minor: int | None, currency: str | None) -> str | None:
    if minor is None:
        return None
    code = (currency or "BYN").strip() or "BYN"
    major = int(minor) / 100
    rendered = str(int(major)) if major == int(major) else f"{major:.2f}"
    return f"{rendered} {code}"


def _attach_price(
    payload: dict[str, Any],
    *,
    show_price: bool,
    minor: int | None,
    currency: str | None,
) -> None:
    if not show_price:
        return
    price = _format_price(minor, currency)
    if price is not None:
        payload["price"] = price


def _invite_state(row: Mapping[Any, Any], *, now: datetime) -> str:
    session_id = row["session_id"]
    status = row["session_status"]
    if session_id is None or status != _STATUS_ACTIVE:
        return "gone"
    if _as_utc(row["starts_at_utc"]) <= now:
        return "past"
    return "ok"


def _snapshot_session(row: Mapping[Any, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": int(row["session_id"]) if row["session_id"] is not None else None,
        **_local_parts(row["starts_at_utc"], row["ends_at_utc"]),
        "arena": _arena_payload(row),
    }
    _attach_price(
        payload,
        show_price=bool(row["show_price"]),
        minor=row["price_adult_minor"],
        currency=row["currency_code"],
    )
    return payload


def _arena_payload(row: Mapping[Any, Any]) -> dict[str, Any]:
    city = str(row["city_name"])
    slug = str(row["arena_slug"] or "").strip()
    address = row["arena_address"]
    return {
        "id": int(row["arena_id"]),
        "name": row["arena_name"],
        "address": address if address else None,
        "city": city,
        "public_path": place_path(city_name=city, slug=slug) if slug else None,
    }


def _answer_payload(row: Mapping[Any, Any]) -> dict[str, Any]:
    return {
        "tries": int(row["tries"]),
        "resist_ms": int(row["resist_ms"]),
        "falls": int(row["falls"]),
        "tricked": bool(row["tricked"]),
        "answered_at": _iso(row["answered_at"]),
    }


def _status_key_ok(stored_hash: str, key: str | None) -> bool:
    raw = "" if key is None or len(key) > 256 else key
    offered = sha256_hex(raw)
    if len(stored_hash) != len(offered):
        return False
    return hmac.compare_digest(stored_hash, offered)


async def _load_session_for_create(session: AsyncSession, *, session_id: int, now: datetime) -> Mapping[Any, Any]:
    if session_id <= 0:
        raise InviteRejected("session_id: сеанс не найден.")
    row = (
        (
            await session.execute(
                text(_LOAD_SESSION_FOR_CREATE),
                {"session_id": int(session_id), **public_scope_params()},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise InviteRejected("session_id: сеанс не найден.")
    if str(row["kind"]) not in _INVITE_KIND_SET:
        raise InviteRejected("session_id: на этот сеанс нельзя позвать.")
    if str(row["status"]) != _STATUS_ACTIVE:
        raise InviteRejected("session_id: сеанс недоступен.")
    if _as_utc(row["starts_at_utc"]) <= now:
        raise InviteRejected("session_id: сеанс уже прошёл.")
    if not row["arena_visible"]:
        raise InviteRejected("session_id: каток скрыт.")
    return row


async def _existing_parent_code(session: AsyncSession, raw: str | None) -> str | None:
    code = (raw or "").strip()
    if not code:
        return None
    found = (
        await session.execute(
            text("SELECT code FROM ice_invites WHERE code = :code"),
            {"code": code},
        )
    ).scalar_one_or_none()
    return str(found) if found else None


async def _insert_invite(session: AsyncSession, params: dict[str, Any]) -> str:
    for _attempt in range(_CODE_ATTEMPTS):
        code = generate_invite_code()
        try:
            async with session.begin_nested():
                await session.execute(text(_INSERT_INVITE), {**params, "code": code})
        except IntegrityError as exc:
            if not _is_code_collision(exc):
                raise
            continue
        return code
    raise InviteRejected("Не удалось создать приглашение. Попробуйте ещё раз.", 503)


def _is_code_collision(exc: IntegrityError) -> bool:
    orig = exc.orig
    name = getattr(orig, "constraint_name", None)
    if not name:
        diag = getattr(orig, "diag", None)
        name = getattr(diag, "constraint_name", None) if diag is not None else None
    return "uq_ice_invites_code" in f"{name or ''} {orig}"


async def _load_invite(session: AsyncSession, code: str) -> Mapping[Any, Any] | None:
    if _CODE_RE.fullmatch(code or "") is None:
        return None
    return (await session.execute(text(_LOAD_INVITE), {"code": code})).mappings().first()


async def _next_session(session: AsyncSession, row: Mapping[Any, Any], *, now: datetime) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "arena_id": int(row["arena_id"]),
        "kind": str(row["kind"]),
        "status": _STATUS_ACTIVE,
        "now": now,
    }
    exclude = ""
    if row["session_id"] is not None:
        exclude = "AND s.id <> :session_id"
        params["session_id"] = int(row["session_id"])
    found = (await session.execute(text(_NEXT_SESSION.format(exclude=exclude)), params)).mappings().first()
    if found is None:
        return None
    payload: dict[str, Any] = {
        "id": int(found["id"]),
        "kind": found["kind"],
        **_local_parts(found["starts_at_utc"], found["ends_at_utc"]),
    }
    _attach_price(
        payload,
        show_price=bool(row["show_price"]),
        minor=found["price_adult_minor"],
        currency=found["currency_code"],
    )
    return payload


async def _my_answer(session: AsyncSession, *, invite_id: int, device_token: str | None) -> dict[str, Any] | None:
    token = device_token or ""
    if not 16 <= len(token) <= 128:
        return None
    found = (
        (
            await session.execute(
                text("""
                SELECT tries, resist_ms, falls, tricked, answered_at
                FROM ice_invite_answers
                WHERE invite_id = :invite_id AND responder_key = :responder_key
                """),
                {"invite_id": invite_id, "responder_key": sha256_hex(token)},
            )
        )
        .mappings()
        .first()
    )
    if found is None:
        return None
    return _answer_payload(found)
