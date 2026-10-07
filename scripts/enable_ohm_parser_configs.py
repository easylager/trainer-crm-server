"""TASK-201-A: enable ОХМ parsing in prod ice_parser_jobs.config (DiaMond + Чижовка only).

ЛД МО (ledby_html_v1) и ledlife (ledlife_origin_html_v1) читают ОХМ из того же HTML без
дополнительных ключей в config — этот скрипт их не трогает.

Default dry-run: печатает diff по затронутым ключам. Запись только с ``--apply``.
Прод/cloud URL — только с ``--i-know-this-is-prod`` (``src/shared/ops_db_guard.py``).
Передайте ``DATABASE_URL`` / ``DATABASE_URL_SYNC`` явно для целевой базы.

Usage:
  PYTHONPATH=. python scripts/enable_ohm_parser_configs.py
  PYTHONPATH=. python scripts/enable_ohm_parser_configs.py --apply
  DATABASE_URL_SYNC=postgresql+psycopg://... PYTHONPATH=. python scripts/enable_ohm_parser_configs.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)

CHIZHOVKA_ARENA_ID = 6
CHIZHOVKA_PARSER_KEY = "chizhovka_html_v1"
OHM_SCHEDULE_URL = (
    "https://chizhovka-arena.by/fizkultura-i-sport/otrabotka-hokkejnogo-masterstva"
)

DIAMOND_ARENA_ID = 7
DIAMOND_PARSER_KEY = "diamond_html_v1"
DIAMOND_OHM_ADULT_MINOR = 1400


class OhmConfigError(RuntimeError):
    """Job missing, duplicate, or config patch refused."""


@dataclass(frozen=True)
class JobRow:
    id: int
    arena_id: int
    parser_key: str
    config: dict[str, Any]


@dataclass(frozen=True)
class ConfigPatch:
    job: JobRow
    before: dict[str, Any]
    after: dict[str, Any]


@dataclass(frozen=True)
class EnableOhmResult:
    patches: tuple[ConfigPatch, ...]
    applied: int


def _database_url() -> str:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def _load_job(session: Session, *, arena_id: int, parser_key: str) -> JobRow:
    rows = session.execute(
        text(
            """
            SELECT id, arena_id, parser_key, config
            FROM ice_parser_jobs
            WHERE arena_id = :aid AND parser_key = :pkey
            ORDER BY id
            """
        ),
        {"aid": arena_id, "pkey": parser_key},
    ).mappings().all()
    if not rows:
        raise OhmConfigError(f"no ice_parser_jobs row for arena_id={arena_id} parser_key={parser_key}")
    if len(rows) > 1:
        raise OhmConfigError(
            f"expected one job for arena_id={arena_id} parser_key={parser_key}, found {len(rows)}"
        )
    row = rows[0]
    cfg = row["config"]
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise OhmConfigError(f"job id={row['id']}: config is not a JSON object")
    return JobRow(
        id=int(row["id"]),
        arena_id=int(row["arena_id"]),
        parser_key=str(row["parser_key"]),
        config=dict(cfg),
    )


def _patch_chizhovka(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    out["ohm_schedule_url"] = OHM_SCHEDULE_URL
    return out


def _patch_diamond(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    drop_raw = out.get("drop_labels")
    if drop_raw is None:
        drop_list: list[Any] = []
    elif isinstance(drop_raw, list):
        drop_list = list(drop_raw)
    else:
        raise OhmConfigError("diamond job: drop_labels must be a list when present")
    new_drop = [label for label in drop_list if str(label).strip().upper() != "ОХМ"]
    out["drop_labels"] = new_drop
    out["ohm_labels"] = ["ОХМ"]
    out["ohm_adult_minor"] = DIAMOND_OHM_ADULT_MINOR
    return out


def _config_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keys = sorted(set(before) | set(after))
    diff: dict[str, dict[str, Any]] = {}
    for key in keys:
        b, a = before.get(key), after.get(key)
        if b != a:
            diff[key] = {"before": b, "after": a}
    return diff


def plan_patches(session: Session) -> tuple[ConfigPatch, ...]:
    specs: tuple[tuple[int, str, Callable[[dict[str, Any]], dict[str, Any]]], ...] = (
        (CHIZHOVKA_ARENA_ID, CHIZHOVKA_PARSER_KEY, _patch_chizhovka),
        (DIAMOND_ARENA_ID, DIAMOND_PARSER_KEY, _patch_diamond),
    )
    patches: list[ConfigPatch] = []
    for arena_id, parser_key, patch_fn in specs:
        job = _load_job(session, arena_id=arena_id, parser_key=parser_key)
        before = job.config
        after = patch_fn(before)
        if before != after:
            patches.append(ConfigPatch(job=job, before=before, after=after))
    return tuple(patches)


def _print_patches(patches: tuple[ConfigPatch, ...]) -> None:
    if not patches:
        print("No config changes needed (already enabled).")
        return
    for patch in patches:
        print(
            f"job id={patch.job.id} arena_id={patch.job.arena_id} "
            f"parser_key={patch.job.parser_key}"
        )
        diff = _config_diff(patch.before, patch.after)
        print(json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True))


def apply_enable_ohm_configs(session: Session) -> EnableOhmResult:
    patches = plan_patches(session)
    applied = 0
    for patch in patches:
        session.execute(
            text(
                """
                UPDATE ice_parser_jobs
                SET config = CAST(:config AS jsonb)
                WHERE id = :id AND arena_id = :aid AND parser_key = :pkey
                """
            ),
            {
                "id": patch.job.id,
                "aid": patch.job.arena_id,
                "pkey": patch.job.parser_key,
                "config": json.dumps(patch.after, ensure_ascii=False),
            },
        )
        applied += 1
    return EnableOhmResult(patches=patches, applied=applied)


def run(*, apply: bool, allow_prod: bool = False) -> EnableOhmResult:
    url = _database_url()
    assert_database_url(url, apply=apply, allow_prod=allow_prod)
    if allow_prod:
        warn_prod_ack()

    engine = create_engine(url)
    with Session(engine) as session:
        patches = plan_patches(session)
        _print_patches(patches)
        if not apply:
            print("Dry-run: no rows updated.")
            return EnableOhmResult(patches=patches, applied=0)
        result = apply_enable_ohm_configs(session)
        session.commit()
        print(f"Applied {result.applied} job config update(s).")
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Enable ОХМ keys in DiaMond and Chizhovka parser jobs.")
    parser.add_argument("--apply", action="store_true", help="Write ice_parser_jobs.config")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    try:
        run(apply=args.apply, allow_prod=args.i_know_this_is_prod)
    except OhmConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
