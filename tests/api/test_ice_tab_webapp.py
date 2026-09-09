"""TASK-053: Ice tab Mini App — tab label, list module, catalog lens, deep links."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _code_only(text: str) -> str:
    """Убирает комментарии: проверять надо объявления, а не рассказ о том, что убрано."""
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.MULTILINE)


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
    assert 'data-intent="group"' not in body
    assert "ice-masthead" in body
    assert "iceServiceChips" in body
    # TASK-103: карта вернулась, но сегмент «Список / Карта» в шапку — нет.
    # Он стоил ~46px над сгибом и был причиной выключения карты в TASK-084 (G-P3).
    # Проверяем именно отсутствие сегмента, а не отсутствие переключателя вообще.
    assert "iceViewSeg" not in body
    assert "iceViewSwitch" in body
    assert "iceMapSec" in body
    assert "Каток, тренер или город" in body
    assert js.status_code == 200
    # Флаг MAP_ENABLED снят намеренно: он гасил случай «экран открылся картой без
    # выхода», а TASK-103 делает этот случай невозможным — список всегда стартовый вид.
    assert "MAP_ENABLED" not in _code_only(js.text)

    assert css.status_code == 200
    assert model.status_code == 200
    assert map_js.status_code == 200
    assert map_model.status_code == 200
    assert alias.status_code == 200
    page_js = js.text + model.text + body
    assert "/api/public/ice/arenas" in page_js
    assert "/api/public/ice/cities" in page_js
    assert "/api/public/trainers" in page_js
    assert "/api/public/services" in page_js
    assert "intent=skate" in page_js or "intent: 'skate'" in page_js or 'intent: "skate"' in page_js
    assert "arena?ref=" in page_js
    assert "computeTier" not in page_js
    assert "data_tier" not in page_js
    assert "formatLiveLine" in model.text
    assert "formatEmptyList" in model.text
    assert "#c2761a" not in css.text.lower()
    assert ".ice-ypin__label" in css.text
    assert "color: inherit" not in css.text.split(".ice-ypin__label")[1].split("}")[0]
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
    # Здесь раньше проверялся deep-link ?view=map. TASK-103 его убрала осознанно:
    # AC-001 требует, чтобы список был стартовым видом всегда, а «открыть экран сразу
    # картой» — это ровно тот случай, ради которого в TASK-084 стоял флаг MAP_ENABLED.
    # Вход в карту остался, но только осознанным тапом по #iceViewSwitch.
    assert "iceViewSwitch" in ice_tab
    assert "buildServicesUrl" in ice_model
    assert "serviceId" in ice_tab
    assert "action.type === 'catalog'" not in ice_tab
    assert "type: 'list', intent: INTENTS.coach" in ice_model or 'type: "list", intent: INTENTS.coach' in ice_model
    assert "catalog?tab=catalog" in ice_model
    assert "trainer_id=" in ice_model
    assert "intentFromSearch" in ice_model
    assert "ice?intent=coach" in ice_model
    assert "buildMapListUrl" in ice_tab
    assert "buildListUrl({ near: near, intent: 'coach', limit: 1 })" in ice_tab


def test_client_browse_ctas_open_ice_coaches() -> None:
    """TASK-084: Mini App 'find a trainer' CTAs must not open the old catalog funnel."""
    rels = (
        "static/webapp/client-home-main.js",
        "static/webapp/client-saved-trainers-main.js",
        "static/webapp/client-stats-main.js",
        "static/webapp/client-requests-main.js",
        "static/webapp/client-bookings.html",
        "static/webapp/booking-client.js",
    )
    for rel in rels:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "catalog?tab=catalog" not in text, rel
        assert "ice?intent=coach" in text, rel


def test_old_catalog_deep_links_still_wired() -> None:
    """EDGE-003 / AC-005: catalog.html still hosts the trainer card; browse is no longer the funnel."""
    catalog = (REPO_ROOT / "static/webapp/catalog.html").read_text(encoding="utf-8")
    assert "catalog-main.js" in catalog
    assert 'id="screenSummary"' in catalog
    assert 'id="screenTrainers"' in catalog
    assert 'id="screenCity"' in catalog
    catalog_js = (REPO_ROOT / "static/webapp/catalog-main.js").read_text(encoding="utf-8")
    assert "forceCatalogBrowse" in catalog_js
    assert "tab') === 'catalog'" in catalog_js or 'tab") === "catalog"' in catalog_js or "get('tab') === 'catalog'" in catalog_js


@pytest.mark.asyncio
async def test_catalog_browse_redirects_to_ice_coaches(app_use_test_db) -> None:
    """TASK-084: /webapp/catalog without trainer_id is Ice coaches, not the old funnel."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bare = await client.get("/webapp/catalog")
        tab = await client.get("/webapp/catalog?tab=catalog")
        with_city = await client.get("/webapp/catalog?tab=catalog&city_id=2")
        card = await client.get("/webapp/catalog?trainer_id=77")
        collective = await client.get("/webapp/catalog?collective=ice-yoga&tab=catalog")
    assert bare.status_code == 307
    assert bare.headers.get("location") == "/webapp/ice?intent=coach"
    assert tab.status_code == 307
    assert tab.headers.get("location") == "/webapp/ice?intent=coach"
    assert with_city.status_code == 307
    assert with_city.headers.get("location") == "/webapp/ice?intent=coach&city_id=2"
    assert card.status_code == 200
    assert "catalog-main.js" in card.text
    assert collective.status_code == 200
    assert "catalog-main.js" in collective.text


