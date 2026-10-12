"""Запись звеньев воронки открытки «Пойдёшь со мной на каток?» (TASK-237).

Пишем в ``catalog_consumer_events``. Сервер пишет всё, что знает сам (создали, открыли, «да»);
клиентский маячок нужен только для того, чего сервер не видит (``invite_no_attempt``,
``invite_send_answer``).

**Склейка людей.** ``actor_hash`` от IP+UA у получателя ненадёжен (встроенный браузер Threads и
Safari дают разные хэши), поэтому в ``payload`` каждого события лежит ещё ``device`` — sha256 токена
``zovi_device``, тот же, что ``responder_key`` в ``ice_invite_answers``, — и ``code`` приглашения.

**Дедуп.** Общий ``event_dedup_hash`` (вид, поверхность, актёр, сутки, город, арена) для воронки
не годится: два приглашения на одну арену за день от одного человека схлопнулись бы в одно.
Поэтому здесь свой ключ ``sha256(zovi|вид|код|кто)``: код приглашения входит в ключ, «кто» —
токен устройства (нет его — актёр). Для ``invite_create`` кто = сам код: он уникален, дедуп не
режет ничего. Без «кто» дедупа нет вовсе. Ключ задаётся в ``record_catalog_consumer_event``
параметром ``dedup_key``, секрет актёра для него не нужен — события пишутся и без секрета.

Запись никогда не ломает запрос: вызывать **после** коммита основной работы.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import (
    KIND_INVITE_CREATE,
    KIND_INVITE_NO_ATTEMPT,
    KIND_INVITE_OPEN,
    KIND_INVITE_SEND_ANSWER,
    KIND_INVITE_YES,
    record_catalog_consumer_event,
)
from src.application.ice_invites import sha256_hex
from src.application.place_links import clean_share_src

logger = logging.getLogger(__name__)

SURFACE_INVITE = "zovi_invite"

#: Откуда человек пришёл на ``/zovi`` (TASK-236). Нет значения — прямой заход.
VIA_VALUES = ("arena_card", "ice_list", "place")
#: Виды, которые принимает клиентский маячок. Остальные — только от сервера.
BEACON_KINDS = (KIND_INVITE_NO_ATTEMPT, KIND_INVITE_SEND_ANSWER)
ACT_MAX = 10
DEVICE_TOKEN_MIN = 16
DEVICE_TOKEN_MAX = 128

_LOAD_CONTEXT = """
SELECT i.code, i.arena_id, a.city_id, i.kind, i.to_name, i.parent_code
FROM ice_invites i
JOIN arenas a ON a.id = i.arena_id
WHERE i.code = :code
"""


def clean_via(raw: object) -> str | None:
    value = str(raw or "").strip().lower()
    return value if value in VIA_VALUES else None


def device_hash(token: object) -> str | None:
    """sha256 токена устройства, как ``responder_key``. Токен не по длине — ``None``."""
    if not isinstance(token, str) or not DEVICE_TOKEN_MIN <= len(token) <= DEVICE_TOKEN_MAX:
        return None
    return sha256_hex(token)


def clean_act(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= ACT_MAX:
        return None
    return raw


def funnel_dedup_key(kind: str, code: str, who: str | None) -> str | None:
    if not who:
        return None
    return hashlib.sha256(f"zovi|{kind}|{code}|{who}".encode()).hexdigest()


def funnel_payload(
    ctx: Mapping[str, Any],
    *,
    device: str | None,
    src: str | None = None,
    via: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Склейка и разрезы: код, устройство, вид сеанса, канал, вход, родитель, «одному / компании»."""
    payload: dict[str, Any] = {
        "code": ctx["code"],
        "kind": ctx["kind"],
        "audience": "one" if ctx["to_name"] else "company",
    }
    if device:
        payload["device"] = device
    if src:
        payload["src"] = src
    if via:
        payload["via"] = via
    if ctx["parent_code"]:
        payload["parent_code"] = ctx["parent_code"]
    payload.update(extra or {})
    return payload


