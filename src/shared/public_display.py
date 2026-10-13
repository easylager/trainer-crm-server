"""Публичный вывод адреса, телефона, имени и короткого дня.

Строки в базе не меняются. Здесь только то, что человек видит на сайте.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urlparse

_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_SPB_LO = re.compile(r"^санкт-петербург\s*/\s*ло$", re.IGNORECASE)
_OBLAST = re.compile(r"(область|обл\.?)$", re.IGNORECASE)
_PROSPEKT_DOT = re.compile(r"пр-т\.")
# «ул. Ташкентская 19» → «ул. Ташкентская, 19»: номер дома после улицы — через запятую.
_HOUSE_NO_COMMA = re.compile(
    r"^((?:ул\.|пр-т|просп\.|проспект|пер\.|бул\.|бульвар|пл\.|площадь|тракт|ш\.)\s+[^\d,]*[^\d\s,])\s+(\d[\w/-]*)$",
    re.IGNORECASE,
)
# «Замковая площадь 11А» → «Замковая площадь, 11А».
_HOUSE_NO_COMMA_TAIL = re.compile(
    r"^([^\d,]*\s(?:площадь|улица|проспект|переулок|бульвар))\s+(\d[\w/-]*)$",
    re.IGNORECASE,
)
_HK = re.compile(r"(?i)(?<!\w)хк(?!\w)")


def _fold(value: str) -> str:
    return value.strip().casefold().replace("ё", "е")


def format_clock(hhmm: str) -> str:
    """«9:00», «12:15». Час без ведущего нуля. Минуты остаются двумя цифрами."""
    raw = str(hhmm or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})", raw)
    if not match:
        return raw[:5]
    return f"{int(match.group(1))}:{match.group(2)}"


def short_day_word(day: date, *, today: date) -> str:
    """«сегодня» / «завтра» / «чт» — строчными, для середины фразы и списков."""
    if day == today:
        return "сегодня"
    if day == today + timedelta(days=1):
        return "завтра"
    return _WEEKDAYS_SHORT[day.weekday()]


def session_day_phrase(day: date, hhmm: str, *, today: date) -> str:
    """«сегодня 12:45» / «завтра 8:30» / «чт 10:30»."""
    clock = format_clock(hhmm)
    word = short_day_word(day, today=today)
    return f"{word} {clock}".strip()


def sentence_when(day: date, hhmm: str, *, today: date) -> str:
    """«сегодня, 14:00» / «завтра, 9:00» — день строчными в середине фразы."""
    clock = format_clock(hhmm)
    word = short_day_word(day, today=today)
    return f"{word}, {clock}" if clock else word


def format_phone_display(phone: str) -> str:
    """«+375 29 330-07-49» и «+7 999 123-45-67». ``tel:`` этим не кормим."""
    from src.shared.phone_guard import tel_href

    raw = str(phone or "").strip()
    href = tel_href(raw)
    if not href:
        return raw
    digits = href[1:] if href.startswith("+") else href
    if digits.startswith("375") and len(digits) == 12:
        code = digits[3:5]
        # Мобильные (25, 29, 33, 44) и Минск (17) — код из двух цифр. У остальных городов код
        # длиннее (Жлобин — 2334), и деление «23 343-52-59» было бы неправдой: оставляем подряд.
        if code in ("25", "29", "33", "44", "17"):
            return f"+375 {code} {digits[5:8]}-{digits[8:10]}-{digits[10:12]}"
        return f"+375 {digits[3:]}"
    if digits.startswith("7") and len(digits) == 11:
        return f"+7 {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return href if href.startswith("+") else raw


def display_host(url: str) -> str:
    """Домен ссылки, без пути. Punycode показываем буквами."""
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if not host:
        tail = str(url or "").split("://", 1)[-1]
        host = tail.split("/", 1)[0].split("?", 1)[0].strip().lower()
    if not host:
        return ""
    try:
        if "xn--" in host:
            host = host.encode("ascii").decode("idna")
    except UnicodeError:
        pass
    return host


def normalize_address_abbr(text: str) -> str:
    """«пр-т.» → «пр-т». «ул.» остаётся."""
    return _PROSPEKT_DOT.sub("пр-т", str(text or ""))


def format_street_address(address: str, *, city: str = "", region: str = "") -> str:
    """Улица без повтора города и области. Данные не трогаем — режем только вывод."""
    raw = normalize_address_abbr(str(address or "").strip())
    if not raw:
        return ""
    drop = {_fold(bit) for bit in (city, region) if str(bit or "").strip()}
    kept: list[str] = []
    for part in raw.split(","):
        piece = part.strip()
        if not piece:
            continue
        folded = _fold(piece)
        bare = folded.removeprefix("г.").strip(" .") if folded.startswith("г.") else folded
        if folded in drop or bare in drop:
            continue
        if _OBLAST.search(folded):
            continue
        piece = _HOUSE_NO_COMMA.sub(r"\1, \2", piece)
        kept.append(_HOUSE_NO_COMMA_TAIL.sub(r"\1, \2", piece))
    return ", ".join(kept)


def format_place_address(address: str, *, city: str = "", region: str = "") -> str:
    """Страница места: «ул. Ташкентская 19, Минск»."""
    street = format_street_address(address, city=city, region=region)
    city_label = format_public_name(city) if str(city or "").strip() else ""
    if street and city_label:
        return f"{street}, {city_label}"
    return street or city_label


def format_public_name(name: str) -> str:
    """Кавычки-ёлочки, «хк» → «ХК», «Санкт-Петербург/ЛО» → «Санкт-Петербург».

    Вертикальная черта в имени — данные, здесь не правится.
    """
    text = str(name or "").strip()
    if not text:
        return ""
    if _SPB_LO.match(_fold(text)):
        return "Санкт-Петербург"
    return _HK.sub("ХК", _guillemets(text))


def _guillemets(text: str) -> str:
    out: list[str] = []
    opened = False
    for ch in text:
        if ch == '"':
            out.append("»" if opened else "«")
            opened = not opened
        else:
            out.append(ch)
    return "".join(out)
