"""«от N за занятие» у тренера — самое дешёвое занятие, которое можно купить.

Решение владельца 2026-11-07 (возврат правила TASK-265 поверх TASK-352). Кандидаты:

* услуга — её тарифы (``trainer_service_price_variants``: детский, взрослый, «на двоих» — за
  занятие целиком); тарифов нет — ``price_cents`` услуги (TASK-352);
* групповое занятие услуги (``group_price_cents``);
* активный абонемент в пересчёте на занятие (``price_cents // sessions_total``, вниз — как
  ``pass_product_use_cases.enrich_pass_items_with_catalog_reference_prices``), если он покрывает
  хоть одну из услуг: нет строк в ``trainer_pass_product_services`` — на все услуги тренера,
  иначе только перечисленные (как ``SQL_PASS_PRODUCT_COVERS_BOOKING``). Дробная цена — как есть
  («от 41,87 BYN»).

Одна функция для всех поверхностей: строки сайта, ``/t/``, API катка, витрина Mini App и «от»
вкладки-направления (``site_trainer_catalog.direction_min_price`` — те же услуги направления и
абонементы, покрывающие их).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Абонемент тренера для «от»: ``{"per_session_cents": int, "service_ids": tuple[int, ...] | None}``;
#: ``service_ids=None`` — на все услуги.
PassOffer = dict[str, Any]


def _positive(value: Any) -> int | None:
    try:
        cents = int(value)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


def service_price_from(svc: Mapping[str, Any]) -> int | None:
    """Индивидуальная цена услуги «от»: минимум тарифов; тарифов нет — ``price_cents`` (TASK-352)."""
    tier_prices = [c for c in (_positive(t.get("price_cents")) for t in svc.get("price_tiers") or []) if c is not None]
    if tier_prices:
        return min(tier_prices)
    return _positive(svc.get("price_cents"))


def pass_covers(offer: Mapping[str, Any], service_ids: Iterable[int]) -> bool:
    """Покрывает ли абонемент хоть одну из услуг (без строк услуг — любую)."""
    ids = {int(s) for s in service_ids}
    if not ids:
        return False
    scope = offer.get("service_ids")
    if not scope:
        return True
    return any(int(s) in ids for s in scope)


#: Из чего «от»: обычное занятие, групповое или абонемент в пересчёте на занятие.
BASIS_SINGLE = "single"
BASIS_GROUP = "group"
BASIS_PASS = "pass"
#: Пометка к цене на карточке; у обычного занятия её нет.
BASIS_LABEL = {BASIS_SINGLE: "", BASIS_GROUP: "в группе", BASIS_PASS: "по абонементу"}
#: Хвост «от 25 BYN …» в сниппетах и подписи: тот же смысл, что у карточки, но со словом и для обычного занятия.
BASIS_PHRASE = {BASIS_SINGLE: "за занятие", BASIS_GROUP: "в группе", BASIS_PASS: "по абонементу"}
_BASIS_RANK = {BASIS_SINGLE: 0, BASIS_GROUP: 1, BASIS_PASS: 2}


def basis_rank(basis: str) -> int:
    """При равной цене обычное занятие честнее группового, а то — абонемента."""
    return _BASIS_RANK.get(basis, len(_BASIS_RANK))


def trainer_min_session_offer(trainer: Mapping[str, Any]) -> tuple[int, str, str] | None:
    """(копейки, валюта, основание) самого дешёвого занятия среди ``services`` и ``passes`` или ``None``.

    ``trainer["passes"]`` — ``PassOffer`` тренера (``load_pass_offers``); учитываются только те,
    что покрывают одну из переданных услуг. Основание — ``BASIS_*``: при равной цене обычное занятие
    побеждает групповое, а групповое — абонемент.
    """
    services = list(trainer.get("services") or [])
    currency = next((str(s["currency_code"]) for s in services if s.get("currency_code")), "BYN")
    singles = [c for c in (service_price_from(s) for s in services) if c is not None]
    groups = [c for c in (_positive(s.get("group_price_cents")) for s in services) if c is not None]
    passes: list[int] = []
    service_ids = [int(s["service_id"]) for s in services if s.get("service_id") is not None]
    for offer in trainer.get("passes") or []:
        cents = _positive(offer.get("per_session_cents"))
        if cents is not None and pass_covers(offer, service_ids):
            passes.append(cents)
    everything = singles + groups + passes
    if not everything:
        return None
    cents = min(everything)
    if singles and min(singles) <= cents:
        return cents, currency, BASIS_SINGLE
    if groups and min(groups) <= cents:
        return cents, currency, BASIS_GROUP
    return cents, currency, BASIS_PASS


def trainer_min_session_price(trainer: Mapping[str, Any]) -> tuple[int, str] | None:
    """(копейки, валюта) самого дешёвого занятия среди ``services`` и ``passes`` или ``None``."""
    found = trainer_min_session_offer(trainer)
    return (found[0], found[1]) if found else None


async def load_pass_offers(session: AsyncSession, trainer_ids: Iterable[int]) -> dict[int, list[PassOffer]]:
    """trainer_id → активные абонементы: цена занятия (копейки, вниз) и услуги (``None`` — все)."""
    ids = sorted({int(t) for t in trainer_ids})
    if not ids:
        return {}
    rows = await session.execute(
        text("""
            SELECT p.trainer_id, p.price_cents / p.sessions_total AS per_session,
                   (SELECT ARRAY_AGG(t.service_id ORDER BY t.service_id)
                      FROM trainer_pass_product_services t WHERE t.pass_product_id = p.id) AS service_ids
            FROM trainer_pass_products p
            WHERE p.trainer_id = ANY(:ids) AND p.is_active = true AND p.sessions_total > 0 AND p.price_cents > 0
            ORDER BY p.trainer_id, p.id
            """),
        {"ids": ids},
    )
    out: dict[int, list[PassOffer]] = {}
    for tid, per_session, service_ids in rows.fetchall():
        out.setdefault(int(tid), []).append(
            {
                "per_session_cents": int(per_session),
                "service_ids": tuple(int(s) for s in service_ids) if service_ids else None,
            }
        )
    return out


async def enrich_min_session_price(session: AsyncSession, trainers: list[dict[str, Any]]) -> dict[int, list[PassOffer]]:
    """Дописывает ``min_session_price_cents`` / ``_currency`` / ``_basis`` (или ``None``).

    Возвращает загруженные абонементы (trainer_id → ``PassOffer``) — для «от» по направлениям.
    """
    offers = await load_pass_offers(session, (int(t["id"]) for t in trainers))
    for trainer in trainers:
        found = trainer_min_session_offer(
            {"services": trainer.get("services") or [], "passes": offers.get(int(trainer["id"]), [])}
        )
        trainer["min_session_price_cents"] = found[0] if found else None
        trainer["min_session_price_currency"] = found[1] if found else None
        trainer["min_session_price_basis"] = found[2] if found else None
    return offers
