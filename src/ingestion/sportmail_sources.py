"""Запасной источник матчей Динамо-Минск: sportmail.ru. Только разбор, без сети и БД.

Включается, когда hcdinamo.by / hockey.by не отвечают (см. ``hockey_matches``). Обе страницы кладут данные
в ``window.__PRELOADED_STATE__PAGE`` — JSON, а не вёрстку, поэтому разбор не держится за классы и теги:

* ``/team/527/matches/407/`` — весь сезон Динамо одной таблицей: дата, время, команды, счёт, пометка «(ОТ)» / «(Бул)»;
* ``/hockey-khl/407/match/<id>/`` — страница матча: счёт, статус («Матч завершен»), идёт ли игра.

Время на sportmail — московское, то есть минское (оба UTC+3).
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from src.ingestion.hockey_sources import DECIDED_OT, DECIDED_REGULATION, DECIDED_SO

MINSK_TZ = ZoneInfo("Europe/Minsk")

SPORTMAIL_BASE = "https://sportmail.ru"
SPORTMAIL_DINAMO_MATCHES_URL = f"{SPORTMAIL_BASE}/team/527/matches/407/"
SPORTMAIL_DINAMO = "Динамо Мн"

# Как sportmail называет клубы, чьи названия у нас другие. Остальные клубы КХЛ называются одинаково.
_ALIASES = {
    "Динамо Мн": "Динамо-Минск",
    "Динамо М": "Динамо Москва",
    "Сочи": "ХК Сочи",
    "Шанхай Дрэгонс": "Шанхайские Драконы",
}

_STATE = re.compile(r"__PRELOADED_STATE__PAGE\s*=\s*")
_MATCH_ID = re.compile(r"/match/(\d+)/")
_SCORE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")
_DECIDED = {"(ОТ)": DECIDED_OT, "(Бул)": DECIDED_SO, "": DECIDED_REGULATION}


@dataclass(frozen=True)
class SportmailMatch:
    """Строка таблицы «Матчи» Динамо. ``home`` / ``away`` — уже в наших названиях."""

    source_match_id: str
    starts_at: datetime
    home: str
    away: str
    home_score: int | None
    away_score: int | None
    decided_in: str | None

    @property
    def played(self) -> bool:
        return self.home_score is not None and self.away_score is not None and self.decided_in is not None


@dataclass(frozen=True)
class SportmailPage:
    """Страница матча: счёт на табло и состояние игры."""

    home: str
    away: str
    home_score: int | None
    away_score: int | None
    is_played: bool
    is_online: bool


def club_name(raw: str) -> str:
    """Название клуба как у нас; неизвестное остаётся как есть (такой матч сайт не покажет — клуба нет в реестре)."""
    name = html.unescape(raw).replace("\xa0", " ").strip()
    return _ALIASES.get(name, name)


def _state(page_html: str) -> dict:
    found = _STATE.search(page_html)
    if found is None:
        raise ValueError("sportmail.ru: на странице нет данных (__PRELOADED_STATE__PAGE) — похоже, сменилась вёрстка")
    state, _ = json.JSONDecoder().raw_decode(page_html[found.end() :])
    return state


def _score(text: str | None) -> tuple[int, int] | None:
    found = _SCORE.match(html.unescape(text or "").replace("\xa0", " "))
    return (int(found.group(1)), int(found.group(2))) if found else None


def parse_sportmail_team_matches(page_html: str) -> list[SportmailMatch]:
    """Все матчи Динамо в таблице. Строка с непонятной датой или без двух команд пропускается."""
    tables = (_state(page_html).get("page_data") or {}).get("tables") or {}
    out: list[SportmailMatch] = []
    for table in tables.get("items") or []:
        for row in table.get("tbody") or []:
            cells = row.get("cells") or []
            if len(cells) < 4:
                continue
            when, teams, score = cells[1], cells[2], cells[3]
            names = [club_name(str(t.get("text") or "")) for t in teams.get("teams") or []]
            ident = _MATCH_ID.search(str(score.get("href") or ""))
            try:
                starts_at = datetime.strptime(f"{when['date']} {when['time']}", "%d.%m.%Y %H:%M").replace(tzinfo=MINSK_TZ)
            except (KeyError, ValueError):
                continue
            if len(names) != 2 or ident is None:
                continue
            result = _score(score.get("text"))
            decided = _DECIDED.get(str(score.get("subtext") or "").strip()) if result else None
            out.append(
                SportmailMatch(
                    source_match_id=ident.group(1),
                    starts_at=starts_at,
                    home=names[0],
                    away=names[1],
                    home_score=result[0] if result else None,
                    away_score=result[1] if result else None,
                    decided_in=decided,
                )
            )
    return out


def sportmail_match_url(source_match_id: str) -> str:
    return f"{SPORTMAIL_BASE}/hockey-khl/407/match/{source_match_id}/"


def parse_sportmail_match(page_html: str) -> SportmailPage:
    details = ((_state(page_html).get("page_data") or {}).get("details")) or {}
    teams = details.get("teams") or []
    if len(teams) != 2:
        raise ValueError("sportmail.ru: на странице матча нет двух команд")
    status = details.get("status") or {}

    def pts(team: dict) -> int | None:
        value = team.get("score")
        return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None

    return SportmailPage(
        home=club_name(str(teams[0].get("name") or "")),
        away=club_name(str(teams[1].get("name") or "")),
        home_score=pts(teams[0]),
        away_score=pts(teams[1]),
        is_played=bool(status.get("is_played")),
        is_online=bool(status.get("is_online")),
    )
