"""Прогрев посетителей: цифры для админки и недельного отчёта владельцу (TASK-428, слой D). Только читает.

* Разовые — актёры (люди, не боты и не служебные аккаунты) с просмотром сайта или входом в Mini App за окно, у кого
  за 30 суток до конца окна ровно один день визита по Минску.
* Из них достижимые — те, чей ``actor_hash`` совпал с ``telegram_actor_hash`` клиента, который запускал бота, не
  заблокировал его и не нажимал «Не присылать». Совпадение считается в памяти и нигде не хранится. Веб-посетителей
  так не достать: у них хэш от IP и браузера.
* Воронка предложения подписки — события ``watch_offer_*`` за окно (по одному каждого вида на актёра и каток).
* Отправлено / не дошло — ``warm_notices``; заблокировали и «Не присылать» — ``warm_prefs`` за окно; «ушло бы в сухом
  прогоне» — журнал решений (разные люди и поводы).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import (
    KIND_MINIAPP_CATALOG_ENTRY,
    KIND_PUBLIC_PAGE_VIEW,
    KIND_WATCH_OFFER_CLICK,
    KIND_WATCH_OFFER_CLOSED,
    KIND_WATCH_OFFER_SHOWN,
    KIND_WATCH_OFFER_SUBSCRIBED,
    catalog_actor_exclusion_sql,
)
from src.application.client_ice_watch_use_cases import ICE_WATCH_STATS_EXCLUDED_TELEGRAM_IDS
from src.application.kk_notify_gate import WARM_KINDS

LOOKBACK = timedelta(days=30)
KIND_LABELS = {
    "warm_welcome": "после подписки",
    "warm_today": "«сегодня лёд»",
    "warm_week": "сеансы на неделю",
    "warm_nudge": "напоминание",
}


@dataclass(frozen=True)
class WarmStats:
    since: datetime
    until: datetime
    one_time: int = 0
    reachable: int = 0
    offer: dict[str, int] = field(default_factory=dict)  # shown / click / closed / subscribed
    sent: dict[str, int] = field(default_factory=dict)
    failed: int = 0
    blocked: int = 0
    opted_out: int = 0
    dry_run: dict[str, int] = field(default_factory=dict)
    active_watches: int = 0

    @property
    def sent_total(self) -> int:
        return sum(self.sent.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "one_time": self.one_time,
            "reachable": self.reachable,
            "offer": dict(self.offer),
            "sent": dict(self.sent),
            "sent_total": self.sent_total,
            "failed": self.failed,
            "blocked": self.blocked,
            "opted_out": self.opted_out,
            "dry_run": dict(self.dry_run),
            "active_watches": self.active_watches,
        }


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


_REACHABLE = text("""
    SELECT DISTINCT c.telegram_id FROM clients AS c
    WHERE c.telegram_id > 0 AND NOT COALESCE(c.is_sandbox, false)
      AND NOT EXISTS (SELECT 1 FROM warm_prefs AS p WHERE p.telegram_id = c.telegram_id
                      AND (p.opted_out_at IS NOT NULL OR p.bot_blocked_at IS NOT NULL))
      AND NOT EXISTS (SELECT 1 FROM hockey_player_prefs AS hp WHERE hp.player_key = c.telegram_id
                      AND (hp.bot_blocked_at IS NOT NULL OR hp.remind IS FALSE OR hp.notify_consent IS FALSE))
    """)


async def _one_time_actors(session: AsyncSession, since: datetime, until: datetime) -> list[str]:
    ex_sql, ex_params = catalog_actor_exclusion_sql("e.actor_hash")
    rows = await session.execute(
        text(f"""
            WITH recent AS (
                SELECT DISTINCT e.actor_hash FROM catalog_consumer_events AS e
                WHERE e.occurred_at >= :since AND e.occurred_at < :until AND e.actor_hash IS NOT NULL
                  AND e.kind IN (:pv, :mini) AND COALESCE(e.payload->>'ua_class', 'human') = 'human' {ex_sql}
            )
            SELECT e.actor_hash FROM catalog_consumer_events AS e JOIN recent AS r ON r.actor_hash = e.actor_hash
            WHERE e.occurred_at >= :month AND e.occurred_at < :until AND e.kind IN (:pv, :mini)
            GROUP BY e.actor_hash
            HAVING COUNT(DISTINCT (e.occurred_at AT TIME ZONE 'Europe/Minsk')::date) = 1
            """),
        {
            "since": since,
            "until": until,
            "month": until - LOOKBACK,
            "pv": KIND_PUBLIC_PAGE_VIEW,
            "mini": KIND_MINIAPP_CATALOG_ENTRY,
            **ex_params,
        },
    )
    return [str(r[0]) for r in rows.all()]


async def collect(session: AsyncSession, *, since: datetime, until: datetime) -> WarmStats:
    from src.application.warm_notify import _hash_map

    since, until = _utc(since), _utc(until)
    window = {"since": since, "until": until}
    one_time = await _one_time_actors(session, since, until)
    reachable_ids = [int(r[0]) for r in (await session.execute(_REACHABLE)).all()]
    reachable_hashes = set(_hash_map(reachable_ids))  # в памяти, только на этот подсчёт
    offer_kinds = {
        KIND_WATCH_OFFER_SHOWN: "shown",
        KIND_WATCH_OFFER_CLICK: "click",
        KIND_WATCH_OFFER_CLOSED: "closed",
        KIND_WATCH_OFFER_SUBSCRIBED: "subscribed",
    }
    offer_rows = await session.execute(
        text("""
            SELECT kind, COUNT(*) FROM catalog_consumer_events
            WHERE kind = ANY(:kinds) AND occurred_at >= :since AND occurred_at < :until GROUP BY kind
            """),
        {**window, "kinds": list(offer_kinds)},
    )
    offer = {name: 0 for name in offer_kinds.values()}
    for kind, n in offer_rows.all():
        offer[offer_kinds[kind]] = int(n)
    sent = {
        str(k): int(n)
        for k, n in (
            await session.execute(
                text("""
                    SELECT kind, COUNT(*) FROM warm_notices
                    WHERE sent_at >= :since AND sent_at < :until GROUP BY kind
                    """),
                window,
            )
        ).all()
    }
    failed = (
        await session.execute(
            text("SELECT COUNT(*) FROM warm_notices WHERE failed AND created_at >= :since AND created_at < :until"),
            window,
        )
    ).scalar_one()
    prefs = (
        await session.execute(
            text("""
                SELECT COUNT(*) FILTER (WHERE bot_blocked_at >= :since AND bot_blocked_at < :until),
                       COUNT(*) FILTER (WHERE opted_out_at >= :since AND opted_out_at < :until)
                FROM warm_prefs
                """),
            window,
        )
    ).one()
    dry = {
        str(k): int(n)
        for k, n in (
            await session.execute(
                text("""
                    SELECT kind, COUNT(DISTINCT player_key) FROM kk_notify_decisions
                    WHERE decision = 'dry_run' AND kind = ANY(:kinds) AND tick_at >= :since AND tick_at < :until
                    GROUP BY kind
                    """),
                {**window, "kinds": list(WARM_KINDS)},
            )
        ).all()
    }
    watches = (
        await session.execute(
            text("""
                SELECT COUNT(*) FROM client_ice_watches
                WHERE active AND watch_kind IN ('sessions', 'schedule_fresh') AND telegram_id <> ALL(:excluded)
                """),
            {"excluded": list(ICE_WATCH_STATS_EXCLUDED_TELEGRAM_IDS)},
        )
    ).scalar_one()
    return WarmStats(
        since=since,
        until=until,
        one_time=len(one_time),
        reachable=sum(1 for h in one_time if h in reachable_hashes),
        offer=offer,
        sent=sent,
        failed=int(failed or 0),
        blocked=int(prefs[0] or 0),
        opted_out=int(prefs[1] or 0),
        dry_run=dry,
        active_watches=int(watches or 0),
    )


async def admin_slice(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Срез для «Статистики» админки: последние 7 суток."""
    until = _utc(now or datetime.now(timezone.utc))
    return (await collect(session, since=until - timedelta(days=7), until=until)).as_dict()


