"""«от N» у тренера — минимальная цена тарифа его услуг (TASK-352).

У услуги берём тарифы (``trainer_service_price_variants``: детский, взрослый, «на двоих» — за
занятие целиком); услуга без тарифов — её ``price_cents``. Групповые цены и абонементы в «от» не
входят: это другие продукты, а у абонемента к тому же делённая цена («41,87»), которой нет в
прайсе. Сайт, Mini App и страница тренера берут цифру только отсюда.
"""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession


def _positive(value: Any) -> int | None:
    try:
        cents = int(value)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


def trainer_min_session_price(trainer: Mapping[str, Any]) -> tuple[int, str] | None:
    """(копейки, валюта) самого дешёвого тарифа или ``None``, если цен нет."""
    services = list(trainer.get("services") or [])
    currency = next((str(s["currency_code"]) for s in services if s.get("currency_code")), "BYN")
    candidates: list[int] = []
    for s in services:
        tier_prices = [_positive(t.get("price_cents")) for t in s.get("price_tiers") or []]
        tier_prices = [c for c in tier_prices if c is not None]
        if tier_prices:
            candidates.extend(tier_prices)
            continue
        cents = _positive(s.get("price_cents"))
        if cents is not None:
            candidates.append(cents)
    if not candidates:
        return None
    return min(candidates), currency


async def enrich_min_session_price(session: AsyncSession, trainers: list[dict[str, Any]]) -> None:
    """Дописывает ``min_session_price_cents`` / ``min_session_price_currency`` (или ``None``)."""
    for trainer in trainers:
        found = trainer_min_session_price(trainer)
        trainer["min_session_price_cents"] = found[0] if found else None
        trainer["min_session_price_currency"] = found[1] if found else None
