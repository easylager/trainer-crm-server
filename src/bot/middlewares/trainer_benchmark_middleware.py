"""
Outer Update middleware: wall-clock time for the full trainer bot pipeline (after rate limit).

Logs one line per update when TRAINER_BOT_BENCHMARK_LOG or TRAINER_BOT_BENCHMARK_SLOW_MS is set.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from src.bot import trainer_benchmark_config as bench_cfg

bench_log = logging.getLogger("trainer_bot.bench")

_MAX_DETAIL = 96


def _update_detail(u: Update) -> tuple[str, int | None, str]:
    """Return (kind, user_id, short detail for grep)."""
    if u.message:
        uid = u.message.from_user.id if u.message.from_user else None
        raw = u.message.text or u.message.caption or ""
        d = raw.replace("\n", " ").strip()[:_MAX_DETAIL]
        return "message", uid, d
    if u.edited_message:
        uid = u.edited_message.from_user.id if u.edited_message.from_user else None
        raw = u.edited_message.text or u.edited_message.caption or ""
        d = raw.replace("\n", " ").strip()[:_MAX_DETAIL]
        return "edited_message", uid, d
    if u.callback_query:
        uid = u.callback_query.from_user.id if u.callback_query.from_user else None
        d = (u.callback_query.data or "")[:_MAX_DETAIL]
        return "callback_query", uid, d
    if u.inline_query:
        uid = u.inline_query.from_user.id if u.inline_query.from_user else None
        d = (u.inline_query.query or "")[:_MAX_DETAIL]
        return "inline_query", uid, d
    if u.chosen_inline_result:
        uid = u.chosen_inline_result.from_user.id if u.chosen_inline_result.from_user else None
        return "chosen_inline_result", uid, ""
    return "other", None, ""


class TrainerBenchmarkMiddleware(BaseMiddleware):
    """Time entire update handling; emit structured BENCH line for analysis."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not bench_cfg.is_active() or not isinstance(event, Update):
            return await handler(event, data)

        t0 = time.perf_counter()
        exc_name: str | None = None
        try:
            return await handler(event, data)
        except BaseException as e:
            exc_name = type(e).__name__
            raise
        finally:
            total_ms = (time.perf_counter() - t0) * 1000
            if bench_cfg.log_every_update or bench_cfg.is_slow_total(total_ms):
                kind, uid, detail = _update_detail(event)
                slow = 1 if bench_cfg.is_slow_total(total_ms) else 0
                extra = ""
                if exc_name:
                    extra = f" exc={exc_name}"
                if detail:
                    safe = detail.replace("%", "%%")
                    extra += f" detail={safe!r}"
                msg = (
                    f"BENCH trainer_update update_id={event.update_id} kind={kind} "
                    f"user_id={uid} total_ms={total_ms:.1f} slow={slow}{extra}"
                )
                if bench_cfg.is_slow_total(total_ms) and not bench_cfg.log_every_update:
                    bench_log.warning(msg)
                else:
                    bench_log.info(msg)