def _kinds_line(counts: dict[str, int]) -> str:
    parts = [f"{KIND_LABELS.get(k, k)} {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n]
    return ", ".join(parts)


def render_section(data: WarmStats) -> str:
    """Блок для недельного отчёта владельцу (тот же текстовый стиль, что у отчёта игры)."""
    o = data.offer
    lines = [
        "<b>Разовые посетители</b>",
        f"Разовых за неделю: {data.one_time}, из них можно написать: {data.reachable}.",
        f"Подписок на катки активно: {data.active_watches}.",
        (
            f"Предложение подписки: показано {o.get('shown', 0)}, нажали {o.get('click', 0)}, "
            f"подписались {o.get('subscribed', 0)}, закрыли {o.get('closed', 0)}."
        ),
    ]
    if data.sent_total:
        lines.append(f"Отправлено {data.sent_total}: {_kinds_line(data.sent)}.")
    else:
        lines.append("Отправлено: ничего.")
    if data.dry_run:
        lines.append(f"В сухом прогоне ушло бы (разных людей): {_kinds_line(data.dry_run)}.")
    lines.append(
        f"Не дошло: {data.failed}. Заблокировали бота: {data.blocked}. Нажали «Не присылать»: {data.opted_out}."
    )
    return "\n".join(lines)


__all__ = ["KIND_LABELS", "WarmStats", "admin_slice", "collect", "render_section"]
