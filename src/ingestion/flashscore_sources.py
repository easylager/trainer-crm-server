"""Запасной источник матчей Экстралиги: flashscore.com. Только разбор, без сети и БД.

Включается, когда hockey.by не отвечает (см. ``extraliga``). Одна страница лиги отдаёт обе ленты сразу —
``cjs.initialFeeds['results']`` (сыгранные) и ``cjs.initialFeeds['fixtures']`` (ближайшие): строка
собственного формата flashscore. Записи разделены ``~``, поля — ``¬``, ключ и значение — ``÷``.
Матч начинается с ``AA÷<id>``; нужные поля:

* ``AD`` — начало, unix-время (UTC); ``AE`` / ``AF`` — хозяева / гости (английские названия);
* ``AG`` / ``AH`` — счёт; при победе по буллитам победителю уже добавлена шайба, как на hockey.by;
* ``AB`` — стадия: 1 — не начат, 2 — идёт, 3 — завершён;
* ``AC`` — у завершённого как он решён: 3 — основное время, 10 — овертайм, 11 — буллиты.

Условия flashscore запрещают автоматический сбор — риск принят владельцем осознанно: один запрос
в 10 минут, только пока hockey.by лежит, честный User-Agent, без обхода защиты.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from src.ingestion.hockey_sources import DECIDED_OT, DECIDED_REGULATION, DECIDED_SO

FLASHSCORE_EXTRALIGA_URL = "https://www.flashscore.com/hockey/belarus/extraleague/"

STATUS_SCHEDULED = "scheduled"
STATUS_LIVE = "live"
STATUS_FINAL = "final"
# Завершён без счёта (перенос, отмена) или стадия, которой мы не знаем: такой матч не трогаем.
STATUS_OTHER = "other"

# Название flashscore → club id hockey.by (ключи ``CLUBS`` в ``application/extraliga.py``).
CLUB_IDS: dict[str, str] = {
    "Yunost Minsk": "10",
    "Neman Grodno": "14",
    "Brest": "11",
    "Soligorsk": "12",  # Шахтер
    "Molodechno": "13",  # Динамо-Молодечно
    "Lida": "20",
    "Baranavichy": "21",  # Авиатор
    "Zhlobin": "16",  # Металлург Жлобин
    "Vitebsk": "22",
    "Slavutych": "225",  # Славутич (Смоленск)
    "Gomel": "1",
    "Novopolotsk": "15",  # Химик
    "Lokomotiv Orsha": "19",
    "Mogilev": "23",
}

_FEED = re.compile(r"cjs\.initialFeeds\['(results|fixtures)'\]\s*=\s*\{\s*data:\s*`(.*?)`", re.S)
_DECIDED = {"3": DECIDED_REGULATION, "10": DECIDED_OT, "11": DECIDED_SO}
_STAGES = {"1": STATUS_SCHEDULED, "2": STATUS_LIVE, "3": STATUS_FINAL}
# Один матч бывает в обеих лентах (только что закончился): берём более позднюю стадию.
_ORDER = {STATUS_OTHER: 0, STATUS_SCHEDULED: 1, STATUS_LIVE: 2, STATUS_FINAL: 3}


@dataclass(frozen=True)
class FlashscoreMatch:
    """Матч из ленты. ``home_club_id`` / ``away_club_id`` — id hockey.by; ``None`` — клуб нам неизвестен."""

    source_match_id: str
    starts_at: datetime
    home: str
    away: str
    home_club_id: str | None
    away_club_id: str | None
    status: str
    home_score: int | None
    away_score: int | None
    # Только у завершённого; ``None`` у завершённого со счётом — способ окончания не распознан.
    decided_in: str | None


def _fields(record: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in record.split("¬"):
        key, sep, value = part.partition("÷")
        if sep and key not in out:
            out[key] = value
    return out


def _int(value: str | None, what: str, match_id: str) -> int | None:
    if value is None or value == "":
        return None
    if not value.isdigit():
        raise ValueError(f"flashscore: у матча {match_id} {what} «{value}» — не число, сменился формат ленты")
    return int(value)


def _match(f: dict[str, str]) -> FlashscoreMatch:
    match_id = f["AA"]
    missing = [k for k in ("AD", "AE", "AF", "AB") if not f.get(k)]
    if missing:
        raise ValueError(f"flashscore: у матча {match_id} нет полей {', '.join(missing)} — сменился формат ленты")
    starts = _int(f["AD"], "время начала", match_id)
    assert starts is not None
    home_score = _int(f.get("AG"), "счёт хозяев", match_id)
    away_score = _int(f.get("AH"), "счёт гостей", match_id)
    status = _STAGES.get(f["AB"], STATUS_OTHER)
    decided = None
    if status == STATUS_FINAL:
        if home_score is None or away_score is None:
            status = STATUS_OTHER  # завершён без счёта: перенос или отмена
        else:
            decided = _DECIDED.get(f.get("AC", ""))
    home, away = f["AE"].strip(), f["AF"].strip()
    return FlashscoreMatch(
        source_match_id=match_id,
        starts_at=datetime.fromtimestamp(starts, tz=timezone.utc),
        home=home,
        away=away,
        home_club_id=CLUB_IDS.get(home),
        away_club_id=CLUB_IDS.get(away),
        status=status,
        home_score=home_score if status in (STATUS_LIVE, STATUS_FINAL) else None,
        away_score=away_score if status in (STATUS_LIVE, STATUS_FINAL) else None,
        decided_in=decided,
    )


def parse_flashscore_league(page_html: str) -> list[FlashscoreMatch]:
    """Все матчи обеих лент. Нет лент или у матча нет обязательного поля — ``ValueError``: молча
    подсовывать игре пустой календарь хуже, чем громко упасть."""
    feeds = _FEED.findall(page_html)
    if not feeds:
        raise ValueError("flashscore: на странице нет лент матчей (cjs.initialFeeds) — похоже, сменилась вёрстка")
    by_id: dict[str, FlashscoreMatch] = {}
    for _, data in feeds:
        for record in data.split("~"):
            if not record.startswith("AA÷"):
                continue
            m = _match(_fields(record))
            old = by_id.get(m.source_match_id)
            if old is None or _ORDER[m.status] >= _ORDER[old.status]:
                by_id[m.source_match_id] = m
    return sorted(by_id.values(), key=lambda m: (m.starts_at, m.source_match_id))


__all__ = [
    "CLUB_IDS",
    "FLASHSCORE_EXTRALIGA_URL",
    "FlashscoreMatch",
    "STATUS_FINAL",
    "STATUS_LIVE",
    "STATUS_OTHER",
    "STATUS_SCHEDULED",
    "parse_flashscore_league",
]
