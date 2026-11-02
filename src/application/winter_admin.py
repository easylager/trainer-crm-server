"""Админ-операции «Зимних катков» на старте сезона (TASK-343, волна 2).

* пачки «подтвердить на сезон» / «скрыть» по городу, типу и точности геокода: сначала число
  (предпросмотр), потом применение; пачка пишется в журнал и отменяется 10 минут;
* поиск дублей и слияние: отметки, фото, подписки, галерея переезжают на оставшуюся точку,
  старые адреса отвечают 301;
* переименование точки (смена типа меняет slug, старый адрес -> 301).

Правила (каталог краевых случаев M2, M3, M4, O1, O2):
* «подтвердить» не трогает статус льда: только ставит ``admin_confirmed_at`` (кандидаты из OSM
  при подтверждении становятся видимыми, ждут заливку);
* точки «под вопросом» и со спором в пачки не попадают: по ним решение отдельное;
* отмена откатывает только строки, которые с момента пачки никто не менял (оптимистично);
* слияние необратимо и просит подтверждение: в журнале остаётся запись, отмены нет.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import arena_slug_redirects as redirects
from src.application.winter_import import haversine_m, winter_slug
from src.application.winter_marks import recompute_point
from src.shared import winter_status as ws
from src.shared.winter_text import normalize_address

UNDO_WINDOW = timedelta(minutes=10)
DUP_RADIUS_M = 60.0
MAP_PRECISIONS = ("house", "osm_exact", "manual")

CONFIRM = "confirm"
HIDE = "hide"
BATCH_ACTIONS = (CONFIRM, HIDE)

# Колонки строки сезона, которые пачка меняет (откат восстанавливает их) и тип для CAST.
_COL_TYPES: dict[str, str] = {
    "state": "varchar", "state_source": "varchar", "state_at": "timestamptz", "hidden_reason": "varchar",
    "admin_confirmed_at": "timestamptz", "doubtful": "boolean",
    "hours_text": "varchar", "opening_hours": "jsonb", "hours_known": "boolean", "hours_season": "varchar",
    "season_from": "varchar", "season_to": "varchar", "phone": "varchar", "source_url": "varchar",
}
STATE_COLS = ("state", "state_source", "state_at", "hidden_reason", "admin_confirmed_at", "doubtful")
HOURS_COLS = ("hours_text", "opening_hours", "hours_known", "hours_season", "season_from", "season_to", "phone", "source_url")
_CHECK_COLS = {
    CONFIRM: ("state", "state_source", "admin_confirmed_at", "hidden_reason"),
    HIDE: ("state", "state_source", "hidden_reason"),
    "import_missing": ("state", "state_source", "hidden_reason"),
    "import_changed": ("hours_text", "phone", "hours_season"),
}
_RESTORE_COLS = {
    CONFIRM: STATE_COLS, HIDE: STATE_COLS, "import_missing": STATE_COLS, "import_changed": HOURS_COLS,
}


class AdminOpError(Exception):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Selection:
    """Что выбрано для пачки. ``scope``: ``unconfirmed`` — видимые точки без подтверждения сезона,
    ``candidates`` — скрытые кандидаты OSM."""

    city_id: int | None = None
    kind: str | None = None  # rink | hockey_box
    precision: str | None = None  # map | nomap
    scope: str = "unconfirmed"

    def to_json(self) -> dict[str, Any]:
        return {"city_id": self.city_id, "kind": self.kind, "precision": self.precision, "scope": self.scope}


def _ser(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now


def _where(sel: Selection) -> tuple[str, dict[str, Any]]:
    clauses = ["s.season = :season", "a.merged_into_arena_id IS NULL"]
    params: dict[str, Any] = {}
    if sel.scope == "candidates":
        clauses.append("s.state = 'hidden' AND s.hidden_reason = 'candidate'")
    else:
        clauses.append("s.state <> 'hidden' AND s.admin_confirmed_at IS NULL AND NOT s.doubtful AND NOT s.dispute")
    if sel.city_id is not None:
        clauses.append("a.city_id = :city")
        params["city"] = int(sel.city_id)
    if sel.kind:
        clauses.append("sr.kind = :kind")
        params["kind"] = sel.kind
    if sel.precision == "map":
        clauses.append("sr.geocode_precision IN ('house', 'osm_exact', 'manual')")
    elif sel.precision == "nomap":
        clauses.append("sr.geocode_precision NOT IN ('house', 'osm_exact', 'manual')")
    return " AND ".join(clauses), params


_FROM = """FROM seasonal_rink_seasons s
           JOIN arenas a ON a.id = s.arena_id AND a.is_active
           JOIN seasonal_rinks sr ON sr.arena_id = a.id"""


async def select_ids(session: AsyncSession, sel: Selection, season: int, *, lock: bool = False) -> list[int]:
    where, params = _where(sel)
    params["season"] = season
    sql = f"SELECT a.id {_FROM} WHERE {where} ORDER BY a.id" + (" FOR UPDATE OF s" if lock else "")
    return [int(r[0]) for r in (await session.execute(text(sql), params)).all()]


async def season_overview(session: AsyncSession, now: datetime) -> dict[str, Any]:
    """Экран «Зимние точки»: сколько не подтверждено на сезон, по городам."""
    season = ws.current_season(_utc(now))
    rows = (
        await session.execute(
            text(
                f"""SELECT c.id AS city_id, c.name AS city, sr.kind AS kind,
                           count(*) FILTER (WHERE s.state <> 'hidden' AND s.admin_confirmed_at IS NULL
                                            AND NOT s.doubtful AND NOT s.dispute) AS unconfirmed,
                           count(*) FILTER (WHERE s.state = 'hidden' AND s.hidden_reason = 'candidate') AS candidates,
                           count(*) FILTER (WHERE s.state <> 'hidden') AS visible
                    {_FROM} JOIN cities c ON c.id = a.city_id
                    WHERE s.season = :season AND a.merged_into_arena_id IS NULL
                    GROUP BY c.id, c.name, sr.kind"""
            ),
            {"season": season},
        )
    ).all()
    cities: dict[int, dict[str, Any]] = {}
    for r in rows:
        c = cities.setdefault(
            int(r.city_id), {"city_id": int(r.city_id), "city": r.city, "unconfirmed": 0, "candidates": 0,
                             "visible": 0, "rink": 0, "hockey_box": 0}
        )
        c["unconfirmed"] += int(r.unconfirmed)
        c["candidates"] += int(r.candidates)
        c["visible"] += int(r.visible)
        c[r.kind] += int(r.unconfirmed)
    listing = sorted(cities.values(), key=lambda c: (-c["unconfirmed"], c["city"]))
    return {
        "season": season, "season_label": ws.season_label(season),
        "unconfirmed": sum(c["unconfirmed"] for c in listing),
        "candidates": sum(c["candidates"] for c in listing),
        "cities": [c for c in listing if c["unconfirmed"] or c["candidates"]],
    }


# --- пачки -------------------------------------------------------------------------
@dataclass
class BatchResult:
    batch_id: int
    action: str
    count: int
    skipped: int = 0


async def _snapshot(session: AsyncSession, ids: list[int], season: int, cols: tuple[str, ...]) -> dict[int, dict[str, Any]]:
    rows = (
        await session.execute(
            text(f"SELECT arena_id, {', '.join(cols)} FROM seasonal_rink_seasons WHERE season=:s AND arena_id = ANY(:ids)"),
            {"s": season, "ids": ids},
        )
    ).mappings().all()
    return {int(r["arena_id"]): {c: _ser(r[c]) for c in cols} for r in rows}


async def _open_item_ids(session: AsyncSession, arena_id: int, kinds: tuple[str, ...]) -> list[int]:
    return [
        int(r[0])
        for r in (
            await session.execute(
                text(
                    "SELECT id FROM seasonal_moderation_items WHERE arena_id=:a AND status='open' AND kind = ANY(:k)"
                ),
                {"a": arena_id, "k": list(kinds)},
            )
        ).all()
    ]


async def _log_batch(
    session: AsyncSession, action: str, season: int, admin_id: int | None, selection: dict[str, Any],
    items: list[tuple[int, dict, dict, list[int]]], now: datetime,
) -> int:
    batch_id = int(
        (
            await session.execute(
                text(
                    """INSERT INTO winter_admin_batches (action, season, admin_telegram_id, selection, item_count, created_at)
                       VALUES (:a, :s, :adm, CAST(:sel AS jsonb), :n, :now) RETURNING id"""
                ),
                {"a": action, "s": season, "adm": admin_id, "sel": json.dumps(selection), "n": len(items), "now": now},
            )
        ).scalar_one()
    )
    for arena_id, before, after, closed in items:
        await session.execute(
            text(
                """INSERT INTO winter_admin_batch_items (batch_id, arena_id, before, after, closed_items)
                   VALUES (:b, :a, CAST(:bf AS jsonb), CAST(:af AS jsonb), CAST(:cl AS jsonb))"""
            ),
            {"b": batch_id, "a": arena_id, "bf": json.dumps(before), "af": json.dumps(after), "cl": json.dumps(closed)},
        )
    return batch_id


async def apply_batch(
    session: AsyncSession, action: str, sel: Selection, *, admin_id: int | None, now: datetime | None = None,
    expect_count: int | None = None,
) -> BatchResult:
    """Применить пачку. ``expect_count`` — число из предпросмотра: список изменился -> ``stale``."""
    now = _utc(now)
    if action not in BATCH_ACTIONS:
        raise AdminOpError("bad_action")
    season = ws.current_season(now)
    ids = await select_ids(session, sel, season, lock=True)
    if expect_count is not None and expect_count != len(ids):
        raise AdminOpError("stale", f"{len(ids)}")
    return await set_visibility(session, action, ids, season, admin_id=admin_id, now=now, selection=sel.to_json())


async def set_visibility(
    session: AsyncSession, action: str, ids: list[int], season: int, *, admin_id: int | None, now: datetime,
    selection: dict[str, Any], batch_action: str | None = None, hidden_reason: str = "admin",
) -> BatchResult:
    """Подтвердить / скрыть заданные точки одной записью журнала (с данными для отмены)."""
    batch_action = batch_action or action
    if not ids:
        return BatchResult(0, batch_action, 0)
    await session.execute(
        text("SELECT 1 FROM seasonal_rink_seasons WHERE season=:s AND arena_id = ANY(:ids) FOR UPDATE"),
        {"s": season, "ids": ids},
    )
    before = await _snapshot(session, ids, season, STATE_COLS)
    closed_kinds = ("new_point",) if action == CONFIRM else ("gone", "dispute", "new_point")
    closed_by_arena = {aid: await _open_item_ids(session, aid, closed_kinds) for aid in ids}
    if action == CONFIRM:
        await session.execute(
            text(
                """UPDATE seasonal_rink_seasons SET admin_confirmed_at = :n,
                       state = CASE WHEN state = 'hidden' THEN 'waiting' ELSE state END,
                       state_source = CASE WHEN state = 'hidden' THEN 'admin' ELSE state_source END,
                       state_at = CASE WHEN state = 'hidden' THEN :n ELSE state_at END,
                       hidden_reason = CASE WHEN state = 'hidden' THEN NULL ELSE hidden_reason END,
                       updated_at = now()
                   WHERE season = :s AND arena_id = ANY(:ids)"""
            ),
            {"n": now, "s": season, "ids": ids},
        )
        resolution = "confirmed"
    else:
        await session.execute(
            text(
                """UPDATE seasonal_rink_seasons SET state = 'hidden', state_source = 'admin', state_at = :n,
                       hidden_reason = :hr, doubtful = false, updated_at = now()
                   WHERE season = :s AND arena_id = ANY(:ids)"""
            ),
            {"n": now, "s": season, "ids": ids, "hr": hidden_reason},
        )
        resolution = "hidden"
    await session.execute(
        text(
            """UPDATE seasonal_moderation_items SET status='done', resolution=:r, resolved_at=:n, resolved_by=:by
               WHERE id = ANY(:ids) AND status='open'"""
        ),
        {"r": resolution, "n": now, "by": admin_id, "ids": [i for v in closed_by_arena.values() for i in v]},
    )
    after = await _snapshot(session, ids, season, _CHECK_COLS[batch_action])
    items = [(aid, before[aid], after[aid], closed_by_arena[aid]) for aid in ids]
    batch_id = await _log_batch(session, batch_action, season, admin_id, selection, items, now)
    return BatchResult(batch_id, batch_action, len(ids))


def _restore_value(col: str, value: Any) -> Any:
    if value is None:
        return None
    if col == "opening_hours":
        return json.dumps(value)
    if _COL_TYPES[col] == "timestamptz":
        return datetime.fromisoformat(value)
    return value


async def _restore_rows(session: AsyncSession, batch_id: int, action: str, season: int) -> tuple[int, int]:
    """Вернуть строки пачки; пропускаем те, что после пачки кто-то менял. -> (возвращено, пропущено)."""
    items = (
        await session.execute(
            text("SELECT arena_id, before, after, closed_items FROM winter_admin_batch_items WHERE batch_id=:b"),
            {"b": batch_id},
        )
    ).mappings().all()
    check = _CHECK_COLS[action]
    restore = _RESTORE_COLS[action]
    restored = skipped = 0
    for it in items:
        aid = int(it["arena_id"])
        cur = await _snapshot(session, [aid], season, check)
        if cur.get(aid) != it["after"]:
            skipped += 1
            continue
        sets = ", ".join(f"{c} = CAST(:{c} AS {_COL_TYPES[c]})" for c in restore)
        params = {c: _restore_value(c, it["before"][c]) for c in restore}
        params.update({"a": aid, "s": season})
        await session.execute(
            text(f"UPDATE seasonal_rink_seasons SET {sets}, updated_at = now() WHERE arena_id=:a AND season=:s"), params
        )
        closed = [int(x) for x in (it["closed_items"] or [])]
        if closed:
            await session.execute(
                text(
                    """UPDATE seasonal_moderation_items m SET status='open', resolution=NULL, resolved_at=NULL, resolved_by=NULL
                       WHERE m.id = ANY(:ids) AND m.status='done'
                         AND NOT EXISTS (SELECT 1 FROM seasonal_moderation_items o
                                         WHERE o.status='open' AND o.kind=m.kind AND COALESCE(o.arena_id,0)=COALESCE(m.arena_id,0)
                                           AND COALESCE(o.ref_id,0)=COALESCE(m.ref_id,0))"""
                ),
                {"ids": closed},
            )
        restored += 1
    return restored, skipped


async def undo_batch(session: AsyncSession, batch_id: int, *, now: datetime | None = None) -> dict[str, Any]:
    """Отменить пачку в течение 10 минут. ``status``: ok | already | expired | not_undoable | not_found."""
    now = _utc(now)
    row = (
        await session.execute(
            text("SELECT action, season, created_at, undone_at FROM winter_admin_batches WHERE id=:i FOR UPDATE"),
            {"i": batch_id},
        )
    ).first()
    if row is None:
        return {"status": "not_found"}
    if row.undone_at is not None:
        return {"status": "already"}
    if row.action not in _CHECK_COLS:
        return {"status": "not_undoable"}
    if now - row.created_at > UNDO_WINDOW:
        return {"status": "expired"}
    restored, skipped = await _restore_rows(session, batch_id, row.action, int(row.season))
    await session.execute(text("UPDATE winter_admin_batches SET undone_at=:n WHERE id=:i"), {"n": now, "i": batch_id})
    return {"status": "ok", "restored": restored, "skipped": skipped}


# --- дубли -------------------------------------------------------------------------
@dataclass
class DupMember:
    arena_id: int
    name: str
    address: str | None
    kind: str
    state: str
    name_source: str
    marks: int
    subs: int
    photos: int
    lat: float | None = None
    lon: float | None = None

    @property
    def weight(self) -> tuple:
        # Кого оставлять: видимая, с настоящим названием, с наибольшим «живым весом», меньший id.
        return (self.state != "hidden", self.name_source != "generated", self.marks + self.subs * 2 + self.photos * 3, -self.arena_id)


@dataclass
class DupGroup:
    reasons: set[str] = field(default_factory=set)
    members: list[DupMember] = field(default_factory=list)

    def keep_candidate(self) -> DupMember:
        return max(self.members, key=lambda m: m.weight)


async def find_duplicate_groups(
    session: AsyncSession, now: datetime | None = None, *, city_id: int | None = None
) -> list[DupGroup]:
    """Группы точек одного города и типа с совпавшим адресом, названием или координатой (<= 60 м)."""
    season = ws.current_season(_utc(now))
    rows = (
        await session.execute(
            text(
                """SELECT a.id, a.city_id, c.name AS city, a.name, a.address, a.latitude, a.longitude,
                          sr.kind, sr.name_source, sr.geocode_precision, s.state,
                          (SELECT count(*) FROM seasonal_rink_marks m WHERE m.arena_id = a.id) AS marks,
                          (SELECT count(*) FROM winter_subscriptions w WHERE w.arena_id = a.id AND w.kind='point' AND w.active) AS subs,
                          (SELECT count(*) FROM seasonal_rink_photos p WHERE p.arena_id = a.id AND p.status='accepted') AS photos
                   FROM arenas a
                   JOIN seasonal_rinks sr ON sr.arena_id = a.id
                   JOIN cities c ON c.id = a.city_id
                   JOIN seasonal_rink_seasons s ON s.arena_id = a.id AND s.season = :season
                   WHERE a.is_active AND a.merged_into_arena_id IS NULL AND (CAST(:city AS integer) IS NULL OR a.city_id = CAST(:city AS integer))
                   ORDER BY a.id"""
            ),
            {"season": season, "city": city_id},
        )
    ).mappings().all()
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    reasons: dict[tuple[int, int], set[str]] = {}

    def union(a: int, b: int, why: str) -> None:
        reasons.setdefault((min(a, b), max(a, b)), set()).add(why)
        parent[find(a)] = find(b)

    by_addr: dict[tuple, int] = {}
    by_name: dict[tuple, int] = {}
    members: dict[int, DupMember] = {}
    geo: dict[tuple[int, str], list[Any]] = {}
    for r in rows:
        aid = int(r["id"])
        members[aid] = DupMember(
            aid, r["name"], r["address"], r["kind"], r["state"], r["name_source"], int(r["marks"]), int(r["subs"]),
            int(r["photos"]), r["latitude"], r["longitude"],
        )
        find(aid)
        addr = normalize_address(r["address"], r["city"])
        if addr:
            key = (int(r["city_id"]), r["kind"], addr)
            if key in by_addr:
                union(aid, by_addr[key], "address")
            else:
                by_addr[key] = aid
        if r["name_source"] == "source" and (r["name"] or "").strip():
            nkey = (int(r["city_id"]), r["kind"], r["name"].strip().lower())
            if nkey in by_name:
                union(aid, by_name[nkey], "name")
            else:
                by_name[nkey] = aid
        if r["geocode_precision"] in MAP_PRECISIONS and r["latitude"] is not None and r["longitude"] is not None:
            geo.setdefault((int(r["city_id"]), r["kind"]), []).append(r)
    for pts in geo.values():
        for i, p in enumerate(pts):
            for q in pts[i + 1:]:
                if haversine_m(float(p["latitude"]), float(p["longitude"]), float(q["latitude"]), float(q["longitude"])) <= DUP_RADIUS_M:
                    union(int(p["id"]), int(q["id"]), "geo")
    groups: dict[int, DupGroup] = {}
    for aid, m in members.items():
        groups.setdefault(find(aid), DupGroup()).members.append(m)
    out: list[DupGroup] = []
    for g in groups.values():
        if len(g.members) < 2:
            continue
        ids = {m.arena_id for m in g.members}
        g.reasons = {why for (a, b), whys in reasons.items() if a in ids and b in ids for why in whys}
        out.append(g)
    out.sort(key=lambda g: min(m.arena_id for m in g.members))
    return out


# --- слияние -----------------------------------------------------------------------
async def merge_points(
    session: AsyncSession, source_id: int, target_id: int, *, admin_id: int | None, now: datetime | None = None
) -> dict[str, Any]:
    """Влить ``source`` в ``target``: отметки, фото, подписки и галерея переезжают, адрес ``source`` -> 301.

    Необратимо; вызывающий уже получил подтверждение админа. Commit — на вызывающем.
    """
    now = _utc(now)
    if source_id == target_id:
        raise AdminOpError("same")
    season = ws.current_season(now)
    info = {}
    for aid in sorted((source_id, target_id)):
        row = (
            await session.execute(
                text(
                    """SELECT a.id, a.city_id, a.is_active, a.merged_into_arena_id, sr.arena_id AS rink
                       FROM arenas a LEFT JOIN seasonal_rinks sr ON sr.arena_id = a.id WHERE a.id = :i FOR UPDATE OF a"""
                ),
                {"i": aid},
            )
        ).first()
        if row is None or row.rink is None:
            raise AdminOpError("not_found")
        info[aid] = row
    src, dst = info[source_id], info[target_id]
    if src.merged_into_arena_id is not None or not src.is_active:
        raise AdminOpError("already_merged")
    if dst.merged_into_arena_id is not None or not dst.is_active:
        raise AdminOpError("target_inactive")
    if src.city_id != dst.city_id:
        raise AdminOpError("other_city")
    stats: dict[str, Any] = {}

    async def run(sql: str, **params: Any) -> int:
        return int((await session.execute(text(sql), {"s": source_id, "t": target_id, **params})).rowcount or 0)

    stats["marks"] = await run("UPDATE seasonal_rink_marks SET arena_id=:t WHERE arena_id=:s")
    stats["photos"] = await run("UPDATE seasonal_rink_photos SET arena_id=:t WHERE arena_id=:s")
    await run("UPDATE seasonal_moderation_items SET arena_id=:t WHERE arena_id=:s AND kind='photo_first' AND status='open'")
    await run("UPDATE winter_user_prefs SET photo_arena_id=:t WHERE photo_arena_id=:s")
    await run("UPDATE winter_asks SET arena_id=:t WHERE arena_id=:s")
    stats["media"] = await run("UPDATE media SET owner_id=:t WHERE owner_type='arena' AND owner_id=:s")
    # «Точки нет» относилось к дублю, на оставшуюся точку не переносим.
    await run("DELETE FROM seasonal_rink_signals WHERE arena_id=:s")
    # Подписки: у кого уже есть колокольчик на оставшейся, лишний убираем; активность сохраняем.
    await run(
        """UPDATE winter_subscriptions t SET active = true, deactivated_reason = NULL
           FROM winter_subscriptions x
           WHERE x.arena_id=:s AND x.kind='point' AND x.active AND t.arena_id=:t AND t.kind='point'
             AND t.telegram_id = x.telegram_id AND NOT t.active"""
    )
    stats["subs_deduped"] = await run(
        """DELETE FROM winter_subscriptions x WHERE x.arena_id=:s AND x.kind='point'
           AND EXISTS (SELECT 1 FROM winter_subscriptions t WHERE t.arena_id=:t AND t.kind='point' AND t.telegram_id=x.telegram_id)"""
    )
    stats["subs"] = await run("UPDATE winter_subscriptions SET arena_id=:t WHERE arena_id=:s AND kind='point'")
    # Повод рассылки по дублю не должен уйти после слияния.
    await run("DELETE FROM winter_notify_queue WHERE arena_id=:s AND sent_at IS NULL")
    await run("DELETE FROM winter_flood_events WHERE arena_id=:s AND fanned_out_at IS NULL")
    # Что знаем у дубля, а у цели пусто — добираем.
    await run(
        """UPDATE seasonal_rinks t SET operator = COALESCE(t.operator, x.operator), is_paid = COALESCE(t.is_paid, x.is_paid),
               price_note = COALESCE(t.price_note, x.price_note), updated_at = now()
           FROM seasonal_rinks x WHERE t.arena_id=:t AND x.arena_id=:s"""
    )
    await run(
        """UPDATE seasonal_rink_seasons t SET
               phone = COALESCE(t.phone, x.phone), source_url = COALESCE(t.source_url, x.source_url),
               hours_text = CASE WHEN NOT t.hours_known AND x.hours_known THEN x.hours_text ELSE t.hours_text END,
               opening_hours = CASE WHEN NOT t.hours_known AND x.hours_known THEN x.opening_hours ELSE t.opening_hours END,
               hours_season = CASE WHEN NOT t.hours_known AND x.hours_known THEN x.hours_season ELSE t.hours_season END,
               season_from = CASE WHEN NOT t.hours_known AND x.hours_known THEN x.season_from ELSE t.season_from END,
               season_to = CASE WHEN NOT t.hours_known AND x.hours_known THEN x.season_to ELSE t.season_to END,
               hours_known = t.hours_known OR x.hours_known,
               admin_confirmed_at = COALESCE(t.admin_confirmed_at, x.admin_confirmed_at), updated_at = now()
           FROM seasonal_rink_seasons x WHERE t.arena_id=:t AND x.arena_id=:s AND t.season = x.season"""
    )
    await run(
        """UPDATE arena_profiles t SET catalog_pin = x.catalog_pin FROM arena_profiles x
           WHERE t.arena_id=:t AND x.arena_id=:s AND t.catalog_pin IS NULL AND x.catalog_pin IS NOT NULL"""
    )
    await run("UPDATE arena_profiles SET catalog_pin = NULL WHERE arena_id=:s")
    await run("UPDATE seasonal_rinks SET same_complex_id=:t WHERE same_complex_id=:s AND arena_id<>:t")
    await run("UPDATE seasonal_rinks SET same_complex_id=NULL WHERE arena_id=:t AND same_complex_id IN (:s, :t)")
    # 301: старый slug дубля и все, что вели на дубль раньше.
    old_slug = (await session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id=:s"), {"s": source_id})).scalar_one_or_none()
    if old_slug:
        await redirects.record_redirect(session, city_id=int(src.city_id), old_slug=old_slug, arena_id=target_id, reason="merge")
    stats["redirects"] = await redirects.repoint_redirects(session, from_arena_id=source_id, to_arena_id=target_id) + (1 if old_slug else 0)
    # Дубль: скрыт, неактивен, ведёт на цель (общий механизм 301 по ``merged_into_arena_id``).
    await run("UPDATE arenas SET merged_into_arena_id=:t, is_active=false WHERE id=:s")
    await run(
        """UPDATE seasonal_rink_seasons SET state='hidden', state_source='admin', state_at=:n, hidden_reason='merged',
               doubtful=false, updated_at=now() WHERE arena_id=:s""",
        n=now,
    )
    await run(
        """UPDATE seasonal_moderation_items SET status='done', resolution='merged', resolved_at=:n, resolved_by=:by
           WHERE arena_id=:s AND status='open'""",
        n=now, by=admin_id,
    )
    await recompute_point(session, target_id, season, now)
    await _log_batch(
        session, "merge", season, admin_id, {"source": source_id, "target": target_id, **{k: v for k, v in stats.items()}}, [], now
    )
    return stats


# --- переименование ----------------------------------------------------------------
async def rename_point(
    session: AsyncSession, arena_id: int, *, name: str | None = None, kind: str | None = None,
    admin_id: int | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Новое название и/или тип. Смена типа меняет slug (``-korobka-`` / ``-katok-``): старый адрес -> 301."""
    now = _utc(now)
    row = (
        await session.execute(
            text(
                """SELECT a.id, a.city_id, c.name AS city, sr.kind FROM arenas a JOIN seasonal_rinks sr ON sr.arena_id=a.id
                   JOIN cities c ON c.id=a.city_id WHERE a.id=:i FOR UPDATE OF a"""
            ),
            {"i": arena_id},
        )
    ).first()
    if row is None:
        raise AdminOpError("not_found")
    out: dict[str, Any] = {"old_slug": None, "slug": None}
    if name is not None:
        clean = " ".join(name.split())[:128]
        if not clean:
            raise AdminOpError("empty_name")
        await session.execute(text("UPDATE arenas SET name=:n WHERE id=:i"), {"n": clean, "i": arena_id})
        await session.execute(
            text("UPDATE seasonal_rinks SET name_source='admin', updated_at=now() WHERE arena_id=:i"),
            {"i": arena_id},
        )
    if kind is not None and kind != row.kind:
        if kind not in ("rink", "hockey_box"):
            raise AdminOpError("bad_kind")
        await session.execute(
            text("UPDATE seasonal_rinks SET kind=:k, often_hockey = (CAST(:k AS varchar) = 'hockey_box') OR often_hockey, updated_at=now() WHERE arena_id=:i"),
            {"k": kind, "i": arena_id},
        )
        try:
            out["old_slug"] = await redirects.change_slug(session, arena_id, winter_slug(row.city, kind, arena_id))
        except redirects.SlugError as exc:
            raise AdminOpError("slug_" + exc.code) from exc
    out["slug"] = (await session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id=:i"), {"i": arena_id})).scalar_one_or_none()
    return out


async def resolve_dispute(
    session: AsyncSession, arena_id: int, state: str, *, admin_id: int | None, now: datetime | None = None
) -> bool:
    """Спор отметок: админ сам ставит статус льда (``flooded`` / ``waiting`` / ``hidden``), спор закрыт."""
    from src.application.winter_marks import _close_items, set_state_admin

    now = _utc(now)
    if state not in ("flooded", "waiting", "hidden"):
        raise AdminOpError("bad_state")
    ok = await set_state_admin(session, arena_id, state, admin_id=admin_id, now=now)
    if not ok:
        return False
    await session.execute(
        text("UPDATE seasonal_rink_seasons SET dispute=false, updated_at=now() WHERE arena_id=:a AND season=:s"),
        {"a": arena_id, "s": ws.current_season(now)},
    )
    await _close_items(session, "dispute", arena_id, state, admin_id)
    return True


async def confirm_flood_card(session: AsyncSession, arena_id: int, now: datetime | None = None) -> dict[str, Any] | None:
    """Что показать админу в запросе «подтвердить заливку»: сколько отметок, когда, откуда, есть ли фото."""
    now = _utc(now)
    season = ws.current_season(now)
    head = (
        await session.execute(
            text(
                """SELECT a.name, c.name AS city, a.address, s.state, s.pending_confirm, s.flood_floor_at
                   FROM seasonal_rink_seasons s JOIN arenas a ON a.id = s.arena_id JOIN cities c ON c.id = a.city_id
                   WHERE s.arena_id = :a AND s.season = :s"""
            ),
            {"a": arena_id, "s": season},
        )
    ).first()
    if head is None:
        return None
    since = now - ws.FLOODED_WINDOW
    if head.flood_floor_at is not None and head.flood_floor_at > since:
        since = head.flood_floor_at
    marks = (
        await session.execute(
            text(
                """SELECT source, count(DISTINCT actor) AS people, max(created_at) AS last_at, min(created_at) AS first_at
                   FROM seasonal_rink_marks
                   WHERE arena_id = :a AND season = :s AND kind = 'ice' AND value = 'flooded' AND created_at > :since
                   GROUP BY source ORDER BY source"""
            ),
            {"a": arena_id, "s": season, "since": since},
        )
    ).all()
    photos = int(
        (
            await session.execute(
                text(
                    """SELECT count(*) FROM seasonal_rink_photos WHERE arena_id = :a AND created_at > :since
                       AND status <> 'rejected'"""
                ),
                {"a": arena_id, "since": since},
            )
        ).scalar_one()
    )
    return {
        "name": head.name, "city": head.city, "address": head.address, "state": head.state,
        "pending": bool(head.pending_confirm),
        "people": sum(int(m.people) for m in marks),
        "by_source": {m.source: int(m.people) for m in marks},
        "last_at": max((m.last_at for m in marks), default=None),
        "first_at": min((m.first_at for m in marks), default=None),
        "photos": photos,
    }


async def resolve_confirm_flood(
    session: AsyncSession, arena_id: int, decision: str, *, admin_id: int | None, now: datetime | None = None
) -> bool:
    """Решение админа по запросу: ``flooded`` (рассылка подписчикам), ``waiting`` или ``ask_more``."""
    from src.application.winter_marks import ask_more, set_state_admin

    now = _utc(now)
    if decision == "ask_more":
        return await ask_more(session, arena_id, admin_id=admin_id, now=now)
    if decision not in ("flooded", "waiting"):
        raise AdminOpError("bad_state")
    return await set_state_admin(session, arena_id, decision, admin_id=admin_id, now=now)


async def merge_preview(session: AsyncSession, source_id: int, target_id: int) -> dict[str, Any]:
    """Что переедет при слиянии: числа для экрана подтверждения."""
    row = (
        await session.execute(
            text(
                """SELECT
                     (SELECT name FROM arenas WHERE id=:s) AS s_name, (SELECT name FROM arenas WHERE id=:t) AS t_name,
                     (SELECT count(*) FROM seasonal_rink_marks WHERE arena_id=:s) AS marks,
                     (SELECT count(*) FROM seasonal_rink_photos WHERE arena_id=:s) AS photos,
                     (SELECT count(*) FROM winter_subscriptions WHERE arena_id=:s AND kind='point') AS subs,
                     (SELECT count(*) FROM media WHERE owner_type='arena' AND owner_id=:s) AS media"""
            ),
            {"s": source_id, "t": target_id},
        )
    ).mappings().one()
    return dict(row)
