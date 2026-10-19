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


def test_live_seats_parse_and_plural() -> None:
    from src.application.session_load import live_seats, live_seats_plan_line

    assert live_seats("70 мест") == (70, "70 мест")
    assert live_seats("23 мест") == (23, "23 места")
    assert live_seats("21 мест") == (21, "21 место")
    assert live_seats("нет мест") == (0, "нет мест")
    assert live_seats("30–35 человек") is None
    assert live_seats(None) is None
    assert live_seats_plan_line("23 мест") == "Осталось 23 места — лучше взять сейчас"
    assert live_seats_plan_line("110 мест") == "Осталось 110 мест"
    assert live_seats_plan_line("нет мест") == "Мест не осталось"


def test_ticket_shows_live_seats_instead_of_meter() -> None:
    kw = dict(vt_session_id=None, base_path="/p/minsk/x", invite=False, focused=False, common_price="")
    html = _b_ticket(_slot(typical_load_level="busy", capacity_note="23 мест"), **kw)
    assert '<span class="b-seats b-seats--low">23 места</span>' in html
    assert "b-load" not in html
    plenty = _b_ticket(_slot(typical_load_level="busy", capacity_note="110 мест"), **kw)
    assert '<span class="b-seats">110 мест</span>' in plenty
    ohm_note = _b_ticket(_slot(typical_load_level="busy", capacity_note="30–35 человек"), **kw)
    assert "b-load" in ohm_note and "b-seats" not in ohm_note
