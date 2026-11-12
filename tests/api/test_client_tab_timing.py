"""TASK-389: POST /client/tab-timing пишет строку лога без персональных данных."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.miniapp_auth import MiniAppPrincipal, get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform

URL = "/api/webapp/client/tab-timing"
_USER_ID = 7100000003

_spec = importlib.util.spec_from_file_location(
    "tab_timing_report", Path(__file__).resolve().parents[2] / "scripts" / "tab_timing_report.py"
)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


@pytest.fixture
def auth():
    principal = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=_USER_ID)
    app.dependency_overrides[get_client_miniapp_principal] = lambda: principal
    yield
    app.dependency_overrides.pop(get_client_miniapp_principal, None)


async def _post(body: dict):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(URL, json=body)


def _body(**over) -> dict:
    base = {
        "kind": "tab",
        "from": "home",
        "to": "kk",
        "ms": 412,
        "page_ms": 381,
        "nav": "navigate",
        "platform": "android",
        "season_ui": True,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_logs_one_line_without_personal_data(auth, caplog) -> None:
    with caplog.at_level(logging.INFO):
        resp = await _post(_body())
    assert resp.status_code == 204
    lines = [r.getMessage() for r in caplog.records if "client tab-timing" in r.getMessage()]
    assert lines == [
        "client tab-timing kind=tab from=home to=kk ms=412 page_ms=381 platform=android season_ui=1 nav=navigate"
    ]
    assert str(_USER_ID) not in lines[0]
    parsed = report.parse_line(lines[0])
    assert parsed and parsed["to"] == "kk" and parsed["ms"] == "412"


@pytest.mark.asyncio
async def test_cold_start_has_no_from(auth, caplog) -> None:
    with caplog.at_level(logging.INFO):
        resp = await _post(_body(kind="cold", **{"from": None}, to="home", ms=2240, page_ms=2240))
    assert resp.status_code == 204
    assert any("kind=cold from=- to=home ms=2240" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"to": "admin"},
        {"ms": -1},
        {"ms": 999_999},
        {"platform": "ev il"},
        {"kind": "other"},
        {"user_id": 5},
    ],
)
async def test_rejects_garbage(auth, over) -> None:
    resp = await _post(_body(**over))
    assert resp.status_code == 422


def test_report_percentiles() -> None:
    rows = [{"kind": "tab", "to": "kk", "platform": "ios", "ms": str(v), "page_ms": str(v)} for v in range(100, 1100, 100)]
    [(key, n, med, p90, _page)] = report.summarize(rows, ("kind", "to", "platform"))
    assert key == ("tab", "kk", "ios")
    assert (n, med, p90) == (10, 550, 900)