# ─── TASK-103: карта вернулась — список первым, карта в один тап ─────────────


@pytest.mark.asyncio
async def test_map_switch_costs_no_height_above_the_fold() -> None:
    """AC-003: переключатель не отнимает высоту у первого экрана.

    Именно это, а не карта сама по себе, было причиной выключения в TASK-084:
    сегмент стоял в шапке между чипами и списком. Тест держит носитель — плавающую
    пилюлю (position: fixed), — потому что вернуть сегмент проще всего «заодно».
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/webapp/ice")).text
        css = _code_only((await client.get("/webapp/ice-tab.css")).text)

    assert "iceViewSwitch" in body
    assert "iceViewSeg" not in body, "сегмент в шапке вернул нарушение G-P3"
    switch_rule = css.split(".ice-viewswitch {")[1].split("}")[0]
    assert "position: fixed" in switch_rule
    # Дно считается от измеренной высоты панели (TASK-093), а не от константы 62px.
    assert "--client-shell-tab-inset" in switch_rule


@pytest.mark.asyncio
async def test_list_is_always_the_entry_state() -> None:
    """AC-001: ни sessionStorage, ни ?view=map не могут открыть экран картой.

    Раньше этот класс багов гасился флагом MAP_ENABLED в двух местах. Теперь
    состояние просто не достижимо при входе — и тест сторожит именно это, а не
    наличие предохранителя.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        js = _code_only((await client.get("/webapp/ice-tab.js")).text)

    boot = js.split("function boot()")[1]
    assert "state.view = 'list';" in boot
    # Обе прежние двери в вид «карта» при входе должны быть закрыты.
    assert "saved.view === 'map'" not in boot
    assert "params.get('view')" not in boot


@pytest.mark.asyncio
async def test_switch_is_one_tap_both_ways_and_hidden_for_coaches() -> None:
    """AC-002 + AC-005: одна кнопка обслуживает оба направления; у «Тренеров» её нет."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        js = _code_only((await client.get("/webapp/ice-tab.js")).text)

    assert "setView(mapViewActive() ? 'list' : 'map')" in js
    # Подпись зовёт в другое состояние, а не называет текущее.
    assert "'Список' : 'Карта'" in js
    assert "state.intent !== 'coach'" in js.split("function mapAllowed()")[1].split("}")[0]


@pytest.mark.asyncio
async def test_map_stage_shows_a_loader_before_tiles() -> None:
    """AC-004: до тайлов — лоадер, а не пустая серая заливка.

    Требование лежало в TASK-082, которой никто не занимается. Без него возврат
    карты выглядел бы хуже её отсутствия: серый прямоугольник неотличим от поломки.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/webapp/ice")).text
        css = _code_only((await client.get("/webapp/ice-tab.css")).text)
        map_js = _code_only((await client.get("/webapp/ice-map.js")).text)

    assert "iceMapLoader" in body
    assert ".ice-map-loader" in css
    # Гасится в showStage — общей точке обоих исходов запуска (карта или пустое
    # состояние), а не вручную в каждой ветке start(), где легко забыть ветку.
    assert "setLoading(false)" in map_js.split("function showStage(on)")[1].split("\n    }")[0]
    assert "setLoading(true)" in map_js
