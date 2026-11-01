"""Сверка с таблицей нового сезона (TASK-343, волна 2): дифф и применение пачкой после подтверждения.

Тот же CSV-формат и тот же ``plan_rows``, что у seed 2025/26. Файл ничего не меняет сам:
``create_run`` строит дифф относительно БД и хранит его вместе с исходными строками, а
``apply_run`` применяет выбранные части по кнопке админа.

Части диффа:
* ``new`` — точек нет в БД: создаём ожидающими подтверждения сезона (без публикации);
* ``changed`` — часы / телефон отличаются (плюс «сверено»: часы совпали -> подпись «часы 2026/27»);
* ``missing`` — точка из прошлой таблицы пропала: после подтверждения скрывается («Нет в списке 2026/27»),
  точки с живым «залит» или подтверждённые админом за 30 дней не трогаем;
* ``same`` — пара «пропала + новая» с тем же местом (переименование школы, смена адреса): это одна
  точка, обновляем ключ, адрес, часы. Такие пары не попадают ни в ``new``, ни в ``missing``.

Защита (T6): неизвестная структура файла, пустой разбор или пропало больше 30% точек затронутых
городов -> запуск ``failed``, ничего не применяется. Частичный файл (один город) не «закрывает»
остальные города.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import winter_admin as wa
from src.application.winter_import import (
    MAP_PRECISIONS,
    PlannedPoint,
    _catalog_arenas,
    _match_catalog,
    haversine_m,
    import_points,
    plan_rows,
)
from src.shared import winter_status as ws

MAX_MISSING_SHARE = 0.30
MIN_BASE_FOR_GUARD = 10
LIST_CAP = 200
SAME_PLACE_RADIUS_M = 150.0
KEEP_SHIELD = timedelta(days=30)
PARTS = ("new", "changed", "missing", "same")
REQUIRED_COLUMNS = ("city",)


class DiffError(Exception):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


def parse_csv(data: bytes) -> list[dict[str, str]]:
    """CSV (запятая или ``;``, UTF-8 с BOM или без) -> строки. Без колонки ``city`` — ``DiffError``."""
    try:
        textual = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DiffError("bad_encoding") from exc
    head = textual.split("\n", 1)[0]
    delimiter = ";" if head.count(";") > head.count(",") else ","
    reader = csv.DictReader(io.StringIO(textual), delimiter=delimiter)
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    if not all(c in fields for c in REQUIRED_COLUMNS) or not ({"address", "name"} & set(fields)):
        raise DiffError("no_columns", ", ".join(fields)[:120])
    rows = []
    for raw in reader:
        rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k})
    return rows


def _norm_hours(value: str | None) -> str:
    return " ".join((value or "").split())[:256]


def _brief(p: PlannedPoint) -> dict[str, Any]:
    return {"key": p.key, "city": p.city, "name": p.name, "address": p.address, "kind": p.kind}


async def _city_id(session: AsyncSession, name: str, cache: dict[str, int | None]) -> int | None:
    if name not in cache:
        row = (
            await session.execute(
                text("SELECT id FROM cities WHERE lower(trim(name)) = lower(trim(:n)) ORDER BY is_active DESC, id LIMIT 1"),
                {"n": name},
            )
        ).first()
        cache[name] = int(row[0]) if row else None
    return cache[name]


async def compute_diff(session: AsyncSession, planned: list[PlannedPoint], season: int) -> dict[str, Any]:
    live = [p for p in planned if p.skip_reason is None]
    file_keys = {p.key for p in live}
    cities_in_file = {p.city.strip().lower() for p in live}
    ex_rows = (
        await session.execute(
            text(
                """SELECT sr.source_key, a.id AS arena_id, a.name, a.address, a.latitude, a.longitude, sr.kind,
                          sr.geocode_precision, lower(c.name) AS city_l, c.name AS city,
                          s.state, s.hours_text, s.phone, s.admin_confirmed_at
                   FROM seasonal_rinks sr
                   JOIN arenas a ON a.id = sr.arena_id AND a.is_active AND a.merged_into_arena_id IS NULL
                   JOIN cities c ON c.id = a.city_id
                   LEFT JOIN seasonal_rink_seasons s ON s.arena_id = a.id AND s.season = :season
                   WHERE sr.source_key IS NOT NULL"""
            ),
            {"season": season},
        )
    ).mappings().all()
    existing = {r["source_key"]: r for r in ex_rows}
    base_in_cities = [r for r in ex_rows if r["city_l"].strip() in cities_in_file and r["state"] != "hidden"]

    new: list[PlannedPoint] = []
    changed: list[dict[str, Any]] = []
    verified: list[int] = []
    skipped_catalog = 0
    city_cache: dict[str, int | None] = {}
    catalog_cache: dict[int, list[dict[str, Any]]] = {}
    for p in live:
        ex = existing.get(p.key)
        if ex is None:
            cid = await _city_id(session, p.city, city_cache)
            if cid is not None:
                arenas = catalog_cache.setdefault(cid, await _catalog_arenas(session, cid))
                if _match_catalog(p, arenas) is not None:
                    skipped_catalog += 1
                    continue
            new.append(p)
            continue
        fields = []
        old_h, new_h = _norm_hours(ex["hours_text"]), _norm_hours(p.hours.raw)
        if new_h and new_h != old_h:
            fields.append("hours")
        if p.phone and p.phone != (ex["phone"] or None):
            fields.append("phone")
        if fields:
            changed.append({
                "key": p.key, "arena_id": int(ex["arena_id"]), "city": ex["city"], "name": ex["name"],
                "fields": fields, "hours_old": old_h or None, "hours_new": new_h or None,
                "phone_old": ex["phone"], "phone_new": p.phone,
            })
        elif new_h and new_h == old_h:
            verified.append(int(ex["arena_id"]))

    missing_rows = [r for r in base_in_cities if r["source_key"] not in file_keys]
    # «Пропала + новая в том же месте» — одна точка: переименование школы, другая запись адреса.
    same: list[dict[str, Any]] = []
    used_new: set[str] = set()
    used_missing: set[int] = set()
    for m in missing_rows:
        for p in new:
            if p.key in used_new or p.city.strip().lower() != m["city_l"].strip() or p.kind != m["kind"]:
                continue
            near = (
                m["geocode_precision"] in MAP_PRECISIONS and p.precision in MAP_PRECISIONS
                and m["latitude"] is not None and p.lat is not None
                and haversine_m(float(m["latitude"]), float(m["longitude"]), p.lat, p.lon) <= SAME_PLACE_RADIUS_M
            )
            same_name = p.name_source == "source" and (m["name"] or "").strip().lower() == p.name.strip().lower()
            if near or same_name:
                same.append({
                    "arena_id": int(m["arena_id"]), "new_key": p.key, "city": m["city"], "name": m["name"],
                    "address_old": m["address"], "address_new": p.address,
                    "hours_new": _norm_hours(p.hours.raw) or None, "phone_new": p.phone,
                })
                used_new.add(p.key)
                used_missing.add(int(m["arena_id"]))
                break
    pure_new = [p for p in new if p.key not in used_new]
    pure_missing = [m for m in missing_rows if int(m["arena_id"]) not in used_missing]
    cap = lambda xs: xs[:LIST_CAP]  # noqa: E731
    return {
        "counts": {
            "file_rows": len(live), "base": len(base_in_cities), "new": len(pure_new), "changed": len(changed),
            "verified": len(verified), "missing": len(pure_missing), "same": len(same),
            "skipped_catalog": skipped_catalog, "skipped_indoor": sum(1 for p in planned if p.skip_reason == "indoor"),
        },
        "new": cap([_brief(p) for p in pure_new]),
        "new_keys": [p.key for p in pure_new],
        "changed": changed,
        "verified": verified,
        "missing": cap([
            {"arena_id": int(m["arena_id"]), "city": m["city"], "name": m["name"], "address": m["address"],
             "state": m["state"]} for m in pure_missing
        ]),
        "missing_ids": [int(m["arena_id"]) for m in pure_missing],
        "same": same,
        "cities": sorted(cities_in_file),
    }


@dataclass
class RunResult:
    run_id: int
    status: str
    duplicate: bool
    diff: dict[str, Any]
    error: str | None = None


def _guard(diff: dict[str, Any]) -> str | None:
    c = diff["counts"]
    if c["file_rows"] == 0:
        return "в файле не нашлось ни одной точки"
    base = c["base"]
    if base >= MIN_BASE_FOR_GUARD and c["missing"] / base > MAX_MISSING_SHARE:
        return f"пропало {c['missing']} из {base} точек (больше 30%): похоже, структура файла изменилась"
    return None


async def create_run(
    session: AsyncSession, rows: list[dict[str, str]], *, season: int, label: str | None, admin_id: int | None,
    now: datetime, file_bytes: bytes | None = None,
) -> RunResult:
    """Построить дифф и сохранить запуск. Тот же файл дважды -> прежний запуск (``duplicate``)."""
    raw = file_bytes if file_bytes is not None else json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    prev = (
        await session.execute(
            text(
                """SELECT id, status, diff, error FROM winter_import_runs
                   WHERE season=:s AND file_sha256=:h AND status IN ('pending', 'applied') ORDER BY id DESC LIMIT 1"""
            ),
            {"s": season, "h": sha},
        )
    ).first()
    if prev is not None:
        return RunResult(int(prev.id), prev.status, True, prev.diff, prev.error)
    planned = plan_rows(rows)
    diff = await compute_diff(session, planned, season)
    error = _guard(diff)
    status = "failed" if error else "pending"
    run_id = int(
        (
            await session.execute(
                text(
                    """INSERT INTO winter_import_runs (season, label, file_sha256, status, error, diff, rows, created_by, created_at)
                       VALUES (:s, :l, :h, :st, :e, CAST(:d AS jsonb), CAST(:r AS jsonb), :by, :n) RETURNING id"""
                ),
                {"s": season, "l": (label or None) and label[:128], "h": sha, "st": status, "e": error,
                 "d": json.dumps(diff, ensure_ascii=False, default=str), "r": json.dumps(rows, ensure_ascii=False),
                 "by": admin_id, "n": now},
            )
        ).scalar_one()
    )
    return RunResult(run_id, status, False, diff, error)


def available_parts(diff: dict[str, Any]) -> list[str]:
    c = diff["counts"]
    out = []
    if c["new"]:
        out.append("new")
    if c["changed"] or c["verified"]:
        out.append("changed")
    if c["missing"]:
        out.append("missing")
    if c["same"]:
        out.append("same")
    return out


async def pending_runs(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text("SELECT id, label, created_at, diff, applied_parts FROM winter_import_runs WHERE status='pending' ORDER BY id")
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def reject_run(session: AsyncSession, run_id: int, *, now: datetime) -> bool:
    res = await session.execute(
        text("UPDATE winter_import_runs SET status='rejected', closed_at=:n WHERE id=:i AND status='pending'"),
        {"n": now, "i": run_id},
    )
    return bool(res.rowcount)


async def _apply_hours(
    session: AsyncSession, arena_id: int, season: int, label: str, *, hours_raw: str | None, p: PlannedPoint | None,
    phone: str | None,
) -> None:
    sets = ["hours_season = :hs", "updated_at = now()"]
    params: dict[str, Any] = {"a": arena_id, "s": season, "hs": label}
    if p is not None and hours_raw:
        sets += ["hours_text = :ht", "opening_hours = CAST(:oh AS jsonb)", "hours_known = :hk", "season_from = :sf", "season_to = :st"]
        params.update({
            "ht": hours_raw[:256], "oh": json.dumps(p.hours.opening_hours) if p.hours.opening_hours else None,
            "hk": p.hours.known, "sf": p.hours.season_from, "st": p.hours.season_to,
        })
    if phone:
        sets.append("phone = :ph")
        params["ph"] = phone
    if p is not None and p.source_url:
        sets.append("source_url = :url")
        params["url"] = p.source_url
    await session.execute(
        text(f"UPDATE seasonal_rink_seasons SET {', '.join(sets)} WHERE arena_id=:a AND season=:s"), params
    )


async def _log_hours_batch(
    session: AsyncSession, ids: list[int], season: int, admin_id: int | None, now: datetime,
    before: dict[int, dict[str, Any]], selection: dict[str, Any],
) -> int:
    after = await wa._snapshot(session, ids, season, wa._CHECK_COLS["import_changed"])
    items = [(aid, before[aid], after[aid], []) for aid in ids if aid in before]
    return await wa._log_batch(session, "import_changed", season, admin_id, selection, items, now)


async def apply_run(
    session: AsyncSession, run_id: int, parts: list[str], *, admin_id: int | None, now: datetime | None = None
) -> dict[str, Any]:
    """Применить выбранные части диффа. Каждую часть можно применить один раз."""
    now = now or datetime.now(timezone.utc)
    run = (
        await session.execute(
            text("SELECT id, season, status, diff, rows, applied_parts FROM winter_import_runs WHERE id=:i FOR UPDATE"),
            {"i": run_id},
        )
    ).mappings().first()
    if run is None:
        raise DiffError("not_found")
    if run["status"] != "pending":
        raise DiffError("not_pending", run["status"])
    diff, season = run["diff"], int(run["season"])
    label = ws.season_label(season)
    todo = [p for p in PARTS if p in parts and p not in run["applied_parts"]]
    if not todo:
        raise DiffError("nothing_to_apply")
    planned = {p.key: p for p in plan_rows(run["rows"])}
    out: dict[str, Any] = {}

    if "new" in todo:
        subset = [planned[k] for k in diff.get("new_keys", []) if k in planned]
        rep = await import_points(session, subset, now=now, source_season=season)
        out["new"] = {"created": rep.created, "matched_catalog": len(rep.matched_catalog), "existing": rep.existing}

    ids_changed: list[int] = []
    if "changed" in todo or "same" in todo:
        if "changed" in todo:
            ids_changed += [int(i["arena_id"]) for i in diff["changed"]]
            ids_changed += [int(i) for i in diff.get("verified", [])]
        if "same" in todo:
            ids_changed += [int(i["arena_id"]) for i in diff["same"]]
        before = await wa._snapshot(session, ids_changed, season, wa.HOURS_COLS)
        if "changed" in todo:
            for item in diff["changed"]:
                p = planned.get(item["key"])
                await _apply_hours(
                    session, int(item["arena_id"]), season, label, hours_raw=item["hours_new"], p=p, phone=item["phone_new"]
                )
            by_arena = {
                int(r[0]): planned.get(r[1]) for r in (
                    await session.execute(
                        text("SELECT arena_id, source_key FROM seasonal_rinks WHERE arena_id = ANY(:ids)"),
                        {"ids": [int(i) for i in diff.get("verified", [])] or [0]},
                    )
                ).all()
            }
            for aid in diff.get("verified", []):
                await _apply_hours(session, int(aid), season, label, hours_raw=None, p=by_arena.get(int(aid)), phone=None)
        if "same" in todo:
            for item in diff["same"]:
                p = planned.get(item["new_key"])
                await session.execute(
                    text("UPDATE seasonal_rinks SET source_key=:k, updated_at=now() WHERE arena_id=:a"),
                    {"k": item["new_key"], "a": int(item["arena_id"])},
                )
                if item["address_new"]:
                    await session.execute(
                        text("UPDATE arenas SET address=:ad WHERE id=:a"), {"ad": item["address_new"], "a": int(item["arena_id"])}
                    )
                await _apply_hours(
                    session, int(item["arena_id"]), season, label, hours_raw=item["hours_new"], p=p, phone=item["phone_new"]
                )
        batch_id = await _log_hours_batch(
            session, ids_changed, season, admin_id, now, before, {"run": run_id, "parts": [x for x in todo if x != "new"]}
        )
        out["changed"] = {"count": len(ids_changed), "batch_id": batch_id}

    if "missing" in todo:
        ids = [int(i) for i in diff.get("missing_ids", [])]
        rows = (
            await session.execute(
                text(
                    """SELECT arena_id FROM seasonal_rink_seasons
                       WHERE season=:s AND arena_id = ANY(:ids) AND state <> 'hidden' AND state <> 'flooded'
                         AND (admin_confirmed_at IS NULL OR admin_confirmed_at < :shield)"""
                ),
                {"s": season, "ids": ids, "shield": now - KEEP_SHIELD},
            )
        ).scalars().all()
        res = await wa.set_visibility(
            session, wa.HIDE, [int(r) for r in rows], season, admin_id=admin_id, now=now,
            selection={"run": run_id, "part": "missing"}, batch_action="import_missing", hidden_reason="not_in_list",
        )
        out["missing"] = {"hidden": res.count, "kept": len(ids) - res.count, "batch_id": res.batch_id}

    applied = list(run["applied_parts"]) + todo
    done = all(p in applied for p in available_parts(diff))
    await session.execute(
        text(
            """UPDATE winter_import_runs SET applied_parts = CAST(:ap AS jsonb),
                   status = CASE WHEN :done THEN 'applied' ELSE status END,
                   closed_at = CASE WHEN :done THEN :n ELSE closed_at END WHERE id=:i"""
        ),
        {"ap": json.dumps(applied), "done": done, "n": now, "i": run_id},
    )
    out["run_closed"] = done
    return out
