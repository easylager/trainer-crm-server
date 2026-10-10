"""TASK-223: контракт start_param Mini App — python-сторона (без БД).

Те же кейсы читает tests/contract/deeplink-contract.test.js (шелл/glide-deeplink + arena-card-model).
Формат кейса в ``deeplink_cases.json``:

* ``expect`` — общий контракт: ``kind`` (``arena`` | ``catalog`` | ``null``), ``arena_id``, ``session_id``,
  ``city_id``, ``intent``, ``when``; опущенное поле = ``null``;
* ``py`` / ``js`` — если сторона законно отличается, здесь её ожидание целиком (вместо ``expect``);
* ``card`` — ``arena-card-model`` (``parseArenaRef`` / ``sessionIdFromStartParam``), только в JS-тесте;
* ``build`` — что должны собрать билдеры ``place_start_param`` / ``catalog_start_param`` (круг «собрали → разобрали»);
* ``valid_start_param`` — ``is_valid_start_param`` (правила Telegram: ``[A-Za-z0-9_-]{1,64}``).

Запуск (``tests/conftest.py`` требует env Settings и локальный URL БД, но сама БД не нужна)::

    TELEGRAM_BOT_TOKEN_CLIENT=x TELEGRAM_BOT_TOKEN_TRAINER=x \\
    DATABASE_URL=postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm_test \\
    PYTHONPATH=. pytest tests/contract/test_deeplink_contract_py.py -q
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.application.place_links import (
    catalog_start_param,
    is_valid_start_param,
    parse_catalog_start_param,
    parse_place_deep_link,
    place_start_param,
)

CASES: list[dict[str, Any]] = json.loads((Path(__file__).parent / "deeplink_cases.json").read_text(encoding="utf-8"))
_FIELDS = ("kind", "arena_id", "session_id", "city_id", "intent", "when")


def _norm(expect: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {f: None for f in _FIELDS}
    out.update(expect)
    for f in ("arena_id", "session_id", "city_id"):
        if out[f] is not None:
            out[f] = str(out[f])
    return out


def parse_like_server(start_param: str) -> dict[str, Any]:
    """Как сервер читает payload: сначала место, потом каталог."""
    place = parse_place_deep_link(start_param)
    if place is not None:
        arena_id, session_id = place
        return _norm({"kind": "arena", "arena_id": arena_id, "session_id": session_id})
    catalog = parse_catalog_start_param(start_param)
    if catalog is not None:
        city_id, intent, when = catalog
        return _norm({"kind": "catalog", "city_id": city_id, "intent": intent, "when": when})
    return _norm({"kind": None})


def _id(case: dict[str, Any]) -> str:
    return case["start_param"][:40] or "<empty>"


def test_cases_file_covers_required_edge_cases() -> None:
    have = {c["start_param"] for c in CASES}
    required = {
        "arena_42",
        "arena_42_s_9001",
        "arena-42",
        "arena_0",
        "arena_42_s_0",
        "ARENA_42",
        "catalog",
        "catalog_12",
        "catalog_12_skate_weekend",
        "catalog_12_sauna",
        "catalog_12_weekend",
        "garbage",
        "",
    }
    assert required <= have
    assert any(len(sp) >= 64 for sp in have), "нужен кейс 64+ символов"


@pytest.mark.parametrize("case", CASES, ids=_id)
def test_python_parser_matches_contract(case: dict[str, Any]) -> None:
    want = _norm(case.get("py", case["expect"]))
    assert parse_like_server(case["start_param"]) == want, case.get("note")


@pytest.mark.parametrize("case", CASES, ids=_id)
def test_start_param_validity_matches_telegram_rules(case: dict[str, Any]) -> None:
    assert is_valid_start_param(case["start_param"]) is case["valid_start_param"]


@pytest.mark.parametrize("case", [c for c in CASES if "build" in c], ids=_id)
def test_builders_roundtrip(case: dict[str, Any]) -> None:
    b = case["build"]
    if b["kind"] == "arena":
        built = place_start_param(b["arena_id"], b.get("session_id"))
    else:
        built = catalog_start_param(b["city_id"], b.get("intent"), b.get("when"))
    assert built == case["start_param"]
    assert is_valid_start_param(built)
    assert parse_like_server(built) == _norm(case["expect"])
