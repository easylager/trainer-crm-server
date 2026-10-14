"""«от N за занятие» у тренера — самое дешёвое занятие, которое можно купить (TASK-265, решение владельца 2026-10-14).

Кандидаты: цена услуги, цена тарифа (детский, взрослый, «на двоих» — за занятие целиком),
групповое занятие и абонемент в пересчёте на занятие. Абонемент делим на число занятий
с округлением вниз — как `pass_product_use_cases.enrich_pass_items_with_catalog_reference_prices`,
чтобы сайт и Mini App показывали одну цифру.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _positive(value: Any) -> int | None:
    try:
        cents = int(value)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


async def load_pass_min_per_session(session: AsyncSession, trainer_ids: Iterable[int]) -> dict[int, int]:
    """trainer_id → самая низкая цена занятия среди активных абонементов (копейки, вниз)."""
    ids = sorted({int(t) for t in trainer_ids})
    if not ids:
        return {}
    rows = await session.execute(
        text(
            """
            SELECT trainer_id, MIN(price_cents / sessions_total) AS per_session
            FROM trainer_pass_products
            WHERE trainer_id = ANY(:ids) AND is_active = true AND sessions_total > 0 AND price_cents > 0
            GROUP BY trainer_id
            """
        ),
        {"ids": ids},
    )
    return {int(r[0]): int(r[1]) for r in rows.fetchall()}


def trainer_min_session_price(
    trainer: Mapping[str, Any], *, pass_min_cents: int | None
) -> tuple[int, str] | None:
    """(копейки, валюта) самого дешёвого занятия или ``None``, если цен нет."""
    services = list(trainer.get("services") or [])
    currency = next((str(s["currency_code"]) for s in services if s.get("currency_code")), "BYN")
    candidates: list[int] = []
    for s in services:
        for key in ("price_cents", "group_price_cents"):
            cents = _positive(s.get(key))
            if cents is not None:
                candidates.append(cents)
        for tier in s.get("price_tiers") or []:
            cents = _positive(tier.get("price_cents"))
            if cents is not None:
                candidates.append(cents)
    pass_cents = _positive(pass_min_cents)
    if pass_cents is not None:
        candidates.append(pass_cents)
    if not candidates:
        return None
    return min(candidates), currency


async def enrich_min_session_price(session: AsyncSession, trainers: list[dict[str, Any]]) -> None:
    """Дописывает ``min_session_price_cents`` / ``min_session_price_currency`` (или ``None``)."""
    pass_min = await load_pass_min_per_session(session, (int(t["id"]) for t in trainers))
    for trainer in trainers:
        found = trainer_min_session_price(trainer, pass_min_cents=pass_min.get(int(trainer["id"])))
        trainer["min_session_price_cents"] = found[0] if found else None
        trainer["min_session_price_currency"] = found[1] if found else None
