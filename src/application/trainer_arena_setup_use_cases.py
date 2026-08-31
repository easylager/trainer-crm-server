"""Arena setup when the public catalog list is empty: mobile format or moderator request."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.support_use_cases import create_support_message
from src.infrastructure.db.models import SUPPORT_FROM_TRAINER
from src.infrastructure.repositories.trainer_repository import TrainerRepository

ARENA_WORK_FORMAT_MOBILE = "mobile"
ARENA_WORK_FORMAT_PENDING_REQUEST = "pending_request"


def tt_minimal_arenas_satisfied(trainer: dict[str, Any]) -> bool:
    """TTV gate: real arenas, mobile format, or a pending arena request all count."""
    aids = trainer.get("arena_ids")
    if aids:
        return True
    fmt = (trainer.get("arena_work_format") or "").strip()
    if fmt == ARENA_WORK_FORMAT_MOBILE:
        return True
    if fmt == ARENA_WORK_FORMAT_PENDING_REQUEST:
        return bool((trainer.get("arena_request_text") or "").strip())
    return False


async def set_trainer_arena_mobile(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return None
    await repo.set_trainer_arena_setup(
        trainer_id,
        work_format=ARENA_WORK_FORMAT_MOBILE,
        request_text=None,
        request_at=None,
    )
    await session.commit()
    return await repo.get_by_id(trainer_id)


async def submit_trainer_arena_request(
    session: AsyncSession,
    trainer_id: int,
    *,
    arena_name: str,
    note: str | None,
    telegram_id: int | None,
) -> dict[str, Any] | None:
    repo = TrainerRepository(session)
    trainer = await repo.get_by_id(trainer_id)
    if not trainer:
        return None
    name = (arena_name or "").strip()
    if not name:
        raise ValueError("Укажите название площадки.")
    if len(name) > 200:
        raise ValueError("Название площадки — не длиннее 200 символов.")
    extra = (note or "").strip()
    if len(extra) > 800:
        raise ValueError("Комментарий — не длиннее 800 символов.")

    profile = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    city_id = profile.get("city_id")
    city_name = ""
    if city_id is not None:
        r = await session.execute(
            text("SELECT name FROM cities WHERE id = :cid"),
            {"cid": int(city_id)},
        )
        row = r.fetchone()
        if row and row[0]:
            city_name = str(row[0]).strip()

    request_text = name
    if extra:
        request_text = f"{name} — {extra}"

    now = datetime.now(timezone.utc)
    await repo.set_trainer_arena_setup(
        trainer_id,
        work_format=ARENA_WORK_FORMAT_PENDING_REQUEST,
        request_text=request_text[:1000],
        request_at=now,
    )

    if telegram_id:
        city_line = f"Город: {city_name} (id={city_id})" if city_id else "Город: не указан"
        support_body = (
            "Заявка на добавление арены (онбординг тренера)\n\n"
            f"Тренер id={trainer_id}\n"
            f"{city_line}\n"
            f"Площадка: {name}\n"
        )
        if extra:
            support_body += f"Комментарий: {extra}\n"
        await create_support_message(
            session,
            int(telegram_id),
            SUPPORT_FROM_TRAINER,
            support_body.strip(),
            admin_notify_source_tag="профиль тренера · заявка на арену",
        )
    else:
        await session.commit()

    return await repo.get_by_id(trainer_id)
