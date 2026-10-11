"""Term stored on a trainer pass product."""

from src.application.pass_product_use_cases import PASS_VALIDITY_DAYS_MAX, _clean_validity_days
import pytest


def test_open_ended_term_is_empty() -> None:
    assert _clean_validity_days(None) is None


def test_whole_day_term_is_kept() -> None:
    assert _clean_validity_days(90) == 90
    assert _clean_validity_days(PASS_VALIDITY_DAYS_MAX) == PASS_VALIDITY_DAYS_MAX


@pytest.mark.parametrize("bad", [0, -1, PASS_VALIDITY_DAYS_MAX + 1])
def test_term_outside_one_day_to_ten_years_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="без срока"):
        _clean_validity_days(bad)
