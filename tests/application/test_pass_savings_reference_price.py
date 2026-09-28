"""Экономия по абонементу должна быть правдой.

Два дефекта, найденные по скриншоту с прода (25.09.2026):

1. Детский абонемент сравнивался со взрослой разовой ценой. Тарифы живут в
   ``trainer_service_price_variants``, абонемент несёт свои ``tier_kinds``, но
   расчёт брал плоскую ``trainer_services.price_cents`` — одну на всех.
2. Итоговая выгода считалась как округлённая цена за занятие × количество.
   375 BYN за 8 занятий против 55 давали «65.04 BYN с абонемента» вместо 65.00 —
   копейки из ниоткуда в обещании про деньги.
"""
import pytest

from src.application.pass_product_use_cases import (
    enrich_pass_items_with_catalog_reference_prices as enrich,
)

SERVICE = 1
ADULT_SINGLE = 5500
CHILD_SINGLE = 5000

_BASE = {SERVICE: ADULT_SINGLE}
_TIERS = {(SERVICE, "adult"): ADULT_SINGLE, (SERVICE, "child"): CHILD_SINGLE}


def _pass(tier: str | None, sessions: int, price: int) -> dict:
    return {
        "service_ids": [SERVICE],
        "tier_kinds": [tier] if tier else [],
        "sessions_total": sessions,
        "price_cents": price,
    }


def _enriched(item: dict, *, with_tiers: bool = True) -> dict:
    items = [item]
    enrich(
        items,
        price_by_service=_BASE,
        default_single_reference=ADULT_SINGLE,
        price_by_service_tier=_TIERS if with_tiers else None,
    )
    return items[0]


class TestTierAwareReference:
    def test_child_pass_is_compared_with_the_child_single_price(self):
        """Ровно баг со скриншота: детский 4×45 обещал экономию против взрослых 55."""
        p = _enriched(_pass("child", 4, 18000))
        assert p["price_per_session_cents"] == CHILD_SINGLE
        assert p["savings_per_session_cents"] == 500
        assert p["savings_total_cents"] == 2000

    def test_adult_pass_keeps_the_adult_reference(self):
        p = _enriched(_pass("adult", 4, 20000))
        assert p["price_per_session_cents"] == ADULT_SINGLE
        assert p["savings_total_cents"] == 2000

    def test_without_a_tier_price_it_falls_back_to_the_service_price(self):
        """Тренер не завёл детский тариф — сравниваем с базовой, а не выдумываем."""
        p = _enriched(_pass("child", 4, 18000), with_tiers=False)
        assert p["price_per_session_cents"] == ADULT_SINGLE

    def test_multi_tier_pass_uses_the_service_price(self):
        """«Ребёнок + взрослый» не имеет одной своей разовой цены — берём базовую."""
        item = _pass(None, 8, 51000)
        item["tier_kinds"] = ["child", "adult"]
        p = _enriched(item)
        assert p["price_per_session_cents"] == ADULT_SINGLE

    def test_untiered_pass_is_unaffected(self):
        p = _enriched(_pass(None, 4, 20000))
        assert p["price_per_session_cents"] == ADULT_SINGLE


class TestSavingsArithmetic:
    def test_total_is_not_the_rounded_rate_times_count(self):
        """375 за 8 против 55: ровно 65.00, а не 65.04, как показывал прод."""
        p = _enriched(_pass("adult", 8, 37500))
        assert p["savings_per_session_cents"] == 813  # 46.87 на витрине — округление вниз
        assert p["savings_total_cents"] == 6500
        assert p["savings_total_cents"] != p["savings_per_session_cents"] * 8

    def test_total_always_equals_real_money(self):
        """Итог = сколько занятий стоили бы по одному минус цена абонемента."""
        for sessions, price in ((4, 18000), (8, 34000), (8, 37500), (12, 50000)):
            p = _enriched(_pass("adult", sessions, price))
            assert p["savings_total_cents"] == ADULT_SINGLE * sessions - price

    def test_a_pass_dearer_than_singles_shows_no_savings(self):
        """Отрицательную выгоду не показываем — но и не выдаём за положительную."""
        p = _enriched(_pass("adult", 4, 30000))
        assert p["savings_per_session_cents"] == 0
        assert p["savings_total_cents"] == 0

    @pytest.mark.parametrize("missing", [{"sessions_total": 0}, {"price_cents": None}])
    def test_incomplete_pass_reports_no_savings_instead_of_guessing(self, missing):
        item = _pass("adult", 4, 20000)
        item.update(missing)
        p = _enriched(item)
        assert p["savings_total_cents"] is None
