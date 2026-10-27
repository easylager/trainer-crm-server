"""Schedule screenshots inbox, Claude's side: list what is waiting, submit a parsed spec.

Used by the ``ice-inbox`` skill. Runs against prod, so it needs the Railway env:
  bash scripts/run_ice_ingest_prod_local.sh scripts/ice_inbox.py list --i-know-this-is-prod
  bash scripts/run_ice_ingest_prod_local.sh scripts/ice_inbox.py submit 12 /path/spec.json --i-know-this-is-prod

``list`` saves each pending screenshot to ``--out`` and prints its path next to what we already know
about the arena (timezone, prices, source link), so the spec can reuse real prices instead of guessing.
``submit`` stores the spec as «parsed»; the admin then reviews and publishes it on the phone.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    warn_prod_ack,
)


async def _list(out: Path) -> None:
    from sqlalchemy import text

    from src.application import admin_ice_inbox as inbox
    from src.infrastructure.db.session import async_session_factory

    out.mkdir(parents=True, exist_ok=True)
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT i.id, i.arena_id, a.name, c.name AS city, i.uploaded_at, i.status,
                           p.timezone, p.phone, p.tickets_url, p.visit_info, s.source_url, s.source_kind
                    FROM arena_schedule_inbox i
                    JOIN arenas a ON a.id = i.arena_id
                    LEFT JOIN cities c ON c.id = a.city_id
                    LEFT JOIN arena_profiles p ON p.arena_id = a.id
                    LEFT JOIN arena_schedule_sources s ON s.arena_id = a.id
                    WHERE i.status = 'pending' ORDER BY i.uploaded_at
                    """
                )
            )
        ).all()
        if not rows:
            print("Нет скринов, ждущих разбора.")
            return
        for r in rows:
            image = await inbox.get_image(session, r.id)
            path = None
            if image:
                body, content_type = image
                ext = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
                path = out / f"inbox-{r.id}{ext}"
                path.write_bytes(body)
            print(json.dumps(
                {
                    "inbox_id": r.id, "arena_id": r.arena_id, "arena": r.name, "city": r.city,
                    "uploaded_at": r.uploaded_at.isoformat(), "image": str(path) if path else None,
                    "timezone": r.timezone, "phone": r.phone, "tickets_url": r.tickets_url,
                    "source_url": r.source_url, "source_kind": r.source_kind,
                    "known_prices": (r.visit_info or {}).get("tickets"),
                },
                ensure_ascii=False,
            ))


async def _submit(inbox_id: int, spec_path: Path) -> None:
    from src.application import admin_ice_inbox as inbox
    from src.infrastructure.db.session import async_session_factory

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    async with async_session_factory() as session:
        try:
            count = await inbox.submit_parsed(session, inbox_id, spec)
        except inbox.InboxError as exc:
            raise SystemExit(f"Не принято ({exc.code}): {exc}") from exc
    print(f"Принято: {count} сеансов. Админ увидит их во «Входящих» и опубликует сам.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "ice-inbox")
    p_submit = sub.add_parser("submit")
    p_submit.add_argument("inbox_id", type=int)
    p_submit.add_argument("spec", type=Path)
    for p in (p_list, p_submit):
        add_i_know_this_is_prod_argument(p)
    args = ap.parse_args()

    from src.shared.config import Settings

    url = Settings().database_url
    assert_database_url(url, apply=True, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        assert_railway_target_database(url)
        warn_prod_ack()
    if args.cmd == "list":
        asyncio.run(_list(args.out))
    else:
        asyncio.run(_submit(args.inbox_id, args.spec))


if __name__ == "__main__":
    main()
