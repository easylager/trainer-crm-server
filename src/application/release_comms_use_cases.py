"""Release comms: parse message files, resolve audiences, broadcast via client/trainer bots."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_PROFILE,
    Client,
    ClientFamilyAccessMember,
    Trainer,
)
from src.shared.audit import ACTOR_ADMIN_BOT, audit_log
from src.shared.config import Settings

logger = logging.getLogger(__name__)

Audience = Literal["clients", "trainers"]
TrainerSegment = Literal["all", "pending_profile"]
DELIVERY_LOG_DIR = Path("var/release-comms")
DEFAULT_SEND_DELAY_SEC = 0.05
TRAINER_SEGMENTS: frozenset[str] = frozenset({"all", "pending_profile"})


@dataclass(frozen=True)
class ReleaseCommsSpec:
    release_id: str
    audience: Audience
    button_text: str | None
    webapp_path: str | None
    html_body: str
    source_path: Path | None = None
    segment: str | None = None


@dataclass
class BroadcastResult:
    release_id: str
    audience: Audience
    dry_run: bool
    total: int
    sent: int
    skipped: int
    failed: int
    errors: list[dict[str, Any]]


def parse_release_comms_file(path: Path) -> ReleaseCommsSpec:
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    release_id = (meta.get("release_id") or path.stem).strip()
    audience_raw = (meta.get("audience") or "clients").strip().lower()
    if audience_raw not in ("clients", "trainers"):
        raise ValueError(f"Invalid audience {audience_raw!r} in {path}")
    audience: Audience = audience_raw  # type: ignore[assignment]
    button_text = (meta.get("button_text") or "").strip() or None
    webapp_path = (meta.get("webapp_path") or "").strip() or None
    segment_raw = (meta.get("segment") or "all").strip().lower()
    if audience == "trainers":
        if segment_raw not in TRAINER_SEGMENTS:
            raise ValueError(f"Invalid trainer segment {segment_raw!r} in {path}")
        segment = segment_raw
    else:
        if segment_raw not in ("", "all"):
            raise ValueError(f"segment is only for trainers, got {segment_raw!r} in {path}")
        segment = "all"
    html_body = body.strip()
    if not html_body:
        raise ValueError(f"Empty message body in {path}")
    return ReleaseCommsSpec(
        release_id=release_id,
        audience=audience,
        button_text=button_text,
        webapp_path=webapp_path,
        html_body=html_body,
        source_path=path,
        segment=segment,
    )


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---"):
        return {}, content.strip()
    end = content.find("---", 3)
    if end == -1:
        return {}, content.strip()
    block = content[3:end].strip()
    body = content[end + 3 :].strip()
    meta: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def delivery_log_path(release_id: str, audience: Audience) -> Path:
    safe_id = release_id.replace("/", "_")
    return DELIVERY_LOG_DIR / f"{safe_id}.{audience}.json"


def load_delivery_log(release_id: str, audience: Audience) -> set[int]:
    path = delivery_log_path(release_id, audience)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {int(x) for x in data.get("sent_telegram_ids", [])}
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Corrupt delivery log %s — treating as empty", path)
        return set()


def save_delivery_log(
    release_id: str,
    audience: Audience,
    sent_ids: set[int],
    failed: list[dict[str, Any]],
) -> None:
    path = delivery_log_path(release_id, audience)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "release_id": release_id,
        "audience": audience,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sent_telegram_ids": sorted(sent_ids),
        "failed": failed,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def fetch_audience_telegram_ids(
    session: AsyncSession,
    audience: Audience,
    *,
    segment: str | None = None,
) -> list[int]:
    if audience == "trainers":
        q = select(Trainer.telegram_id).where(
            Trainer.telegram_id.is_not(None),
            Trainer.status != TRAINER_STATUS_DEACTIVATED,
        )
        if (segment or "all") == "pending_profile":
            q = q.where(Trainer.status == TRAINER_STATUS_PENDING_PROFILE)
        rows = await session.scalars(q)
        return sorted({int(tid) for tid in rows if tid is not None})

    primary = select(Client.telegram_id).where(
        Client.telegram_id.is_not(None),
        Client.is_sandbox.is_(False),
    )
    family = select(ClientFamilyAccessMember.member_telegram_id)
    rows = await session.scalars(union(primary, family))
    return sorted({int(tid) for tid in rows if tid is not None})


def build_webapp_markup(settings: Settings, spec: ReleaseCommsSpec) -> InlineKeyboardMarkup | None:
    if not spec.button_text or not spec.webapp_path:
        return None
    base = (settings.webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    path = spec.webapp_path if spec.webapp_path.startswith("/") else f"/{spec.webapp_path}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=spec.button_text,
                    web_app=WebAppInfo(url=f"{base}{path}"),
                ),
            ],
        ],
    )


def _bot_for_audience(settings: Settings, audience: Audience) -> Bot:
    token = (
        settings.telegram_bot_token_client
        if audience == "clients"
        else settings.telegram_bot_token_trainer
    )
    if not token:
        raise RuntimeError(f"Missing bot token for audience={audience}")
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def broadcast_release_comms(
    session: AsyncSession,
    spec: ReleaseCommsSpec,
    *,
    settings: Settings | None = None,
    dry_run: bool = False,
    chat_id: int | None = None,
    force: bool = False,
    limit: int | None = None,
    send_delay_sec: float = DEFAULT_SEND_DELAY_SEC,
) -> BroadcastResult:
    settings = settings or Settings()
    already_sent = set() if (force or chat_id is not None) else load_delivery_log(spec.release_id, spec.audience)
    markup = build_webapp_markup(settings, spec)

    if chat_id is not None:
        targets = [chat_id]
    else:
        targets = await fetch_audience_telegram_ids(
            session, spec.audience, segment=spec.segment
        )
        if limit is not None:
            targets = targets[: max(0, limit)]

    to_send = [tid for tid in targets if tid not in already_sent]
    skipped = len(targets) - len(to_send)

    result = BroadcastResult(
        release_id=spec.release_id,
        audience=spec.audience,
        dry_run=dry_run,
        total=len(targets),
        sent=0,
        skipped=skipped,
        failed=0,
        errors=[],
    )

    if dry_run:
        logger.info(
            "release_comms dry-run release_id=%s audience=%s total=%s would_send=%s skipped=%s",
            spec.release_id,
            spec.audience,
            result.total,
            len(to_send),
            skipped,
        )
        if to_send[:5]:
            logger.info("sample telegram_ids: %s", to_send[:5])
        return result

    bot = _bot_for_audience(settings, spec.audience)
    sent_ids = set(already_sent)
    try:
        for tid in to_send:
            try:
                await bot.send_message(
                    chat_id=tid,
                    text=spec.html_body,
                    reply_markup=markup,
                )
                sent_ids.add(tid)
                result.sent += 1
                audit_log(
                    "release_comms.sent",
                    ACTOR_ADMIN_BOT,
                    "broadcast_script",
                    {
                        "release_id": spec.release_id,
                        "audience": spec.audience,
                        "telegram_id": tid,
                    },
                )
            except TelegramRetryAfter as exc:
                wait = float(exc.retry_after or 1) + 0.5
                logger.warning("rate limited, sleeping %.1fs", wait)
                await asyncio.sleep(wait)
                await bot.send_message(
                    chat_id=tid,
                    text=spec.html_body,
                    reply_markup=markup,
                )
                sent_ids.add(tid)
                result.sent += 1
            except TelegramForbiddenError:
                result.failed += 1
                result.errors.append({"telegram_id": tid, "error": "forbidden"})
            except Exception as exc:
                result.failed += 1
                result.errors.append({"telegram_id": tid, "error": str(exc)[:200]})
                logger.exception("release_comms send failed telegram_id=%s", tid)
            if send_delay_sec > 0:
                await asyncio.sleep(send_delay_sec)
    finally:
        await bot.session.close()

    if chat_id is None:
        save_delivery_log(spec.release_id, spec.audience, sent_ids, result.errors)

    audit_log(
        "release_comms.batch_done",
        ACTOR_ADMIN_BOT,
        "broadcast_script",
        {
            "release_id": spec.release_id,
            "audience": spec.audience,
            "sent": result.sent,
            "failed": result.failed,
            "skipped": result.skipped,
        },
    )
    return result
