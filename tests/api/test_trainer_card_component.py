"""TASK-092: карточка тренера — один компонент, без обрезаний.

Зачем тест. F-5 возник не оттого, что кто-то плохо сверстал карточку, а оттого,
что карточка существовала двумя независимыми копиями CSS, и копии разошлись:
в карусели плейсхолдер показывал инициалы, в списке «Лёд» это была пустая
заливка. Расхождение бесшумное — глазами его ловят через недели.

Поэтому тест держит именно то, что разъезжается: единый источник стилей и
отсутствие приёмов, которые обрезают факты.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app

REPO_ROOT = Path(__file__).resolve().parents[2]
_WEBAPP = REPO_ROOT / "static/webapp"


def _code_only(text: str) -> str:
    """Убирает комментарии.

    Первая версия этих проверок искала подстроки во всём файле и падала на
    собственных комментариях, где объясняется, что именно убрано. Проверять надо
    объявления, а не рассказ о них.
    """
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.MULTILINE)


@pytest.mark.asyncio
async def test_trainer_card_component_is_served() -> None:
    """Компонент отдаётся сервером: без маршрута файл существует, но 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        css = await client.get("/webapp/mini-app-trainer-card.css")
        page = await client.get("/webapp/client-home")
    assert css.status_code == 200
    assert ".tcard" in css.text
    assert page.status_code == 200
    assert "mini-app-trainer-card.css" in page.text


def test_card_has_single_source_of_truth() -> None:
    """AC/DEC-001: карточка живёт в одном файле, дубликат на Главной удалён."""
    home_css = _code_only((_WEBAPP / "mini-app-client-home.css").read_text(encoding="utf-8"))
    for leftover in (
        ".hub-discovery__card",
        ".hub-discovery__avatar",
        ".hub-discovery__name",
        ".hub-discovery__svc",
    ):
        assert leftover not in home_css, f"дубликат компонента вернулся: {leftover}"


def test_card_never_truncates_facts() -> None:
    """AC-001/AC-002: ни имя, ни место, ни услуги не обрезаются.

    `text-overflow: ellipsis` и `-webkit-line-clamp` — ровно те два приёма,
    которыми обрезались три факта подряд. В компоненте их быть не должно:
    факт либо переносится, либо не показывается вовсе.
    """
    card_css = _code_only((_WEBAPP / "mini-app-trainer-card.css").read_text(encoding="utf-8"))
    assert "text-overflow" not in card_css
    assert "line-clamp" not in card_css
    assert "white-space: nowrap" not in card_css


def test_services_are_whole_units_not_a_joined_line() -> None:
    """AC-002: услуги — чипы и честный счётчик остатка, а не склейка через « · »."""
    js = _code_only((_WEBAPP / "client-home-main.js").read_text(encoding="utf-8"))
    assert "hubDiscoveryServiceChips" in js
    assert "tcard__svc--more" in js
    assert "labels.join(' · ')" not in js


def test_placeholder_is_a_designed_object() -> None:
    """AC-004: у карточки без фото — инициалы и брендовая геометрия, не пустой блок.

    Плейсхолдер здесь основное состояние, а не край: по замеру локальной БД фото
    есть у одного тренера из девяти.
    """
    card_css = _code_only((_WEBAPP / "mini-app-trainer-card.css").read_text(encoding="utf-8"))
    block = card_css.split(".tcard__media--empty")[1].split("}")[0]
    assert "--glide-brand-wash" in block
    assert "--glide-ink-teal" in block
    assert "--app-ribbon-clip-avatar" in block

    js = (_WEBAPP / "client-home-main.js").read_text(encoding="utf-8")
    # Сбой загрузки фото ведёт к тому же плейсхолдеру, что и его отсутствие.
    assert "tcard__media--empty" in js
    assert "initials(name)" in js
