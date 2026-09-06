"""TASK-053: Ice tab Mini App — tab label, list module, catalog lens, deep links."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ice_tab_model_node_unit() -> None:
    """AC-001/003/004 + epic-corrected skate filter + EDGE-001/002 + TASK-076 coach lens."""
    proc = subprocess.run(
        [
            "node",
            "--test",
            "tests/js/ice-tab-model.test.js",
            "tests/js/ice-tab-tokens.test.js",
            "tests/js/ice-map-model.test.js",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.asyncio
async def test_ice_tab_page_and_assets_served(app_use_test_db) -> None:
    """AC-001: second tab is Лёд and opens the arena list module, not catalog-main.js."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        html = await client.get("/webapp/ice")
        js = await client.get("/webapp/ice-tab.js")
        css = await client.get("/webapp/ice-tab.css")
        model = await client.get("/webapp/ice-tab-model.js")
        map_js = await client.get("/webapp/ice-map.js")
        map_model = await client.get("/webapp/ice-map-model.js")
        alias = await client.get("/webapp/ice.html")
    assert html.status_code == 200, html.text
    body = html.text
    assert "ice-tab.js" in body
    assert "ice-map.js" in body
    assert "catalog-main.js" not in body
    assert "Покататься" in body
    assert "Тренеры" in body
    assert "Группы" in body
    assert 'data-intent="group"' in body
    assert "ice-map-loading" in body
    assert "Каток, тренер или город" in body
    assert js.status_code == 200
    assert css.status_code == 200
    assert model.status_code == 200
    assert map_js.status_code == 200
    assert map_model.status_code == 200
    assert alias.status_code == 200
    page_js = js.text + model.text + body
    assert "/api/public/ice/arenas" in page_js
    assert "/api/public/trainers" in page_js
    assert "intent=skate" in page_js or "intent: 'skate'" in page_js or 'intent: "skate"' in page_js
    assert "arena?ref=" in page_js
    assert "computeTier" not in page_js
    assert "data_tier" not in page_js
    assert "formatLiveLine" in model.text
    assert "formatEmptyList" in model.text
    assert "#c2761a" not in css.text.lower()
    assert ".ice-sec[hidden]" in css.text


def test_shell_second_tab_is_ice() -> None:
    """AC-001: tab bar label Лёд opens ice; four tabs unchanged otherwise."""
    shell = (REPO_ROOT / "static/webapp/mini-app-client-shell.js").read_text(encoding="utf-8")
    assert "label: 'Лёд'" in shell
    assert "path: 'ice'" in shell
    assert "label: 'Главная'" in shell
    assert "label: 'Записи'" in shell
    assert "label: 'Ещё'" in shell
    assert "label: 'Тренеры', path: 'catalog?tab=catalog'" not in shell
    ice_tab = (REPO_ROOT / "static/webapp/ice-tab.js").read_text(encoding="utf-8")
    ice_model = (REPO_ROOT / "static/webapp/ice-tab-model.js").read_text(encoding="utf-8")
    assert "class=\"ice-acard\" href=\"" in ice_tab
    assert "params.get('view') === 'map'" in ice_tab
    assert "action.type === 'catalog'" not in ice_tab
    assert "type: 'list', intent: INTENTS.coach" in ice_model or 'type: "list", intent: INTENTS.coach' in ice_model
    assert "catalog?tab=catalog" in ice_model
    assert "trainer_id=" in ice_model
    assert "buildMapListUrl" in ice_tab
    assert "buildListUrl({ near: near, intent: 'coach', limit: 1 })" in ice_tab


def test_old_catalog_deep_links_still_wired() -> None:
    """EDGE-003 / AC-005: catalog.html still hosts the trainer funnel."""
    catalog = (REPO_ROOT / "static/webapp/catalog.html").read_text(encoding="utf-8")
    assert "catalog-main.js" in catalog
    assert 'id="screenSummary"' in catalog
    assert 'id="screenTrainers"' in catalog
    assert 'id="screenCity"' in catalog
    catalog_js = (REPO_ROOT / "static/webapp/catalog-main.js").read_text(encoding="utf-8")
    assert "forceCatalogBrowse" in catalog_js
    assert "tab') === 'catalog'" in catalog_js or 'tab") === "catalog"' in catalog_js or "get('tab') === 'catalog'" in catalog_js
