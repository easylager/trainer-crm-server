"""Карточка катка v2: что клиенту нужно знать до поездки.

Админка хранит сырые настройки в ``arena_profiles.visit_info`` (jsonb). Отсюда
выходит одна модель для сайта и Mini App — ``visit_view``. Блоки, их порядок и
условие появления заданы здесь, а не на каждой арене: данные появились — блок
встал на своё место, данных нет — блока нет.

Старые поля читаются как запасной источник, без миграции данных:
``amenities`` (галочки), ``opening_hours.rental_catalog`` / ``rental_note`` /
``ticket_note`` / ``kassa``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Порядок блоков страницы катка. Один на сайт и Mini App; тест сверяет оба.
PLACE_BLOCKS: tuple[str, ...] = ("cover", "ice", "facts", "services", "trainers", "partners", "more")

TICKET_MODES: tuple[str, ...] = ("online", "same_day", "box_office", "phone")
FACT_STATES: tuple[str, ...] = ("yes", "no")
WARMTH_STATES: tuple[str, ...] = ("warm", "cool", "cold")
SERVICE_KINDS: tuple[str, ...] = ("aid", "rental", "sharpening", "protection", "helmet", "other")
FACT_ICONS: tuple[str, ...] = (
    "hanger", "lock", "cup", "thermo", "card", "child", "eye", "ruler", "clock", "info", "parking", "person",
)

# Порядок и подписи фактов. «Нет» тоже ответ: без кафе клиент возьмёт термос.
_FACTS: tuple[tuple[str, str, str, str], ...] = (
    # key, icon, «есть», «нет»
    ("locker_rooms", "hanger", "Раздевалка есть", "Раздевалки нет"),
    ("lockers", "lock", "Камеры хранения", "Камер хранения нет"),
    ("cafe", "cup", "Кафе", "Кафе нет"),
    ("parking", "parking", "Парковка", "Парковки нет"),
)
_WARMTH_TITLES = {"warm": "Внутри тепло", "cool": "Внутри прохладно", "cold": "Внутри холодно"}
FACTS_VISIBLE = 4

_SERVICE_ORDER = {kind: i for i, kind in enumerate(("aid", "rental", "protection", "helmet", "sharpening", "other"))}
_SERVICE_TITLES = {
    "aid": "Опора «пингвин»",
    "rental": "Прокат коньков",
    "sharpening": "Заточка",
    "protection": "Защита",
    "helmet": "Шлем",
}
_SERVICE_ICONS = {
    "aid": "penguin",
    "rental": "skate",
    "sharpening": "sharpen",
    "protection": "shield",
    "helmet": "helmet",
    "other": "info",
}

_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
_TEXT_MAX = 200
_ROWS_MAX = 12


class VisitInfoError(ValueError):
    """Админка прислала то, что карточка не сможет показать."""


def _text(value: Any, *, limit: int = _TEXT_MAX) -> str:
    out = " ".join(str(value or "").split())
    if len(out) > limit:
        raise VisitInfoError(f"слишком длинный текст: {out[:40]}…")
    return out


def _opt_int(value: Any, *, lo: int, hi: int, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise VisitInfoError(f"{field}: нужно число") from exc
    if not lo <= n <= hi:
        raise VisitInfoError(f"{field}: от {lo} до {hi}")
    return n


def _opt_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _choice(value: Any, allowed: tuple[str, ...], *, field: str) -> str | None:
    if value in (None, ""):
        return None
    if value not in allowed:
        raise VisitInfoError(f"{field}: неизвестное значение {value!r}")
    return str(value)


def _hhmm(value: Any, *, field: str) -> str | None:
    raw = _text(value, limit=5)
    if not raw:
        return None
    if not _HHMM.match(raw):
        raise VisitInfoError(f"{field}: время в виде 12:30")
    return raw.zfill(5)


def _rows(value: Any, *, field: str) -> list[Mapping[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise VisitInfoError(f"{field}: нужен список")
    if len(value) > _ROWS_MAX:
        raise VisitInfoError(f"{field}: не больше {_ROWS_MAX} строк")
    return [row for row in value if isinstance(row, Mapping)]


def normalize_visit_info(raw: Any) -> dict[str, Any]:
    """Проверка и чистка того, что сохраняет админка. Пустое выбрасывается."""
    if raw in (None, ""):
        return {}
    if not isinstance(raw, Mapping):
        raise VisitInfoError("visit_info: нужен объект")
    out: dict[str, Any] = {}

    t = raw.get("tickets") if isinstance(raw.get("tickets"), Mapping) else {}
    tickets = {
        "mode": _choice(t.get("mode"), TICKET_MODES, field="tickets.mode"),
        "open": _hhmm(t.get("open"), field="tickets.open"),
        "close": _hhmm(t.get("close"), field="tickets.close"),
        "presale_days": _opt_int(t.get("presale_days"), lo=0, hi=60, field="tickets.presale_days"),
        "card": _opt_bool(t.get("card")),
        "cash": _opt_bool(t.get("cash")),
        "desk_only_services": _opt_bool(t.get("desk_only_services")),
        "note": _text(t.get("note")),
    }
    tickets = {k: v for k, v in tickets.items() if v not in (None, "")}
    if tickets:
        out["tickets"] = tickets

    child_age = _opt_int(raw.get("child_age_max"), lo=1, hi=18, field="child_age_max")
    if child_age is not None:
        out["child_age_max"] = child_age

    f = raw.get("facts") if isinstance(raw.get("facts"), Mapping) else {}
    facts: dict[str, Any] = {}
    for key, *_ in _FACTS:
        item = f.get(key) if isinstance(f.get(key), Mapping) else {}
        state = _choice(item.get("state"), FACT_STATES, field=f"facts.{key}")
        if state:
            facts[key] = {"state": state, "note": _text(item.get("note"))}
    warmth = f.get("warmth") if isinstance(f.get("warmth"), Mapping) else {}
    w_state = _choice(warmth.get("state"), WARMTH_STATES, field="facts.warmth")
    if w_state:
        facts["warmth"] = {"state": w_state, "note": _text(warmth.get("note"))}
    spectators = f.get("spectators") if isinstance(f.get("spectators"), Mapping) else {}
    s_state = _choice(spectators.get("state"), FACT_STATES, field="facts.spectators")
    if s_state:
        facts["spectators"] = {
            "state": s_state,
            "price": _text(spectators.get("price"), limit=40),
            "note": _text(spectators.get("note")),
        }
    if facts:
        out["facts"] = facts

    custom = []
    for row in _rows(raw.get("custom_facts"), field="custom_facts"):
        title = _text(row.get("title"), limit=60)
        if not title:
            continue
        icon = row.get("icon") if row.get("icon") in FACT_ICONS else "info"
        custom.append({"icon": icon, "title": title, "note": _text(row.get("note"))})
    if custom:
        out["custom_facts"] = custom

    services = []
    for row in _rows(raw.get("services"), field="services"):
        kind = _choice(row.get("kind") or "other", SERVICE_KINDS, field="services.kind") or "other"
        label = _text(row.get("label"), limit=60)
        if kind == "other" and not label:
            continue
        services.append(
            {
                "kind": kind,
                "label": label,
                "price": _text(row.get("price"), limit=40),
                "note": _text(row.get("note")),
            }
        )
    if services:
        out["services"] = services

    r = raw.get("rental") if isinstance(raw.get("rental"), Mapping) else {}
    rental = {"sizes": _text(r.get("sizes"), limit=20), "deposit": _text(r.get("deposit"))}
    rental = {k: v for k, v in rental.items() if v}
    if rental:
        out["rental"] = rental

    s = raw.get("school") if isinstance(raw.get("school"), Mapping) else {}
    school_rows = [
        {"label": _text(row.get("label"), limit=60), "child": _text(row.get("child"), limit=40),
         "adult": _text(row.get("adult"), limit=40)}
        for row in _rows(s.get("rows"), field="school.rows")
        if _text(row.get("label"), limit=60)
    ]
    school = {
        "age_from": _opt_int(s.get("age_from"), lo=1, hi=18, field="school.age_from"),
        "phone": _text(s.get("phone"), limit=40),
        "contact": _text(s.get("contact"), limit=60),
        "rows": school_rows,
    }
    school = {k: v for k, v in school.items() if v not in (None, "", [])}
    if school:
        out["school"] = school

    p = raw.get("passes") if isinstance(raw.get("passes"), Mapping) else {}
    cols = [_text(c, limit=30) for c in (p.get("columns") or [])[:3] if _text(c, limit=30)]
    pass_rows = []
    for row in _rows(p.get("rows"), field="passes.rows"):
        label = _text(row.get("label"), limit=40)
        values = [_text(v, limit=30) for v in (row.get("values") or [])[: len(cols) or 3]]
        if label and any(values):
            pass_rows.append({"label": label, "values": values})
    if pass_rows:
        out["passes"] = {"columns": cols or ["Цена"], "rows": pass_rows}

    rr = raw.get("rink_rental") if isinstance(raw.get("rink_rental"), Mapping) else {}
    rink_rows = []
    for row in _rows(rr.get("rows"), field="rink_rental.rows"):
        label = _text(row.get("label"), limit=60)
        price = _text(row.get("price"), limit=40)
        if label and price:
            minutes = _opt_int(row.get("minutes"), lo=10, hi=600, field="rink_rental.minutes")
            rink_rows.append({"label": label, "minutes": minutes, "price": price})
    if rink_rows:
        rink: dict[str, Any] = {"rows": rink_rows}
        phone = _text(rr.get("phone"), limit=40)
        if phone:
            rink["phone"] = phone
        out["rink_rental"] = rink

    return out


# ── Модель для показа ────────────────────────────────────────────────────


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sentence(text: str) -> str:
    body = str(text or "").strip().rstrip(".;")
    if not body:
        return ""
    return body[0].upper() + body[1:] + "."


def _tickets_view(card: Mapping[str, Any], visit: Mapping[str, Any], hours: Mapping[str, Any]) -> dict[str, Any]:
    """Строка покупки под тремя ценами и подпись к кнопке в шапке блока."""
    t = _mapping(visit.get("tickets"))
    mode = t.get("mode")
    has_url = bool(str(card.get("tickets_url") or "").strip())
    legacy_note = str(hours.get("ticket_note") or "").strip()
    if mode is None:
        if has_url:
            mode = "online"
        elif legacy_note:
            mode = "box_office"
        elif card.get("schedule_mode") == "phone":
            mode = "phone"
    if mode in ("online", "same_day") and not has_url:
        mode = "box_office"
    kassa = _mapping(hours.get("kassa"))
    open_ = t.get("open") or kassa.get("open")
    close = t.get("close") or kassa.get("close")
    pay = [label for key, label in (("card", "карта"), ("cash", "наличные")) if t.get(key) is True]
    only = [label for key, label in (("card", "только карта"), ("cash", "только наличные")) if t.get(key) is True]
    if t.get("card") is True and t.get("cash") is False:
        pay = [only[0]]
    elif t.get("cash") is True and t.get("card") is False:
        pay = ["только наличные"]
    bits: list[str] = []
    if open_ and close:
        bits.append(f"касса {open_}–{close}")
    presale = t.get("presale_days")
    if presale:
        bits.append(f"продают за {presale} {_days_word(int(presale))}")
    if pay:
        bits.append(", ".join(pay))
    note = str(t.get("note") or "").strip() or (legacy_note if mode == "box_office" and not bits else "")
    return {
        "mode": mode,
        "detail": " · ".join(bits),
        "note": _sentence(note) if note else "",
        "desk_only_services": t.get("desk_only_services") is True,
    }


def _days_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def _facts_view(card: Mapping[str, Any], visit: Mapping[str, Any]) -> list[dict[str, Any]]:
    facts = _mapping(visit.get("facts"))
    amenities = _mapping(card.get("amenities"))
    out: list[dict[str, Any]] = []
    for key, icon, yes, no in _FACTS:
        item = _mapping(facts.get(key))
        state = item.get("state")
        if state is None and amenities.get(key) is True:
            state = "yes"
        if state == "yes":
            title = "Кафе" if key == "cafe" else yes
            out.append({"key": key, "icon": icon, "title": title, "note": str(item.get("note") or "")})
        elif state == "no":
            out.append({"key": key, "icon": icon, "title": no, "note": str(item.get("note") or "")})
    warmth = _mapping(facts.get("warmth"))
    if warmth.get("state") in _WARMTH_TITLES:
        out.append(
            {"key": "warmth", "icon": "thermo", "title": _WARMTH_TITLES[warmth["state"]],
             "note": str(warmth.get("note") or "")}
        )
    t = _mapping(visit.get("tickets"))
    if t.get("card") is True or t.get("cash") is True:
        if t.get("card") is True and t.get("cash") is True:
            title = "Карта и наличные"
        elif t.get("card") is True:
            title = "Только карта" if t.get("cash") is False else "Можно картой"
        else:
            title = "Только наличные" if t.get("card") is False else "Наличными"
        out.append({"key": "payment", "icon": "card", "title": title, "note": "оплата в кассе"})
    age = visit.get("child_age_max")
    if age:
        out.append({"key": "child", "icon": "child", "title": f"Детский билет до {age} лет", "note": ""})
    spectators = _mapping(facts.get("spectators"))
    if spectators.get("state") == "yes":
        price = str(spectators.get("price") or "").strip()
        title = f"Трибуна — {price}" if price else "Можно смотреть с трибуны"
        out.append({"key": "spectators", "icon": "eye", "title": title,
                    "note": str(spectators.get("note") or "") or "пока дети на льду"})
    sizes = str(_mapping(visit.get("rental")).get("sizes") or "").strip()
    if sizes:
        out.append({"key": "sizes", "icon": "ruler", "title": f"Коньки {sizes}", "note": "размеры проката"})
    age_from = _mapping(visit.get("school")).get("age_from")
    if age_from:
        out.append({"key": "school", "icon": "child", "title": f"Учат с {age_from} лет", "note": "занятия от катка"})
    for row in visit.get("custom_facts") or []:
        out.append({"key": "custom", "icon": row.get("icon") or "info", "title": row["title"],
                    "note": row.get("note") or ""})
    return out


def _services_view(card: Mapping[str, Any], visit: Mapping[str, Any], hours: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in visit.get("services") or []:
        kind = row.get("kind") or "other"
        title = row.get("label") or _SERVICE_TITLES.get(kind, "")
        if not title:
            continue
        rows.append({"kind": kind, "icon": _SERVICE_ICONS[kind], "title": title,
                     "price": row.get("price") or "", "note": row.get("note") or ""})
    if not visit.get("services"):
        # Старый прайс строками «label — price»: показываем как есть, тип не угадываем.
        for row in hours.get("rental_catalog") or []:
            if not isinstance(row, Mapping):
                continue
            label = str(row.get("label") or "").strip()
            price = str(row.get("price") or "").strip()
            per = str(row.get("per") or "").strip()
            if label and price:
                icon = _guess_icon(label)
                kind = next((k for k, v in _SERVICE_ICONS.items() if v == icon and k != "other"), "other")
                rows.append({"kind": kind, "icon": icon, "title": label,
                             "price": f"{price}/{per}" if per else price, "note": ""})
        amenities = _mapping(card.get("amenities"))
        have = {r["icon"] for r in rows}
        for key, kind in (("skate_rental", "rental"), ("skate_sharpening", "sharpening")):
            if amenities.get(key) is True and _SERVICE_ICONS[kind] not in have:
                rows.append({"kind": kind, "icon": _SERVICE_ICONS[kind], "title": _SERVICE_TITLES[kind],
                             "price": "", "note": "цена в кассе"})
    rows.sort(key=lambda r: _SERVICE_ORDER.get(r["kind"], 99))
    rental = _mapping(visit.get("rental"))
    notes: list[str] = []
    if rental.get("deposit"):
        notes.append(_sentence(f"Коньки выдают под залог: {rental['deposit']}"))
    legacy = str(hours.get("rental_note") or "").strip()
    if legacy and not visit.get("services"):
        notes.append(_sentence(legacy))
    t = _mapping(visit.get("tickets"))
    if t.get("desk_only_services") is True:
        notes.insert(0, "Прокат и заточку оплачивают только в кассе перед сеансом.")
    return {"rows": rows, "notes": notes}


def _guess_icon(label: str) -> str:
    low = label.casefold()
    for needle, icon in (("заточ", "sharpen"), ("пингв", "penguin"), ("опор", "penguin"), ("шлем", "helmet"),
                         ("защит", "shield"), ("конь", "skate"), ("прокат", "skate")):
        if needle in low:
            return icon
    return "info"


def _more_view(visit: Mapping[str, Any], *, has_trainers: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    school = _mapping(visit.get("school"))
    if school.get("rows") and not has_trainers:
        out.append({"key": "school", "icon": "child", "title": "Научиться кататься",
                    "note": _school_line(school), "detail": school})
    passes = _mapping(visit.get("passes"))
    if passes.get("rows"):
        out.append({"key": "passes", "icon": "pass", "title": "Абонементы",
                    "note": _from_price_line(passes), "detail": passes})
    rink = _mapping(visit.get("rink_rental"))
    if rink.get("rows"):
        cheapest = rink["rows"][0]
        mins = cheapest.get("minutes")
        tail = f" за {mins} минут" if mins and mins != 60 else " за час" if mins == 60 else ""
        prefix = "от " if len(rink["rows"]) > 1 else ""
        out.append({"key": "rink", "icon": "rink", "title": "Снять лёд целиком",
                    "note": f"{prefix}{cheapest['price']}{tail}", "detail": rink})
    return out


def _school_line(school: Mapping[str, Any]) -> str:
    bits = []
    if school.get("age_from"):
        bits.append(f"с {school['age_from']} лет")
    first = (school.get("rows") or [{}])[0]
    price = first.get("child") or first.get("adult")
    if first.get("label") and price:
        bits.append(f"{first['label'].lower()} от {price}")
    return " · ".join(bits)


def _from_price_line(passes: Mapping[str, Any]) -> str:
    first = passes["rows"][0]
    values = [v for v in first.get("values") or [] if v]
    if not values:
        return ""
    label = str(first["label"])
    if label.isdigit():
        n = int(label)
        word = "катание" if n % 10 == 1 and n % 100 != 11 else (
            "катания" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "катаний"
        )
        return f"от {min(values, key=_price_key)} за {n} {word}"
    return f"{label} — {values[0]}"


def _price_key(text: str) -> float:
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    return float(m.group(0).replace(",", ".")) if m else 1e9


def visit_view(card: Mapping[str, Any], *, has_trainers: bool = False) -> dict[str, Any]:
    """Всё, что блоки 2–7 показывают сверх расписания. Пустые части — пустые списки."""
    visit = _mapping(card.get("visit_info"))
    hours = _mapping(card.get("opening_hours"))
    school = _mapping(visit.get("school"))
    return {
        "blocks": list(PLACE_BLOCKS),
        "tickets": _tickets_view(card, visit, hours),
        "child_age_max": visit.get("child_age_max"),
        "sizes": str(_mapping(visit.get("rental")).get("sizes") or ""),
        "facts": _facts_view(card, visit),
        "facts_visible": FACTS_VISIBLE,
        "services": _services_view(card, visit, hours),
        "school": dict(school) if school.get("rows") and has_trainers else None,
        "more": _more_view(visit, has_trainers=has_trainers),
    }
