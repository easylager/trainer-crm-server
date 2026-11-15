#!/usr/bin/env python3
"""Разбор ручной выгрузки Search Console («Эффективность») для /c/minsk (TASK-420).

Выгрузка — zip или папка с CSV: Диаграмма, Запросы, Страницы, Устройства, Фильтры.
Недостающие файлы и столбцы не ломают отчёт: раздел просто пишет «нет данных».

    python3 scripts/gsc_minsk_report.py ~/Downloads/glideclub.by-Performance.zip
    python3 scripts/gsc_minsk_report.py <zip|папка> --save            # + строка недели в историю
    python3 scripts/gsc_minsk_report.py <zip|папка> --save --history other.csv --date 2026-11-23
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

# Отслеживаемые запросы — править здесь. Сравнение без регистра.
TRACKED_QUERIES = [
    "массовые катания минск",
    "массовое катание минск",
    "каток минск",
    "катки минск",
    "расписание массового катания",
    "минск арена расписание массового катания",
    "охм чижовка",
    "охм даймонд",
]
FOCUS_WORD = "минск"
DEFAULT_HISTORY = ".ai/seo/minsk-weekly.csv"
REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY_FIELDS = [
    "export_date", "period_start", "period_end", "clicks", "impressions",
    "tracked_avg_position", "minsk_query_impressions", "position_mobile", "position_desktop",
]
MOBILE = ("мобиль", "mobile")
DESKTOP = ("пк", "компьют", "desktop")

Row = dict[str, str]


def _norm(text: str) -> str:
    """Нормализация имён и заголовков: NFC, латинская K/A... из выгрузки → кириллица, регистр."""
    text = unicodedata.normalize("NFC", text or "").strip().casefold().lstrip("﻿")
    return text.translate(str.maketrans("kaecopxy", "каесорху"))


def to_number(raw: Any) -> float | None:
    """«33.33%», «1 234», «6,24», «» → число или None."""
    if raw is None:
        return None
    s = str(raw).replace(" ", "").replace(" ", "").replace("%", "").replace(",", ".").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_csv(text: str) -> list[Row]:
    text = text.lstrip("﻿")
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    return [dict(r) for r in csv.DictReader(io.StringIO(text), delimiter=delim)]


def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if not info.flag_bits & 0x800:  # имя не помечено utf-8: Python прочитал его как cp437
        try:
            name = name.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return Path(name).stem


def load_export(source: Path) -> dict[str, list[Row]]:
    """Ключ — нормализованное имя файла без расширения («диаграмма», «запросы»…)."""
    out: dict[str, list[Row]] = {}
    if source.is_dir():
        for p in sorted(source.glob("*.csv")):
            out[_norm(p.stem)] = _parse_csv(p.read_text(encoding="utf-8-sig"))
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as z:
            for info in z.infolist():
                if info.filename.lower().endswith(".csv"):
                    out[_norm(_fix_zip_name(info))] = _parse_csv(z.read(info).decode("utf-8-sig"))
    else:
        raise SystemExit(f"Не zip и не папка: {source}")
    return out


def _col(row: Row, *prefixes: str) -> str | None:
    """Значение столбца по началу нормализованного заголовка (устойчиво к «Kлики» с латинской K)."""
    for key, value in row.items():
        k = _norm(key)
        if any(k.startswith(p) for p in prefixes):
            return value
    return None


def _first_col(row: Row) -> str:
    return next(iter(row.values()), "") or ""


def _metrics(row: Row) -> dict[str, float | None]:
    return {
        "clicks": to_number(_col(row, "клик")),
        "impressions": to_number(_col(row, "показ")),
        "position": to_number(_col(row, "позиц")),
    }


def summary(data: dict[str, list[Row]]) -> dict[str, Any]:
    chart = data.get("диаграмма") or []
    dates = sorted(d for d in ((_col(r, "дата") or "").strip() for r in chart) if re.match(r"\d{4}-\d{2}-\d{2}$", d))
    clicks = sum(m["clicks"] or 0 for m in map(_metrics, chart)) if chart else None
    imps = sum(m["impressions"] or 0 for m in map(_metrics, chart)) if chart else None
    if not chart:  # без диаграммы — суммы по страницам, потом по запросам
        for key in ("страницы", "запросы"):
            rows = data.get(key) or []
            if rows:
                ms = list(map(_metrics, rows))
                clicks, imps = sum(m["clicks"] or 0 for m in ms), sum(m["impressions"] or 0 for m in ms)
                break
    filters = {_norm(_first_col(r)): (list(r.values())[1] if len(r) > 1 else "") for r in data.get("фильтры") or []}
    return {
        "start": dates[0] if dates else None,
        "end": dates[-1] if dates else None,
        "period_label": filters.get("дата"),
        "page_filter": filters.get("страница"),
        "clicks": clicks,
        "impressions": imps,
    }


def queries(data: dict[str, list[Row]]) -> list[dict[str, Any]]:
    out = []
    for r in data.get("запросы") or []:
        q = _first_col(r).strip()
        if q:
            out.append({"query": q, **_metrics(r)})
    return out


def minsk_queries(qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [q for q in qs if FOCUS_WORD in q["query"].casefold()]
    return sorted(rows, key=lambda q: -(q["impressions"] or 0))


def tracked(qs: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any] | None]]:
    by_q = {q["query"].casefold(): q for q in qs}
    return [(t, by_q.get(t.casefold())) for t in TRACKED_QUERIES]


def tracked_avg_position(rows: list[tuple[str, dict[str, Any] | None]]) -> float | None:
    """Средняя позиция по отслеживаемым запросам с показами, взвешенная показами."""
    pairs = [(m["position"], m["impressions"]) for _, m in rows if m and m["impressions"] and m["position"]]
    total = sum(w for _, w in pairs)
    return sum(p * w for p, w in pairs) / total if total else None


def device_positions(data: dict[str, list[Row]]) -> dict[str, float | None]:
    res: dict[str, float | None] = {"mobile": None, "desktop": None}
    for r in data.get("устройства") or []:
        name = _norm(_first_col(r))
        pos = _metrics(r)["position"]
        if name.startswith(MOBILE):
            res["mobile"] = pos
        elif name.startswith(DESKTOP):
            res["desktop"] = pos
    return res


def _fmt(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    return str(int(v)) if float(v).is_integer() and digits == 0 else f"{v:.{digits}f}".rstrip("0").rstrip(".")


def build_history_row(data: dict[str, list[Row]], export_date: str) -> dict[str, str]:
    s = summary(data)
    qs = queries(data)
    mq = minsk_queries(qs)
    dev = device_positions(data)
    avg = tracked_avg_position(tracked(qs))
    return {
        "export_date": export_date,
        "period_start": s["start"] or "",
        "period_end": s["end"] or "",
        "clicks": _fmt(s["clicks"], 0) if s["clicks"] is not None else "",
        "impressions": _fmt(s["impressions"], 0) if s["impressions"] is not None else "",
        "tracked_avg_position": f"{avg:.1f}" if avg is not None else "",
        "minsk_query_impressions": _fmt(sum(q["impressions"] or 0 for q in mq), 0) if qs else "",
        "position_mobile": f"{dev['mobile']:.1f}" if dev["mobile"] is not None else "",
        "position_desktop": f"{dev['desktop']:.1f}" if dev["desktop"] is not None else "",
    }


def save_history(path: Path, row: dict[str, str]) -> str:
    """Одна строка на дату выгрузки: та же дата — обновить, иначе дописать. Остальные строки не трогаем."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            rows = [dict(r) for r in csv.DictReader(f)]
    action = "added"
    for i, old in enumerate(rows):
        if old.get("export_date") == row["export_date"]:
            rows[i], action = row, "updated"
            break
    else:
        rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in HISTORY_FIELDS})
    return action


