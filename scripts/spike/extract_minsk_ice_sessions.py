#!/usr/bin/env python3
"""Extract Minsk rink schedules into unified ice_sessions-shaped JSON.

Read-only spike — no DB writes. Run from repo root:

  python scripts/spike/extract_minsk_ice_sessions.py
  python scripts/spike/extract_minsk_ice_sessions.py --stdout
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
from http_fetch import fetch_html as fetch_http  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "data/minsk-ice-sessions.json"
OUT_CSV = ROOT / "data/minsk-ice-sessions.csv"
PROD_CSV = ROOT / "data/minsk-arenas-prod.csv"
TZ = ZoneInfo("Europe/Minsk")
CURRENCY = "BYN"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


@dataclass
class PriceItem:
    label: str
    amount_minor: int
    currency_code: str = CURRENCY
    duration_minutes: int | None = None
    day_type: str | None = None


@dataclass
class IceSessionRow:
    arena_id: int
    kind: str
    local_date: str
    starts_at_local: str
    ends_at_local: str | None
    starts_at_utc: str
    ends_at_utc: str | None
    duration_minutes: int | None
    price_minor: int | None
    currency_code: str
    price_note: str | None
    session_label: str | None
    age_note: str | None
    source_url: str
    status: str = "active"
    confidence: str = "high"


@dataclass
class ArenaExport:
    arena_id: int
    arena_name: str
    source_urls: list[str]
    extractor: str
    extract_status: str
    extract_notes: str = ""
    price_catalog: list[PriceItem] = field(default_factory=list)
    sessions: list[IceSessionRow] = field(default_factory=list)


def byn_to_minor(amount: float) -> int:
    return int(round(amount * 100))


def fetch_html(url: str, timeout: float = 25.0, try_geo_bypass: bool = False) -> str:
    result = fetch_http(url, timeout=timeout, try_geo_bypass=try_geo_bypass)
    if not result.ok or not result.body:
        raise RuntimeError(f"fetch failed for {url}: status={result.http_status} err={result.error}")
    return result.body


def parse_chizhovka_prices(html: str) -> list[PriceItem]:
    text = strip_html(html).upper()
    catalog: list[PriceItem] = []
    m_adult = re.search(r"ВЗРОСЛЫЙ БИЛЕТ.*?1 ЧАС.*?(\d{1,2})", text)
    m_child = re.search(r"ДЕТСКИЙ БИЛЕТ.*?1 ЧАС.*?(\d{1,2})", text)
    m_rental = re.search(r"ОДНА ПАРА КОНЬКОВ.*?1 СЕАНС.*?(\d{1,2})", text)
    if m_adult:
        catalog.append(PriceItem("взрослый, 1 час", byn_to_minor(float(m_adult.group(1))), duration_minutes=60, day_type="any"))
    if m_child:
        catalog.append(PriceItem("детский до 16, 1 час", byn_to_minor(float(m_child.group(1))), duration_minutes=60, day_type="any"))
    if m_rental:
        catalog.append(PriceItem("прокат коньков", byn_to_minor(float(m_rental.group(1))), duration_minutes=60, day_type="any"))
    return catalog


def parse_diamond_price_images(html: str) -> list[str]:
    imgs = re.findall(
        r"""<img[^>]+src=["']([^"']*(?:/cena|/price|cen[a-z_]*|preisk)[^"']*\.(?:png|jpg|jpeg|webp))["']""",
        html,
        re.I,
    )
    out: list[str] = []
    for u in imgs:
        out.append(u if u.startswith("http") else f"https://diamondcity.by{u}")
    return out


def strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ").replace("&#8212;", "—")
    return re.sub(r"\s+", " ", text).strip()


def parse_ru_date(day: int, month_word: str, year: int) -> date:
    month = MONTHS_RU[month_word.lower()]
    return date(year, month, day)


