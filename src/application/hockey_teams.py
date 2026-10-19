"""Справочник команд «Кто кого»: короткое имя, цвет половинки, логотип (TASK-299).

Имена — как на hcdinamo.by. Цвет — основной клубный, достаточно тёмный, чтобы белый текст
на нём читался (контраст не ниже 4.5:1). Неизвестная команда получает нейтральный цвет
и короткое имя из первых букв, без логотипа.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

UNKNOWN_COLOR = "#5D7285"
LOGO_URL_PREFIX = "/static/webapp/hockey-logos"
_LOGO_DIR = Path(__file__).resolve().parents[2] / "static" / "webapp" / "hockey-logos"

_CYR = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


@dataclass(frozen=True)
class Team:
    slug: str
    short: str
    color: str


# Короткое имя — две буквы, чтобы половинки карточки не спорили за место.
# Цвета темнее «фирменного яркого», где яркий не держит белый текст.
TEAMS: dict[str, Team] = {
    "Динамо-Минск": Team("dinamo-minsk", "ДМ", "#003DA5"),
    "Динамо Москва": Team("dinamo-moscow", "МС", "#002F6C"),
    "ЦСКА": Team("cska", "ЦС", "#9D1024"),
    "СКА": Team("ska", "СК", "#C8102E"),
    "Локомотив": Team("lokomotiv", "ЛК", "#8C1515"),
    "Торпедо": Team("torpedo", "ТП", "#003865"),
    "ХК Сочи": Team("sochi", "СЧ", "#0057A8"),
    "Спартак": Team("spartak", "СП", "#8E0E1A"),
    "Северсталь": Team("severstal", "СВ", "#004B87"),
    "Витязь": Team("vityaz", "ВТ", "#4A1C3A"),
    "Ак Барс": Team("ak-bars", "АБ", "#006B3F"),
    "Барыс": Team("barys", "БР", "#003E73"),
    "Металлург Мг": Team("metallurg-mg", "МГ", "#1A1A1A"),
    "Авангард": Team("avangard", "АВ", "#8B1E3F"),
    "Салават Юлаев": Team("salavat-yulaev", "СЮ", "#007A33"),
    "Трактор": Team("traktor", "ТР", "#111111"),
    "Автомобилист": Team("avtomobilist", "АТ", "#0C2340"),
    "Нефтехимик": Team("neftekhimik", "НХ", "#006341"),
    "Амур": Team("amur", "АМ", "#1B365D"),
    "Адмирал": Team("admiral", "АД", "#002855"),
    "Сибирь": Team("sibir", "СБ", "#0A2F6B"),
    "Лада": Team("lada", "ЛД", "#8B1538"),
    "Шанхайские Драконы": Team("shanghai-dragons", "ШД", "#5C1A1B"),
}


def short_from_name(name: str) -> str:
    """Первые буквы слов; у одного слова — две первые буквы."""
    words = [word for word in re.split(r"[\s\-]+", (name or "").strip()) if word]
    if not words:
        return "??"
    if len(words) == 1:
        return words[0][:2].upper()
    return "".join(word[0] for word in words)[:2].upper()


def slug_for(name: str) -> str:
    known = TEAMS.get(name)
    if known is not None:
        return known.slug
    raw = (name or "").strip().lower().replace("ё", "е")
    parts: list[str] = []
    for ch in raw:
        if ch in _CYR:
            parts.append(_CYR[ch])
        elif ch.isascii() and ch.isalnum():
            parts.append(ch)
        elif parts and parts[-1] != "-":
            parts.append("-")
    slug = "".join(parts).strip("-")
    return slug or "team"


def logo_path(slug: str) -> Path:
    return _LOGO_DIR / f"{slug}.png"


def team_card(name: str) -> dict:
    """Карточка команды для API: имя, короткое, цвет, путь к логотипу или null."""
    known = TEAMS.get(name)
    if known is None:
        return {"name": name, "short": short_from_name(name), "color": UNKNOWN_COLOR, "logo": None}
    logo = f"{LOGO_URL_PREFIX}/{known.slug}.png" if logo_path(known.slug).is_file() else None
    return {"name": name, "short": known.short, "color": known.color, "logo": logo}


__all__ = [
    "LOGO_URL_PREFIX",
    "TEAMS",
    "UNKNOWN_COLOR",
    "Team",
    "logo_path",
    "short_from_name",
    "slug_for",
    "team_card",
]