def render(data: dict[str, list[Row]]) -> str:
    s = summary(data)
    qs = queries(data)
    out: list[str] = []
    out.append("== Сводка ==")
    period = f"{s['start']} .. {s['end']}" if s["start"] else (s["period_label"] or "нет данных")
    out.append(f"Период: {period}" + (f"  ({s['period_label']})" if s["start"] and s["period_label"] else ""))
    if s["page_filter"]:
        out.append(f"Страница: {s['page_filter']}")
    out.append(f"Клики: {_fmt(s['clicks'], 0)}   Показы: {_fmt(s['impressions'], 0)}")

    out.append(f"\n== Запросы со словом «{FOCUS_WORD}» (показы, позиция, клики) ==")
    mq = minsk_queries(qs)
    if mq:
        for q in mq:
            out.append(f"{_fmt(q['impressions'], 0):>7}  {_fmt(q['position'], 1):>6}  {_fmt(q['clicks'], 0):>4}  {q['query']}")
    else:
        out.append("нет данных" if not qs else "нет таких запросов")

    out.append("\n== Устройства ==")
    devices = data.get("устройства") or []
    for r in devices:
        m = _metrics(r)
        out.append(f"{_first_col(r):<10} показы {_fmt(m['impressions'], 0):>6}  позиция {_fmt(m['position'], 1):>6}  клики {_fmt(m['clicks'], 0)}")
    if not devices:
        out.append("нет данных")

    out.append("\n== Отслеживаемые запросы ==")
    rows = tracked(qs)
    for t, m in rows:
        if m and m["impressions"]:
            out.append(f"{t:<46} показы {_fmt(m['impressions'], 0):>5}  позиция {_fmt(m['position'], 1)}")
        else:
            out.append(f"{t:<46} нет показов")
    avg = tracked_avg_position(rows)
    out.append(f"Средняя позиция (по показам): {_fmt(avg, 1)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="zip или папка с выгрузкой Search Console")
    ap.add_argument("--save", action="store_true", help="дописать/обновить строку недели в историю")
    ap.add_argument("--history", type=Path, default=REPO_ROOT / DEFAULT_HISTORY, help=f"CSV истории (по умолчанию <корень репо>/{DEFAULT_HISTORY})")
    ap.add_argument("--date", default=None, help="дата выгрузки YYYY-MM-DD (по умолчанию сегодня)")
    args = ap.parse_args(argv)

    data = load_export(args.source)
    if not data:
        print("В выгрузке нет CSV", file=sys.stderr)
        return 1
    print(render(data))
    if args.save:
        row = build_history_row(data, args.date or date.today().isoformat())
        action = save_history(args.history, row)
        print(f"\nИстория: {action} строка {row['export_date']} -> {args.history}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