async def load_invite_context(session: AsyncSession, code: str) -> Mapping[str, Any] | None:
    row = (await session.execute(text(_LOAD_CONTEXT), {"code": code})).mappings().first()
    return dict(row) if row is not None else None


async def _record(
    session: AsyncSession,
    *,
    kind: str,
    code: str,
    actor_hash: str | None,
    device: str | None,
    dedup_who: str | None,
    src: str | None = None,
    via: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> bool:
    """Одна строка воронки. Любой сбой гасится: основной ответ уже ушёл в коммит."""
    try:
        ctx = await load_invite_context(session, code)
        if ctx is None:
            return False
        key = funnel_dedup_key(kind, code, dedup_who)
        inserted = await record_catalog_consumer_event(
            session,
            kind=kind,
            surface=SURFACE_INVITE,
            actor_hash=actor_hash,
            city_id=ctx["city_id"],
            arena_id=ctx["arena_id"],
            payload=funnel_payload(ctx, device=device, src=src, via=via, extra=extra),
            dedup=False,
            dedup_key=key,
        )
        if not inserted and key and kind == KIND_INVITE_NO_ATTEMPT:
            await _raise_act(session, key, (extra or {}).get("act"))
        return inserted
    except Exception:  # noqa: BLE001 — воронка не должна ронять приглашение
        logger.exception("zovi funnel event failed kind=%s", kind)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


async def _raise_act(session: AsyncSession, key: str, act: object) -> None:
    """``invite_no_attempt`` — одна строка на открытие; номер акта в ней только растёт."""
    value = clean_act(act)
    if value is None:
        return
    await session.execute(
        text("""
            UPDATE catalog_consumer_events
            SET payload = jsonb_set(payload, '{act}', to_jsonb(CAST(:act AS integer)))
            WHERE dedup_key = :key
              AND COALESCE((payload->>'act')::integer, -1) < :act
            """),
        {"key": key, "act": value},
    )
    await session.commit()


async def record_invite_created(
    session: AsyncSession,
    *,
    code: str,
    actor_hash: str | None,
    device_token: object = None,
    src: object = None,
    via: object = None,
) -> bool:
    return await _record(
        session,
        kind=KIND_INVITE_CREATE,
        code=code,
        actor_hash=actor_hash,
        device=device_hash(device_token),
        dedup_who=code,
        src=clean_share_src(str(src) if src else None),
        via=clean_via(via),
    )


async def record_invite_opened(
    session: AsyncSession,
    *,
    code: str,
    actor_hash: str | None,
    device_token: object = None,
    src: object = None,
) -> bool:
    """Первое открытие этим устройством. Повтор того же устройства строку не добавляет."""
    device = device_hash(device_token)
    return await _record(
        session,
        kind=KIND_INVITE_OPEN,
        code=code,
        actor_hash=actor_hash,
        device=device,
        dedup_who=device or actor_hash,
        src=clean_share_src(str(src) if src else None),
    )


async def record_invite_answered(
    session: AsyncSession,
    *,
    code: str,
    actor_hash: str | None,
    device_token: object,
    tries: int,
    tricked: bool,
) -> bool:
    """«Да» — только когда ответ вставлен, а не вернулся существующий (решает вызывающий)."""
    device = device_hash(device_token)
    return await _record(
        session,
        kind=KIND_INVITE_YES,
        code=code,
        actor_hash=actor_hash,
        device=device,
        dedup_who=device or actor_hash,
        extra={"tries": tries, "tricked": bool(tricked)},
    )


async def record_invite_beacon(
    session: AsyncSession,
    *,
    code: str,
    kind: object,
    device_token: object,
    act: object,
    actor_hash: str | None,
) -> bool:
    """Маячок страницы. Неизвестный вид и неверное устройство — без записи."""
    if kind not in BEACON_KINDS:
        return False
    device = device_hash(device_token)
    if device is None:
        return False
    value = clean_act(act)
    extra = {"act": value} if kind == KIND_INVITE_NO_ATTEMPT and value is not None else None
    return await _record(
        session,
        kind=str(kind),
        code=code,
        actor_hash=actor_hash,
        device=device,
        dedup_who=device,
        extra=extra,
    )