def local_session_times(
    arena_id: int,
    local_d: date,
    start_hm: str,
    end_hm: str | None,
    duration_minutes: int | None,
    *,
    kind: str = "public_skate",
    source_url: str,
    session_label: str | None = None,
    price_minor: int | None = None,
    price_note: str | None = None,
    confidence: str = "high",
) -> IceSessionRow:
    sh, sm = map(int, start_hm.split(":"))
    start_local = datetime(local_d.year, local_d.month, local_d.day, sh, sm, tzinfo=TZ)
    if end_hm:
        eh, em = map(int, end_hm.split(":"))
        end_local = datetime(local_d.year, local_d.month, local_d.day, eh, em, tzinfo=TZ)
        if end_local <= start_local:
            end_local += timedelta(days=1)
        duration = int((end_local - start_local).total_seconds() // 60)
    elif duration_minutes:
        end_local = start_local + timedelta(minutes=duration_minutes)
        duration = duration_minutes
    else:
        end_local = None
        duration = None

    return IceSessionRow(
        arena_id=arena_id,
        kind=kind,
        local_date=local_d.isoformat(),
        starts_at_local=start_hm,
        ends_at_local=end_hm or (end_local.strftime("%H:%M") if end_local else None),
        starts_at_utc=start_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ends_at_utc=end_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ") if end_local else None,
        duration_minutes=duration,
        price_minor=price_minor,
        currency_code=CURRENCY,
        price_note=price_note,
        session_label=session_label,
        age_note=None,
        source_url=source_url,
        confidence=confidence,
    )


def extract_zamok() -> ArenaExport:
    url = "https://tczamok.by/entertainments/ice-rink"
    html = fetch_html(url)
    text = strip_html(html)

    pairs = re.findall(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", text)
    # Stable daily grid — unique start times in order
    seen: set[str] = set()
    slots: list[tuple[str, str]] = []
    for start, end in pairs:
        if start not in seen and start.endswith(":15"):
            seen.add(start)
            slots.append((start, end))

    price_catalog = [
        PriceItem("взрослый, будни", byn_to_minor(10.0), duration_minutes=45, day_type="weekday"),
        PriceItem("взрослый, выходные", byn_to_minor(11.0), duration_minutes=45, day_type="weekend"),
        PriceItem("детский 3–14, будни", byn_to_minor(8.0), duration_minutes=45, day_type="weekday"),
        PriceItem("детский 3–14, выходные", byn_to_minor(9.0), duration_minutes=45, day_type="weekend"),
        PriceItem("прокат коньков", byn_to_minor(9.0), duration_minutes=None, day_type="any"),
    ]

    today = date.today()
    sessions: list[IceSessionRow] = []
    for offset in range(7):
        d = today + timedelta(days=offset)
        is_weekend = d.weekday() >= 5
        price_note = "взр. 10 / дет. 8 BYN" if not is_weekend else "взр. 11 / дет. 9 BYN"
        price_minor = byn_to_minor(8.0 if not is_weekend else 9.0)
        for start, end in slots:
            sessions.append(
                local_session_times(
                    3,
                    d,
                    start,
                    end,
                    None,
                    source_url=url,
                    price_minor=price_minor,
                    price_note=price_note,
                    confidence="high",
                )
            )

    return ArenaExport(
        arena_id=3,
        arena_name="ТЦ Замок",
        source_urls=[url],
        extractor="zamok_html_v1",
        extract_status="ok" if sessions else "failed",
        extract_notes="Стабильная сетка :15; материализация на 7 дней от даты прогона",
        price_catalog=price_catalog,
        sessions=sessions,
    )


def extract_ledby() -> ArenaExport:
    schedule_url = "http://led.by/category/timetable/"
    price_url = "http://led.by/mass_skating/"
    html = fetch_html(schedule_url)
    text = strip_html(html)

    # Two weekly blocks; times after a day marker inherit that date until the next marker.
    mk_chunks = re.findall(r"МАССОВОЕ КАТАНИЕ(.+?)(?:Далее|ОТРАБОТКА|$)", text, flags=re.I)
    day_re = re.compile(r"(?:Пн|Вт|Ср|Чт|Пт|Сб|Вс)\.(\d{2}\.\d{2}\.\d{4})")
    time_re = re.compile(r"(\d{1,2}:\d{2})\s*\((\d+)\s*час")

    sessions: list[IceSessionRow] = []
    seen: set[tuple[str, str]] = set()
    for chunk in mk_chunks:
        day_marks = [(m.start(), m.group(1)) for m in day_re.finditer(chunk)]
        for tm in time_re.finditer(chunk):
            date_str = None
            for pos, ds in reversed(day_marks):
                if pos < tm.start():
                    date_str = ds
                    break
            if not date_str:
                continue
            time_s, hours_s = tm.group(1), tm.group(2)
            key = (date_str, time_s)
            if key in seen:
                continue
            seen.add(key)
            d = datetime.strptime(date_str, "%d.%m.%Y").date()
            duration = int(hours_s) * 60
            eh, em = map(int, time_s.split(":"))
            end_dt = datetime(d.year, d.month, d.day, eh, em, tzinfo=TZ) + timedelta(minutes=duration)
            sessions.append(
                local_session_times(
                    5,
                    d,
                    time_s,
                    end_dt.strftime("%H:%M"),
                    duration,
                    source_url=schedule_url,
                    confidence="high",
                )
            )

    price_html = fetch_html(price_url)
    price_text = strip_html(price_html)
    price_catalog = [
        PriceItem("взрослый 45 мин, будни", byn_to_minor(7.0), duration_minutes=45, day_type="weekday"),
        PriceItem("детский 45 мин, будни", byn_to_minor(5.0), duration_minutes=45, day_type="weekday"),
        PriceItem("взрослый 45 мин, выходные", byn_to_minor(8.0), duration_minutes=45, day_type="weekend"),
        PriceItem("детский 45 мин, выходные", byn_to_minor(6.0), duration_minutes=45, day_type="weekend"),
        PriceItem("взрослый 60 мин, будни", byn_to_minor(9.0), duration_minutes=60, day_type="weekday"),
        PriceItem("детский 60 мин, будни", byn_to_minor(7.0), duration_minutes=60, day_type="weekday"),
    ]

    for s in sessions:
        s.price_note = "см. price_catalog (45/60/75 мин)"
        s.price_minor = byn_to_minor(5.0)

    status = "ok" if sessions else "failed"
    return ArenaExport(
        arena_id=5,
        arena_name="Ледовый дворец спорта Минской области",
        source_urls=[schedule_url, price_url],
        extractor="ledby_html_v1",
        extract_status=status,
        extract_notes="Расписание с датами; цены с mass_skating (не привязаны к сеансу)",
        price_catalog=price_catalog,
        sessions=sessions,
    )


def extract_chizhovka() -> ArenaExport:
    schedule_url = "https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah"
    price_url = "https://chizhovka-arena.by/czeny/katanie-na-konkah"
    html = fetch_html(schedule_url)
    text = strip_html(html)
    price_catalog = parse_chizhovka_prices(fetch_html(price_url))

    day_re = re.compile(
        r"(Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|Воскресенье)\s+(\d{1,2})\s+(\w+)",
        re.I,
    )
    time_re = re.compile(r"(\d{1,2})[.:](\d{2})\s+(БА|МА)", re.I)

    sessions: list[IceSessionRow] = []
    seen: set[tuple[str, str, str]] = set()
    year = date.today().year
    for m in day_re.finditer(text):
        month_word = m.group(3)
        if month_word.lower() not in MONTHS_RU:
            continue
        local_d = parse_ru_date(int(m.group(2)), month_word, year)
        chunk = text[m.end() : m.end() + 400]
        for tm in time_re.finditer(chunk):
            hh, mm, label = tm.group(1), tm.group(2), tm.group(3).upper()
            start = f"{int(hh):02d}:{mm}"
            key = (local_d.isoformat(), start, label)
            if key in seen:
                continue
            seen.add(key)
            sessions.append(
                local_session_times(
                    6,
                    local_d,
                    start,
                    None,
                    60,
                    source_url=schedule_url,
                    session_label=label,
                    price_minor=price_catalog[0].amount_minor if price_catalog else None,
                    price_note="взр. 10 / дет. 7 BYN" if price_catalog else None,
                    confidence="medium",
                )
            )

    status = "ok" if sessions and price_catalog else ("partial" if sessions else "failed")
    return ArenaExport(
        arena_id=6,
        arena_name="Чижовка-арена",
        source_urls=[schedule_url, price_url],
        extractor="chizhovka_html_v1",
        extract_status=status,
        extract_notes="Расписание МА/БА + цены с /czeny/katanie-na-konkah",
        price_catalog=price_catalog,
        sessions=sessions,
    )


def extract_diamond() -> ArenaExport:
    schedule_url = "https://diamondcity.by/ledovaya-arena"
    price_url = "https://diamondcity.by/ceny"
    html = fetch_html(schedule_url)
    text = strip_html(html)
    price_html = fetch_html(price_url)
    price_images = parse_diamond_price_images(price_html)
    # Official prices published as PNG on /ceny (cena_led_2606.png). OCR not in spike v1.
    price_catalog = [
        PriceItem("взрослый, будни, 45 мин", byn_to_minor(11.0), duration_minutes=45, day_type="weekday"),
        PriceItem("детский, будни, 45 мин", byn_to_minor(8.0), duration_minutes=45, day_type="weekday"),
        PriceItem("взрослый, выходные, 45 мин", byn_to_minor(12.0), duration_minutes=45, day_type="weekend"),
        PriceItem("детский, выходные, 45 мин", byn_to_minor(9.0), duration_minutes=45, day_type="weekend"),
        PriceItem("прокат коньков", byn_to_minor(10.0), duration_minutes=45, day_type="any"),
    ]

    block_re = re.compile(
        r"(Пн|Вт|Ср|Чт|Пт|Сб|Вс),?\s+(\d{1,2})\s+(\w+)(.+?)(?=(?:Пн|Вт|Ср|Чт|Пт|Сб|Вс),?\s+\d{1,2}\s+\w+|$)",
        re.I,
    )
    sess_re = re.compile(r"(МК|ОХМ|ШРС|ТОРНАДО|Тех\.обслуживание)\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", re.I)

    sessions: list[IceSessionRow] = []
    seen: set[tuple[str, str, str]] = set()
    year = date.today().year
    for m in block_re.finditer(text):
        month_word = m.group(3)
        if month_word.lower() not in MONTHS_RU:
            continue
        local_d = parse_ru_date(int(m.group(2)), month_word, year)
        body = m.group(4)
        for label, start, end in sess_re.findall(body):
            label_u = label.upper()
            if "ТЕХ" in label_u:
                continue
            kind = "public_skate" if label_u == "МК" else "open_ice"
            key = (local_d.isoformat(), start, label_u)
            if key in seen:
                continue
            seen.add(key)
            sessions.append(
                local_session_times(
                    7,
                    local_d,
                    start,
                    end,
                    None,
                    kind=kind,
                    source_url=schedule_url,
                    session_label=label_u,
                    price_minor=byn_to_minor(8.0),
                    price_note="см. price_catalog; офиц. PNG: " + (price_images[0] if price_images else price_url),
                    confidence="high" if label_u == "МК" else "medium",
                )
            )

    mk_sessions = [s for s in sessions if s.kind == "public_skate"]
    for s in mk_sessions:
        s.price_note = "взр. 11–12 / дет. 8–9 BYN (45 мин); PNG: " + (price_images[0] if price_images else "diamondcity.by/ceny")

    return ArenaExport(
        arena_id=7,
        arena_name="ТЦ DiaMond city",
        source_urls=[schedule_url, price_url] + price_images[:1],
        extractor="diamond_html_v1",
        extract_status="partial" if mk_sessions and price_images else ("partial" if mk_sessions else "failed"),
        extract_notes="МК расписание HTML; цены — официальный PNG на /ceny (транскрипция вручную, OCR TODO)",
        price_catalog=price_catalog,
        sessions=mk_sessions,
    )


def extract_junost() -> ArenaExport:
    """Origin schedule URL is geo-403. Public weekend grid is reprinted on hockey.by / slivki / bestbelarus."""
    url = "https://junost.hockey.by/clubs/skating/"
    html = fetch_html(url)
    price_catalog = [
        PriceItem("взрослый", byn_to_minor(7.0), duration_minutes=45, day_type="weekend"),
        PriceItem("детский до 16", byn_to_minor(5.5), duration_minutes=45, day_type="weekend"),
        PriceItem("прокат коньков", byn_to_minor(6.0), duration_minutes=45, day_type="any"),
    ]
    slots = [("17:00", "17:45"), ("18:15", "19:00")]
    sessions: list[IceSessionRow] = []
    today = date.today()
    # Next 4 weekend days (Sat+Sun)
    d = today
    weekend_days = 0
    while weekend_days < 4:
        if d.weekday() >= 5:
            for start, end in slots:
                sessions.append(
                    local_session_times(
                        8,
                        d,
                        start,
                        end,
                        45,
                        source_url=url,
                        price_minor=byn_to_minor(5.5),
                        price_note="взр. 7 / дет. 5.50 BYN",
                        confidence="medium",
                    )
                )
            weekend_days += 1
        d += timedelta(days=1)

    return ArenaExport(
        arena_id=8,
        arena_name='Каток хк "Юность"',
        source_urls=[url, "https://junost.by/seansy_massovogo_kataniya_na_vyhodnyh/"],
        extractor="junost_weekend_grid_v1",
        extract_status="partial",
        extract_notes=(
            "junost.by schedule → 403 from non-BY IP. "
            "Stable Sat/Sun 17:00–17:45 + 18:15–19:00 from hockey.by + slivki.by; confidence=medium"
        ),
        price_catalog=price_catalog,
        sessions=sessions,
    )


def extract_minskarena_bycard() -> ArenaExport:
    """Official widget is stale; ByCard/24afisha JSON is the live ticket feed."""
    import json as _json
    from urllib.request import Request, urlopen

    api = "https://abws.bycard.by/api/v3/pages/events/konkobezhnyy-stadion-minsk-arena"
    page = "https://bycard.by/afisha/minsk/katki/5821807"
    req = Request(api, headers={"User-Agent": UA, "Accept": "application/json", "Referer": "https://bycard.by/"})
    with urlopen(req, timeout=20) as resp:
        payload = _json.loads(resp.read().decode("utf-8", errors="replace"))

    perf = payload.get("performance") or {}
    desc = (perf.get("description") or "") + " " + (perf.get("shortDescription") or "")
    desc_text = strip_html(desc)
    rental = None
    m = re.search(r"проката.*?(\d+(?:[.,]\d+)?)\s*руб", desc_text, re.I)
    if m:
        rental = float(m.group(1).replace(",", "."))

    price_catalog = [
        PriceItem("прокат коньков", byn_to_minor(rental or 5.5), duration_minutes=45, day_type="any"),
        PriceItem("прокат «Пингвин»", byn_to_minor(6.0), duration_minutes=45, day_type="any"),
    ]

    sessions: list[IceSessionRow] = []
    calendar = payload.get("calendar") or []
    for item in calendar:
        # Expected live shape once tickets appear; keep parser defensive.
        start_ts = item.get("startTimestamp") or item.get("timestamp")
        if not start_ts:
            continue
        start_local = datetime.fromtimestamp(int(start_ts), TZ)
        duration = int(perf.get("duration") or 45)
        end_local = start_local + timedelta(minutes=duration)
        sessions.append(
            local_session_times(
                2,
                start_local.date(),
                start_local.strftime("%H:%M"),
                end_local.strftime("%H:%M"),
                duration,
                source_url=page,
                price_note="сеанс из ByCard calendar; цена билета когда isSelling=1",
                confidence="high",
            )
        )

    return ArenaExport(
        arena_id=2,
        arena_name="Минск Арена",
        source_urls=[page, api, "https://minskarena.by/services.html"],
        extractor="minskarena_bycard_v1",
        extract_status="partial" if not sessions else "ok",
        extract_notes=(
            f"ByCard API live; calendar empty (isSelling={perf.get('isSelling')}). "
            "Сезон заявлен 2025-11-01…2026-12-31; сеансы появляются в calendar когда открывают продажу."
        ),
        price_catalog=price_catalog,
        sessions=sessions,
    )


def skipped_arena(arena_id: int, name: str, reason: str) -> ArenaExport:
    return ArenaExport(
        arena_id=arena_id,
        arena_name=name,
        source_urls=[],
        extractor="none",
        extract_status="skipped",
        extract_notes=reason,
    )


def load_prod_names() -> dict[int, str]:
    if not PROD_CSV.exists():
        return {}
    out: dict[int, str] = {}
    with PROD_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[int(row["arena_id"])] = row["name"]
    return out


def arena_to_dict(a: ArenaExport) -> dict[str, Any]:
    return {
        "arena_id": a.arena_id,
        "arena_name": a.arena_name,
        "source_urls": a.source_urls,
        "extractor": a.extractor,
        "extract_status": a.extract_status,
        "extract_notes": a.extract_notes,
        "price_catalog": [asdict(p) for p in a.price_catalog],
        "sessions": [asdict(s) for s in a.sessions],
    }


def write_csv(arenas: list[ArenaExport], path: Path) -> None:
    fields = [
        "arena_id",
        "arena_name",
        "kind",
        "local_date",
        "starts_at_local",
        "ends_at_local",
        "duration_minutes",
        "price_minor",
        "currency_code",
        "price_note",
        "session_label",
        "confidence",
        "source_url",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for a in arenas:
            for s in a.sessions:
                w.writerow(
                    {
                        "arena_id": s.arena_id,
                        "arena_name": a.arena_name,
                        "kind": s.kind,
                        "local_date": s.local_date,
                        "starts_at_local": s.starts_at_local,
                        "ends_at_local": s.ends_at_local,
                        "duration_minutes": s.duration_minutes,
                        "price_minor": s.price_minor,
                        "currency_code": s.currency_code,
                        "price_note": s.price_note,
                        "session_label": s.session_label,
                        "confidence": s.confidence,
                        "source_url": s.source_url,
                    }
                )


def run_extract() -> dict[str, Any]:
    prod_names = load_prod_names()
    extractors: list[tuple[int, str, Any]] = [
        (3, "ТЦ Замок", extract_zamok),
        (5, "led.by", extract_ledby),
        (6, "Чижовка-арена", extract_chizhovka),
        (7, "ТЦ DiaMond city", extract_diamond),
        (8, "Юность", extract_junost),
        (2, prod_names.get(2, "Минск Арена"), extract_minskarena_bycard),
        (4, prod_names.get(4, "СДЮШОР"), lambda: skipped_arena(4, prod_names.get(4, "СДЮШОР"), "ledlife.by HTTP 403 from non-BY IP; Google/Wayback see HTML table; need BY egress")),
        (9, prod_names.get(9, "Олимпик-арена"), lambda: skipped_arena(9, prod_names.get(9, "Олимпик-арена"), "нет публичного МК в HTML")),
        (13, prod_names.get(13, "JUSTSKATE"), lambda: skipped_arena(13, prod_names.get(13, "JUSTSKATE"), "training_only")),
        (14, prod_names.get(14, "Финт"), lambda: skipped_arena(14, prod_names.get(14, "Финт"), "training_only")),
        (12, prod_names.get(12, "Лыжероллерная трасса"), lambda: skipped_arena(12, prod_names.get(12, "Лыжероллерная трасса"), "not_ice")),
    ]

    arenas: list[ArenaExport] = []
    for arena_id, label, fn in extractors:
        try:
            arenas.append(fn())
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001 spike
            arenas.append(
                ArenaExport(
                    arena_id=arena_id,
                    arena_name=label,
                    source_urls=[],
                    extractor="error",
                    extract_status="failed",
                    extract_notes=repr(e),
                )
            )

    total_sessions = sum(len(a.sessions) for a in arenas)
    return {
        "schema_version": "1",
        "generated_at": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "timezone": "Europe/Minsk",
        "summary": {
            "arenas_total": len(arenas),
            "arenas_ok": sum(1 for a in arenas if a.extract_status == "ok"),
            "arenas_partial": sum(1 for a in arenas if a.extract_status == "partial"),
            "arenas_skipped": sum(1 for a in arenas if a.extract_status == "skipped"),
            "arenas_failed": sum(1 for a in arenas if a.extract_status == "failed"),
            "sessions_total": total_sessions,
        },
        "arenas": [arena_to_dict(a) for a in sorted(arenas, key=lambda x: x.arena_id)],
    }


def print_summary(payload: dict[str, Any]) -> None:
    s = payload["summary"]
    print(f"arenas: {s['arenas_total']} | sessions: {s['sessions_total']}")
    print(f"  ok={s['arenas_ok']} partial={s['arenas_partial']} skipped={s['arenas_skipped']} failed={s['arenas_failed']}")
    print()
    print(f"{'id':>3}  {'status':<10}  {'sessions':>8}  name")
    print("-" * 60)
    for a in payload["arenas"]:
        print(f"{a['arena_id']:>3}  {a['extract_status']:<10}  {len(a['sessions']):>8}  {a['arena_name']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    payload = run_extract()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    arenas_objs = []
    for a in payload["arenas"]:
        arenas_objs.append(
            ArenaExport(
                arena_id=a["arena_id"],
                arena_name=a["arena_name"],
                source_urls=a["source_urls"],
                extractor=a["extractor"],
                extract_status=a["extract_status"],
                extract_notes=a["extract_notes"],
                price_catalog=[PriceItem(**p) for p in a["price_catalog"]],
                sessions=[IceSessionRow(**s) for s in a["sessions"]],
            )
        )
    write_csv(arenas_objs, OUT_CSV)

    print_summary(payload)
    print(f"\nWrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_CSV.relative_to(ROOT)}")
    if args.stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
