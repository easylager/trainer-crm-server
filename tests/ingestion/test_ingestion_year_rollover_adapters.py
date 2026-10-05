"""Year-boundary date inference for the six adapters called out in TASK-186."""
from __future__ import annotations

from datetime import date
import pytest

from src.ingestion.adapters import ChizhovkaHtmlParser, DiamondHtmlParser
from src.ingestion.adapters_regional_batch_c import (
    GorkiLdsParser,
    OstrovetsLdsParser,
    _ostrovets_header_date,
)
from src.ingestion.adapters_regional_batch_d import (
    SoligorskSzkParser,
    _bobruisk_schedule_slots,
)
from src.ingestion.types import ParserJob

_REF_DEC_29 = date(2026, 12, 29)
_REF_JAN_2 = date(2027, 1, 2)


def _minimal_job(parser_key: str, config: dict | None = None) -> ParserJob:
    return ParserJob(
        id=1,
        arena_id=1,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=None,
        last_run_at=None,
        config=config or {},
    )


def _patch_reference(monkeypatch: pytest.MonkeyPatch, ref: date) -> None:
    stub = lambda config=None: ref
    for module in (
        "src.ingestion.dates",
        "src.ingestion.adapters",
        "src.ingestion.adapters_regional_batch_c",
        "src.ingestion.adapters_regional_batch_d",
    ):
        monkeypatch.setattr(f"{module}.parser_reference_date", stub)


_CHIZ_NY_TABLE = """
<table><tr>
<td>29 декабря</td><td>30 декабря</td><td>31 декабря</td>
<td>1 января</td><td>2 января</td><td>3 января</td><td>4 января</td>
</tr><tr>
<td>10:00 МА</td><td>10:00 МА</td><td>10:00 МА</td>
<td>10:00 МА</td><td>10:00 МА</td><td>10:00 МА</td><td>10:00 МА</td>
</tr></table>
"""

_DIAMOND_NY_HTML = """
<div id='irqsbii62_0'></div>
<div class='blocklist__item_title' id='x1'>
<div class='text-block-wrap-div'>Пн, 29 декабря</div>
<div class='list__item'><span>18:00-19:00 МК</span></div>
<div class='blocklist__item_text'></div>
<div class='blocklist__item_title' id='x2'>
<div class='text-block-wrap-div'>Вт, 1 января</div>
<div class='list__item'><span>19:00-20:00 МК</span></div>
<div class='blocklist__item_text'></div>
"""

_GORKI_NY_HTML = """
<p>МАССОВОЕ КАТАНИЕ</p>
<p>29 декабря: 18.00</p>
<p>1 января: 19.00</p>
<p>4 января: 20.00</p>
"""

_OSTROVETS_NY_TABLE = """
<table><tr>
<td>29 декабря</td><td>30 декабря</td><td>31 декабря</td>
<td>1 января</td><td>2 января</td><td>3 января</td><td>4 января</td>
</tr><tr>
<td>15:45</td><td>15:45</td><td>15:45</td>
<td>15:45</td><td>15:45</td><td>15:45</td><td>15:45</td>
</tr></table>
"""

_BOBRUISK_NY_HTML = """
<p>Пятница 29 декабря</p><p>Массовое катание 18.00-18.45</p>
<p>Суббота 1 января</p><p>Массовое катание 19.00-19.45</p>
"""

_SOLIGORSK_NY_HTML = """
<h3>РАСПИСАНИЕ МАССОВЫХ КАТАНИЙ</h3>
<h3>29 декабря - 18.00-19.00</h3>
<h3>1 января - 19.00-20.00</h3>
<h3>4 января - 20.00-21.00</h3>
<p>Продолжительность</p>
"""


