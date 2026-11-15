"""TASK-420: разбор ручной выгрузки Search Console для /c/minsk."""

from __future__ import annotations

import csv
import importlib.util
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "gsc_minsk_report", Path(__file__).resolve().parents[2] / "scripts" / "gsc_minsk_report.py"
)
gsc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gsc)

# Заголовок «Kлики» — с латинской K, как в настоящей выгрузке.
FILES = {
    "Диаграмма.csv": "Дата,Kлики,Показы,CTR,Позиция\n2026-11-01,1,10,10%,5\n2026-11-02,0,20,0%,9\n2026-11-03,0,0,,\n",
    "Запросы.csv": (
        "Популярные запросы,Kлики,Показы,CTR,Позиция\n"
        "Массовые катания Минск,1,10,10%,40\n"
        "каток минск,0,5,0%,\"20,5\"\n"
        "охм даймонд,0,\"1 000\",0%,6.24\n"
        "каток гомель,0,7,0%,3\n"
    ),
    "Устройства.csv": "Устройство,Kлики,Показы,CTR,Позиция\nМобильный,1,20,5%,7.76\nПК,0,10,0%,41.65\nПланшет,0,1,0%,8",
    "Фильтры.csv": "Фильтр,Значение\nДата,За последние 28 дней\nСтраница,https://glideclub.by/c/minsk\n",
}


def _folder(tmp_path: Path, skip: tuple[str, ...] = ()) -> Path:
    d = tmp_path / "export"
    d.mkdir()
    for name, body in FILES.items():
        if name not in skip:
            (d / name).write_text("﻿" + body, encoding="utf-8")
    return d


def test_numbers_with_percent_comma_and_spaces() -> None:
    assert gsc.to_number("33.33%") == 33.33
    assert gsc.to_number("6,24") == 6.24
    assert gsc.to_number("1 000") == 1000
    assert gsc.to_number("") is None and gsc.to_number(None) is None and gsc.to_number("n/a") is None


def test_summary_period_clicks_impressions(tmp_path: Path) -> None:
    s = gsc.summary(gsc.load_export(_folder(tmp_path)))
    assert (s["start"], s["end"]) == ("2026-11-01", "2026-11-03")
    assert (s["clicks"], s["impressions"]) == (1, 30)
    assert s["page_filter"] == "https://glideclub.by/c/minsk"


def test_zip_with_utf8_names_matches_folder(tmp_path: Path) -> None:
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, body in FILES.items():
            zf.writestr(name, body)
    assert gsc.summary(gsc.load_export(z)) == gsc.summary(gsc.load_export(_folder(tmp_path)))


def test_minsk_queries_tracked_and_devices(tmp_path: Path) -> None:
    data = gsc.load_export(_folder(tmp_path))
    qs = gsc.queries(data)
    assert [q["query"] for q in gsc.minsk_queries(qs)] == ["Массовые катания Минск", "каток минск"]
    rows = dict(gsc.tracked(qs))
    assert rows["массовые катания минск"]["impressions"] == 10  # регистр не важен
    assert rows["катки минск"] is None
    assert rows["охм даймонд"]["impressions"] == 1000
    avg = gsc.tracked_avg_position(list(rows.items()))
    assert round(avg, 2) == round((40 * 10 + 20.5 * 5 + 6.24 * 1000) / 1015, 2)
    assert gsc.device_positions(data) == {"mobile": 7.76, "desktop": 41.65}
    text = gsc.render(data)
    assert "катки минск" in text and "нет показов" in text


def test_missing_files_do_not_break(tmp_path: Path) -> None:
    data = gsc.load_export(_folder(tmp_path, skip=("Запросы.csv", "Устройства.csv", "Диаграмма.csv")))
    out = gsc.render(data)
    assert "нет данных" in out
    row = gsc.build_history_row(data, "2026-11-16")
    assert row["tracked_avg_position"] == "" and row["position_mobile"] == "" and row["clicks"] == ""


def test_history_one_row_per_date_and_never_rewrites_others(tmp_path: Path) -> None:
    data = gsc.load_export(_folder(tmp_path))
    hist = tmp_path / "seo" / "minsk-weekly.csv"  # каталога ещё нет
    first = gsc.build_history_row(data, "2026-11-09")
    second = gsc.build_history_row(data, "2026-11-16")
    assert gsc.save_history(hist, first) == "added"
    assert gsc.save_history(hist, second) == "added"
    changed = {**second, "clicks": "99"}
    assert gsc.save_history(hist, changed) == "updated"
    rows = list(csv.DictReader(hist.open(encoding="utf-8")))
    assert [r["export_date"] for r in rows] == ["2026-11-09", "2026-11-16"]
    assert rows[0] == first and rows[1]["clicks"] == "99"
    assert list(rows[0]) == gsc.HISTORY_FIELDS


def test_cli_save(tmp_path: Path, capsys) -> None:
    hist = tmp_path / "h.csv"
    code = gsc.main([str(_folder(tmp_path)), "--save", "--history", str(hist), "--date", "2026-11-16"])
    assert code == 0 and hist.exists()
    assert "Отслеживаемые запросы" in capsys.readouterr().out
