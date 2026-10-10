"""Rank a small public catalog in process: name, address, service, venue, typo.

Postgres ``pg_trgm`` is not installed on the catalog database, and ``simple``
tsvector does not decline Russian. The visible set is a few hundred places, so
each keystroke loads that set and scores it here. Name hits beat a street, a
street beats a service word, and the city the person already picked is lifted
above the same hit in another city.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

_WORD = re.compile(r"[0-9a-zа-я]+")
_DIGIT_RUN = re.compile(r"\d{5,}")

# Longest ending first so «чижовки» sheds «и», not a shorter suffix.
_ENDINGS = (
    "ами",
    "ями",
    "ого",
    "ему",
    "ыми",
    "ими",
    "ах",
    "ях",
    "ов",
    "ев",
    "ой",
    "ий",
    "ый",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ам",
    "ям",
    "ом",
    "ем",
    "ую",
    "юю",
    "а",
    "я",
    "у",
    "ю",
    "е",
    "ы",
    "и",
    "о",
)

# Words that sit in almost every card text. They still match a name or a
# venue type; they must not match the description.
_BLURB_STOP = frozenset(
    {
        "каток",
        "катки",
        "катка",
        "лед",
        "ледовый",
        "ледовая",
        "ледовое",
        "дворец",
        "спорта",
        "спортивный",
        "массовое",
        "массовые",
        "катание",
        "катания",
        "сеанс",
        "билет",
        "билеты",
        "прокат",
        "заточка",
        "магазин",
        "хоккей",
        "хоккейный",
        "фигурное",
        "зал",
        "трасса",
        "арена",
        "минск",
        "город",
    }
)

_ADDRESS_STOP = frozenset(
    {
        "ул",
        "улица",
        "пр",
        "проспект",
        "просп",
        "пер",
        "переулок",
        "дом",
        "город",
        "область",
        "район",
        "этаж",
        "пав",
        "тц",
        "трц",
        "минск",
        "беларусь",
    }
)

# stem, amenity key, line shown under the hit
_SERVICE_STEMS: tuple[tuple[str, str, str], ...] = (
    ("заточ", "skate_sharpening", "Заточка"),
    ("наточ", "skate_sharpening", "Заточка"),
    ("точк", "skate_sharpening", "Заточка"),
    ("прокат", "skate_rental", "Прокат"),
    ("аренд", "skate_rental", "Прокат"),
    ("коньк", "skate_rental", "Прокат"),
    ("ремонт", "repair", "Ремонт"),
    ("формовк", "skate_molding", "Формовка"),
    ("профилир", "blade_profiling", "Профилирование"),
    ("скан", "foot_scan", "3D-скан"),
    ("хокке", "discipline_hockey", "Хоккей"),
    ("фигурн", "discipline_figure", "Фигурное"),
    ("ролик", "discipline_roller", "Ролики"),
    ("купить", "retail", "Розница"),
    ("магазин", "retail", "Магазин"),
    ("экипир", "retail", "Экипировка"),
)

# word, venue types, line under the hit.
# Ice is city-scoped: «каток» must not list every rink in the country.
_VENUE_WORDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("каток", ("ice", "outdoor"), "Каток"),
    ("катки", ("ice", "outdoor"), "Каток"),
    ("катка", ("ice", "outdoor"), "Каток"),
    ("катку", ("ice", "outdoor"), "Каток"),
    ("лед", ("ice", "outdoor"), "Каток"),
    ("льду", ("ice", "outdoor"), "Каток"),
    ("ледовый", ("ice", "outdoor"), "Каток"),
    ("ледовая", ("ice", "outdoor"), "Каток"),
    ("зал", ("gym", "choreo"), "Зал"),
    ("зала", ("gym", "choreo"), "Зал"),
    ("залы", ("gym", "choreo"), "Зал"),
    ("бассейн", ("pool",), "Бассейн"),
    ("трасса", ("other",), "Трасса"),
    ("лыжеролл", ("other",), "Трасса"),
    ("магазин", ("shop",), "Магазин"),
    ("мастерск", ("shop",), "Мастерская"),
)

_CITY_SCOPED_VENUES = frozenset({"ice", "outdoor"})
_KIND_SCORE = {"exact": 100, "prefix": 82, "stem": 74, "infix": 68, "typo": 62}
_CITY_BOOST = 25
_EXTRA_WORD = 7


def fold(value: str | None) -> str:
    return str(value or "").replace("Ё", "Е").replace("ё", "е").lower()


def words_of(value: str | None) -> list[str]:
    return _WORD.findall(fold(value))


def stem(word: str) -> str:
    w = fold(word)
    if len(w) < 5:
        return w
    for end in _ENDINGS:
        if w.endswith(end) and len(w) - len(end) >= 4:
            return w[: -len(end)]
    return w


def _trigrams(token: str) -> set[str]:
    padded = f" {fold(token)} "
    if len(padded) < 3:
        return set()
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def similarity(left: str, right: str) -> float:
    a, b = _trigrams(left), _trigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def query_wants_ohm(query: str) -> bool:
    words = words_of(query)
    if any(w == "охм" or w.startswith("охм") for w in words):
        return True
    if any(w.startswith("любител") for w in words):
        return True
    blob = " ".join(words)
    return "открыт" in blob and "хокке" in blob


def service_amenity_keys_for_query(query: str) -> list[str]:
    """Amenity keys a query asks for («заточка» → skate_sharpening)."""
    keys: list[str] = []
    for word in words_of(query):
        for stem_prefix, key, _label in _SERVICE_STEMS:
            if (word.startswith(stem_prefix) or stem_prefix in word) and key not in keys:
                keys.append(key)
    return keys


def _amenity_on(amenities: Mapping[str, Any] | None, key: str) -> bool:
    if not isinstance(amenities, Mapping):
        return False
    value = amenities.get(key)
    if value is True:
        return True
    return isinstance(value, str) and value.lower() == "true"


def _token_kind(word: str, tokens: list[str], *, typos: bool) -> str | None:
    w = fold(word)
    if len(w) < 2 or not tokens:
        return None
    sw = stem(w)
    best: str | None = None
    rank = {"exact": 5, "prefix": 4, "stem": 3, "infix": 2, "typo": 1}
    for tok in tokens:
        kind = None
        if tok == w:
            kind = "exact"
        elif len(w) >= 2 and tok.startswith(w):
            kind = "prefix"
        elif len(sw) >= 4 and len(tok) >= 4 and (tok.startswith(sw) or stem(tok) == sw):
            kind = "stem"
        elif len(w) >= 4 and w in tok:
            kind = "infix"
        if kind and (best is None or rank[kind] > rank[best]):
            best = kind
            if best == "exact":
                return best
    if best:
        return best
    if typos and len(w) >= 5:
        nearest = max((similarity(w, tok) for tok in tokens if len(tok) >= 4), default=0.0)
        if nearest >= 0.4:
            return "typo"
    return None


def _service_label(word: str, amenities: Mapping[str, Any] | None) -> str:
    for stem_prefix, key, label in _SERVICE_STEMS:
        if word.startswith(stem_prefix) or stem_prefix in word:
            if _amenity_on(amenities, key):
                return label
    return ""


def _venue_label(word: str, venue_type: str) -> str:
    for stem_prefix, types, label in _VENUE_WORDS:
        if word == stem_prefix or (len(stem_prefix) >= 4 and word.startswith(stem_prefix)):
            if venue_type in types:
                return label
    return ""


def _blurb_stopped(word: str) -> bool:
    w = fold(word)
    sw = stem(w)
    if w in _BLURB_STOP or sw in _BLURB_STOP:
        return True
    return any(sw.startswith(stop) or stop.startswith(sw) for stop in _BLURB_STOP if len(stop) >= 4 and len(sw) >= 4)


def address_hint(address: str | None, city_name: str | None, query: str) -> str:
    """Street line. If the match sits past the cut, show the piece that matched."""
    raw = " ".join(str(address or "").split())
    city = fold(city_name)
    folded = fold(raw)
    for prefix in (f"{city},", city):
        if prefix and folded.startswith(prefix):
            raw = raw[len(prefix) :].strip(" ,")
            folded = fold(raw)
    words = [word for word in words_of(query) if len(word) >= 4 or word.isdigit()]
    head = raw if len(raw) <= 52 else raw[:52].rstrip(" ,.;") + "…"
    if any(word in fold(head) for word in words) or not any(word in folded for word in words):
        return head
    for word in words:
        if word in folded:
            return _snippet(raw, word)
    return head


def _snippet(text: str, word: str) -> str:
    raw = " ".join(str(text or "").split())
    folded = fold(raw)
    needle = fold(word)
    at = folded.find(needle)
    if at < 0:
        st = stem(needle)
        at = folded.find(st) if len(st) >= 4 else -1
        needle = st if at >= 0 else needle
    if at < 0:
        return ""
    start = at
    while start > 0 and raw[start - 1] not in " \n\t":
        start -= 1
        if at - start > 14:
            break
    chunk = raw[start : start + 46].strip(" ,.;:—-")
    if start > 0:
        chunk = "…" + chunk
    if start + 46 < len(raw):
        chunk = chunk.rstrip(" ,.;") + "…"
    if any(bad in fold(chunk) for bad in ("origin", "csv", "403", "unknown", "conflicts")):
        return ""
    return chunk


def _consider(found: list[tuple[int, str, str]], score: int, reason: str, hint: str) -> None:
    if score > 0 and hint is not None:
        found.append((score, reason, hint))


def score_place(
    query: str,
    row: Mapping[str, Any],
    *,
    city_id: int | None = None,
    ohm_ids: set[int] | None = None,
) -> dict[str, Any] | None:
    """Return a ranked hit, or None when nothing in the query lands on this place."""
    words = words_of(query)
    if not words:
        return None
    name = str(row.get("name") or "")
    venue = str(row.get("venue_type") or "ice")
    amenities = row.get("amenities") if isinstance(row.get("amenities"), Mapping) else {}
    city_name = str(row.get("city_name") or "")
    address = address_hint(row.get("address"), city_name, query)
    district = str(row.get("district") or "").strip()
    blurb = str(row.get("blurb") or "")
    name_tokens = words_of(name)
    city_fold = fold(city_name)
    address_tokens = [
        tok
        for tok in words_of(row.get("address"))
        if tok not in _ADDRESS_STOP and tok != city_fold and len(tok) >= 3
    ]
    district_tokens = words_of(district)
    blurb_tokens = words_of(blurb)
    found: list[tuple[int, str, str]] = []
    matched_words = 0
    for word in words:
        before = len(found)
        kind = _token_kind(word, name_tokens, typos=True)
        if kind:
            _consider(found, _KIND_SCORE[kind], kind, address or district)
        # Two letters are a prefix of a name («чи» → Чижовка), not a service
        # or a street: «за» must not open every sharpening shop.
        if len(word) < 3:
            if len(found) > before:
                matched_words += 1
            continue
        if len(word) >= 4 or word.isdigit():
            addr_kind = _token_kind(word, address_tokens, typos=False)
            if addr_kind:
                _consider(found, min(_KIND_SCORE[addr_kind], 58), "address", address)
        dist_kind = _token_kind(word, district_tokens, typos=False)
        if dist_kind:
            _consider(found, min(_KIND_SCORE[dist_kind], 52), "district", district or address)
        if not _blurb_stopped(word):
            blur_kind = _token_kind(word, blurb_tokens, typos=False)
            if blur_kind:
                snip = _snippet(blurb, word)
                # A phone number or a three-word scrap is a worse line than the street.
                if snip and (_DIGIT_RUN.search(snip) or len(snip.lstrip("…").strip()) < 12):
                    snip = address
                if snip:
                    _consider(found, 42, "blurb", snip)
        service = _service_label(word, amenities)
        if service:
            hint = f"{service} · {address}" if address else service
            _consider(found, 44, "service", hint)
        venue_label = _venue_label(word, venue)
        if venue_label:
            hint = f"{venue_label} · {address}" if address else venue_label
            _consider(found, 32, "venue", hint)
        if len(found) > before:
            matched_words += 1
    if ohm_ids and int(row.get("id") or 0) in ohm_ids and query_wants_ohm(query):
        hint = f"ОХМ · {address}" if address else "ОХМ"
        _consider(found, 40, "ohm", hint)
        matched_words = max(matched_words, 1)
    if not found:
        return None
    reasons = {reason for _score, reason, _hint in found}
    row_city = row.get("city_id")
    venue_only = reasons <= {"venue"}
    if (
        venue_only
        and city_id is not None
        and row_city != city_id
        and venue in _CITY_SCOPED_VENUES
    ):
        return None
    found.sort(key=lambda item: item[0], reverse=True)
    score, _reason, hint = found[0]
    if matched_words > 1:
        score += _EXTRA_WORD * (matched_words - 1)
    if city_id is not None and row_city == city_id:
        score += _CITY_BOOST
    return {
        "id": int(row["id"]),
        "slug": row.get("slug"),
        "name": name,
        "city_id": int(row_city) if row_city is not None else None,
        "district": district or None,
        "city_name": city_name,
        "venue_type": venue,
        "address": address,
        "hint": hint,
        "score": score,
    }


def score_person(
    query: str,
    row: Mapping[str, Any],
    *,
    city_id: int | None = None,
) -> dict[str, Any] | None:
    name = " ".join(part for part in (row.get("first_name"), row.get("last_name")) if part).strip()
    kind = _token_kind_any(query, words_of(name))
    if not kind:
        return None
    score = _KIND_SCORE[kind]
    row_city = row.get("city_id")
    if city_id is not None and row_city == city_id:
        score += _CITY_BOOST
    return {
        "id": int(row["id"]),
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "name": name,
        "city_id": int(row_city) if row_city is not None else None,
        "city_name": str(row.get("city_name") or ""),
        "hint": str(row.get("city_name") or ""),
        "score": score,
    }


def score_city(query: str, row: Mapping[str, Any]) -> dict[str, Any] | None:
    name = str(row.get("name") or "")
    kind = _token_kind_any(query, words_of(name))
    if not kind:
        return None
    return {"id": int(row["id"]), "name": name, "score": _KIND_SCORE[kind]}


def _token_kind_any(query: str, tokens: list[str]) -> str | None:
    best: str | None = None
    rank = {"exact": 5, "prefix": 4, "stem": 3, "infix": 2, "typo": 1}
    for word in words_of(query):
        kind = _token_kind(word, tokens, typos=True)
        if kind and (best is None or rank[kind] > rank[best]):
            best = kind
    return best


def _by_score(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(hits, key=lambda hit: (-int(hit["score"]), fold(str(hit.get("name") or "")), int(hit["id"])))


def rank_places(
    query: str,
    rows: list[Mapping[str, Any]],
    *,
    city_id: int | None = None,
    ohm_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    hits = [
        hit
        for row in rows
        if (hit := score_place(query, row, city_id=city_id, ohm_ids=ohm_ids)) is not None
    ]
    return _by_score(hits)


def rank_people(
    query: str,
    rows: list[Mapping[str, Any]],
    *,
    city_id: int | None = None,
) -> list[dict[str, Any]]:
    hits = [hit for row in rows if (hit := score_person(query, row, city_id=city_id)) is not None]
    return _by_score(hits)


def rank_cities(query: str, rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    hits = [hit for row in rows if (hit := score_city(query, row)) is not None]
    return _by_score(hits)