@pytest.mark.asyncio
async def test_chizhovka_year_rollover_december_to_january(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reference(monkeypatch, _REF_DEC_29)

    async def load(job, *, filename: str, url_keys=()):
        if filename == "schedule.html":
            return _CHIZ_NY_TABLE
        return "<html>ВЗРОСЛЫЙ БИЛЕТ 10 руб</html>"

    monkeypatch.setattr("src.ingestion.adapters.load_source_text", load)
    job = _minimal_job("chizhovka_html_v1", {"keep_rink_labels": ["МА"]})
    extraction = await ChizhovkaHtmlParser().extract(job)
    dates = sorted({s.local_date for s in extraction.slots})
    assert dates == [
        "2026-12-29",
        "2026-12-30",
        "2026-12-31",
        "2027-01-01",
        "2027-01-02",
        "2027-01-03",
        "2027-01-04",
    ]


@pytest.mark.asyncio
async def test_chizhovka_year_rollover_january_maps_december_to_prior_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reference(monkeypatch, _REF_JAN_2)

    async def load(job, *, filename: str, url_keys=()):
        if filename == "schedule.html":
            return _CHIZ_NY_TABLE
        return "<html>ВЗРОСЛЫЙ БИЛЕТ 10 руб</html>"

    monkeypatch.setattr("src.ingestion.adapters.load_source_text", load)
    job = _minimal_job("chizhovka_html_v1", {"keep_rink_labels": ["МА"]})
    extraction = await ChizhovkaHtmlParser().extract(job)
    assert "2026-12-29" in {s.local_date for s in extraction.slots}
    assert "2027-12-29" not in {s.local_date for s in extraction.slots}


@pytest.mark.asyncio
async def test_diamond_year_rollover_december_to_january(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reference(monkeypatch, _REF_DEC_29)

    async def load(job, *, filename: str, url_keys=()):
        return _DIAMOND_NY_HTML

    monkeypatch.setattr("src.ingestion.adapters.load_source_text", load)
    job = _minimal_job("diamond_html_v1")
    extraction = await DiamondHtmlParser().extract(job)
    by_date = {s.local_date for s in extraction.slots}
    assert "2026-12-29" in by_date
    assert "2027-01-01" in by_date


@pytest.mark.asyncio
async def test_diamond_year_rollover_january_maps_december_to_prior_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reference(monkeypatch, _REF_JAN_2)

    async def load(job, *, filename: str, url_keys=()):
        return _DIAMOND_NY_HTML

    monkeypatch.setattr("src.ingestion.adapters.load_source_text", load)
    extraction = await DiamondHtmlParser().extract(_minimal_job("diamond_html_v1"))
    assert "2026-12-29" in {s.local_date for s in extraction.slots}
    assert "2027-12-29" not in {s.local_date for s in extraction.slots}


@pytest.mark.asyncio
async def test_gorki_year_rollover_december_to_january(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reference(monkeypatch, _REF_DEC_29)

    async def load(job, *, filename: str, url_keys=()):
        if "home" in filename:
            return _GORKI_NY_HTML
        return "<html></html>"

    monkeypatch.setattr("src.ingestion.adapters_regional_batch_c.load_source_text", load)
    job = _minimal_job("gorki_lds_v1", {"mk_heading": "МАССОВОЕ КАТАНИЕ"})
    extraction = await GorkiLdsParser().extract(job)
    assert {s.local_date for s in extraction.slots} == {"2026-12-29", "2027-01-01", "2027-01-04"}


@pytest.mark.asyncio
async def test_gorki_year_rollover_january_maps_december_to_prior_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reference(monkeypatch, _REF_JAN_2)

    async def load(job, *, filename: str, url_keys=()):
        return _GORKI_NY_HTML

    monkeypatch.setattr("src.ingestion.adapters_regional_batch_c.load_source_text", load)
    job = _minimal_job("gorki_lds_v1", {"mk_heading": "МАССОВОЕ КАТАНИЕ"})
    extraction = await GorkiLdsParser().extract(job)
    assert "2026-12-29" in {s.local_date for s in extraction.slots}
    assert "2027-12-29" not in {s.local_date for s in extraction.slots}


def test_ostrovets_header_year_rollover() -> None:
    assert _ostrovets_header_date("29 декабря", _REF_DEC_29) == date(2026, 12, 29)
    assert _ostrovets_header_date("1 января", _REF_DEC_29) == date(2027, 1, 1)
    assert _ostrovets_header_date("29 декабря", _REF_JAN_2) == date(2026, 12, 29)


@pytest.mark.asyncio
async def test_ostrovets_year_rollover_december_to_january(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reference(monkeypatch, _REF_DEC_29)

    async def load(job, *, filename: str, url_keys=()):
        if "katanie" in filename:
            return _OSTROVETS_NY_TABLE
        return "<html></html>"

    monkeypatch.setattr("src.ingestion.adapters_regional_batch_c.load_source_text", load)
    job = _minimal_job("ostrovets_lds_v1")
    extraction = await OstrovetsLdsParser().extract(job)
    dates = sorted({s.local_date for s in extraction.slots})
    assert "2027-01-01" in dates
    assert "2026-12-29" in dates


def test_bobruisk_schedule_year_rollover() -> None:
    slots = _bobruisk_schedule_slots(_BOBRUISK_NY_HTML, reference=_REF_DEC_29)
    dates = sorted({d.isoformat() for d, _, _ in slots})
    assert dates == ["2026-12-29", "2027-01-01"]

    slots_jan = _bobruisk_schedule_slots(_BOBRUISK_NY_HTML, reference=_REF_JAN_2)
    assert "2026-12-29" in {d.isoformat() for d, _, _ in slots_jan}
    assert "2027-12-29" not in {d.isoformat() for d, _, _ in slots_jan}


@pytest.mark.asyncio
async def test_soligorsk_year_rollover_december_to_january(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reference(monkeypatch, _REF_DEC_29)

    async def load(job, *, filename: str, url_keys=()):
        return _SOLIGORSK_NY_HTML

    monkeypatch.setattr("src.ingestion.adapters_regional_batch_d.load_source_text", load)
    extraction = await SoligorskSzkParser().extract(_minimal_job("soligorsk_szk_v1"))
    assert {s.local_date for s in extraction.slots} == {"2026-12-29", "2027-01-01", "2027-01-04"}


@pytest.mark.asyncio
async def test_soligorsk_year_rollover_january_maps_december_to_prior_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reference(monkeypatch, _REF_JAN_2)

    async def load(job, *, filename: str, url_keys=()):
        return _SOLIGORSK_NY_HTML

    monkeypatch.setattr("src.ingestion.adapters_regional_batch_d.load_source_text", load)
    extraction = await SoligorskSzkParser().extract(_minimal_job("soligorsk_szk_v1"))
    assert "2026-12-29" in {s.local_date for s in extraction.slots}
    assert "2027-12-29" not in {s.local_date for s in extraction.slots}


@pytest.mark.asyncio
async def test_gorki_next_year_token_on_page_does_not_shift_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression (batch review): «…на январь 2027» on 29.12.2026 must not push dates to 2027-12/2028-01."""
    _patch_reference(monkeypatch, _REF_DEC_29)

    async def load(job, *, filename: str, url_keys=()):
        if "home" in filename:
            return "<p>Расписание на новогодние праздники 2027</p>" + _GORKI_NY_HTML
        return "<html></html>"

    monkeypatch.setattr("src.ingestion.adapters_regional_batch_c.load_source_text", load)
    job = _minimal_job("gorki_lds_v1", {"mk_heading": "МАССОВОЕ КАТАНИЕ"})
    extraction = await GorkiLdsParser().extract(job)
    assert {s.local_date for s in extraction.slots} == {"2026-12-29", "2027-01-01", "2027-01-04"}


def test_bobruisk_legacy_header_outside_window_is_skipped_not_none() -> None:
    """Regression (batch review): a legacy header date the window rejects must not yield date=None."""
    html = (
        '<div class="post__raspisanie">'
        "<p>1 сентября</p><p>Массовое катание 18.00-19.00</p><p></p>"
        "<p>2 октября</p><p>Массовое катание 18.00-19.00</p><p></p>"
        "<p>Массовое катание 19.00-20.00</p>"
        "</div>"
    )
    # 1 Sep is 34 days before 5 Oct — outside the −30 / +330 inference window.
    slots = _bobruisk_schedule_slots(html, reference=date(2026, 10, 5))
    assert all(isinstance(d, date) for d, _, _ in slots)
    assert [(d.isoformat(), s) for d, s, _ in slots] == [("2026-10-02", "18:00"), ("2026-10-03", "19:00")]
