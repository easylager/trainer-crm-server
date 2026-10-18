"""TASK-290: черточки загрузки на квадрате сеанса и слово в «Выбранном сеансе»."""

from src.application.place_page import _b_ticket
from src.application.session_load import LOAD_PLAN_LINES, load_meter_html


def _slot(**extra):
    return {"id": 7, "starts_at_local": "19:15", "ends_at_local": "20:00", **extra}


def test_meter_markup_per_level() -> None:
    for level, word in LOAD_PLAN_LINES.items():
        html = load_meter_html(level)
        assert f'data-level="{level}"' in html
        assert f'aria-label="{word}"' in html
        assert html.count("<i></i>") == 3


def test_meter_empty_for_unknown_level() -> None:
    assert load_meter_html(None) == ""
    assert load_meter_html("") == ""
    assert load_meter_html("full") == ""


def test_ticket_carries_meter_only_with_level() -> None:
    kw = dict(vt_session_id=None, base_path="/p/minsk/x", invite=False, focused=False, common_price="")
    busy = _b_ticket(_slot(typical_load_level="busy"), **kw)
    assert 'class="b-load" data-level="busy"' in busy
    assert busy.index("b-ticket__time") < busy.index("b-load")
    assert "b-load" not in _b_ticket(_slot(), **kw)
