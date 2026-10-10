#!/usr/bin/env python
"""AC-2: у каждой опубликованной BY-арены ≥1 входящая SSR-ссылка (TASK-191-B).

Сканирует отрендеренные страницы /, /c/{city} (все страницы пагинации), /ice/{city}/today.
Только чтение БД; прод — с ``--i-know-this-is-prod``.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.catalog_home_page import load_catalog_home_view, render_catalog_home_page  # noqa: E402
from src.application.ice_city_day import city_slug, get_city_ice_day  # noqa: E402
from src.application.ice_city_day_page import render_ice_city_day_page  # noqa: E402
from src.application.place_links import place_path  # noqa: E402
from src.application.selection_page import load_selection_view, render_selection_page, selection_path  # noqa: E402
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params  # noqa: E402
from src.shared.ops_db_guard import (  # noqa: E402
    ProdDatabaseError,
    add_i_know_this_is_prod_argument,
    assert_database_url,
    async_database_url,
    normalize_db_url,
    warn_prod_ack,
)

_PLACE_HREF_RE = re.compile(r'href="(/p/[^"#?]+)"')


def _normalize_async_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


def _extract_place_paths(html: str) -> set[str]:
    return set(_PLACE_HREF_RE.findall(html))


async def _all_visible_arenas(session) -> list[dict]:
    scope = public_scope_params()
    rows = (
        await session.execute(
            text(
                f"""
                SELECT a.id, c.name AS city_name, p.slug
                FROM arenas a
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE c.country = 'BY' AND {PUBLIC_ARENA_VISIBLE_SQL}
                ORDER BY a.id
                """
            ),
            scope,
        )
    ).mappings()
    out = []
    for r in rows:
        slug = str(r.get("slug") or "").strip()
        if not slug:
            continue
        out.append(
            {
                "id": int(r["id"]),
                "path": place_path(city_name=str(r["city_name"]), slug=slug),
                "city_name": str(r["city_name"]),
            }
        )
    return out


async def _collect_ssr_links(session, *, base: str) -> set[str]:
    links: set[str] = set()
    home_view = await load_catalog_home_view(session)
    home_html = render_catalog_home_page(
        home_view,
        canonical_url=f"{base}/",
        og_image_url="/logos/02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png",
        cta_url=None,
        trainers_url=f"{base}/trainers",
    )
    links |= _extract_place_paths(home_html)

    cities = (
        await session.execute(
            text(
                f"""
                SELECT DISTINCT c.id, c.name, c.country
                FROM cities c
                JOIN arenas a ON a.city_id = c.id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE c.country = 'BY' AND {PUBLIC_ARENA_VISIBLE_SQL}
                ORDER BY c.name
                """
            ),
            public_scope_params(),
        )
    ).mappings()
    for city in cities:
        city_map = dict(city)
        page = 1
        pages = 1
        while page <= pages:
            view = await load_selection_view(session, city=city_map, venue=None, when=None, page=page)
            pages = int(view.get("pages") or 1)
            html = render_selection_page(
                view,
                canonical_url=base + selection_path(city_name=str(city["name"]), venue=None, when=None),
                og_image_url=base + f"/c/{city_slug(str(city['name']))}/og.png",
                cta_url=None,
                share={"share_url": base + selection_path(city_name=str(city["name"]), venue=None, when=None), "share_text": "", "share_body": ""},
                city_page_url=None,
                base_url=base,
            )
            links |= _extract_place_paths(html)
            page += 1

        day = await get_city_ice_day(session, city_id=int(city["id"]))
        if day is not None:
            ice_html = render_ice_city_day_page(
                city_name=str(city["name"]),
                day=day,
                canonical_url=base + f"/ice/{city_slug(str(city['name']))}/today",
                og_image_url=base + f"/ice/{city_slug(str(city['name']))}/today/og.png",
                cta_url=None,
                country=str(city.get("country") or "BY"),
            )
            links |= _extract_place_paths(ice_html)
    return links


async def main() -> int:
    parser = argparse.ArgumentParser(description="Find published BY arenas without inbound SSR links")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    url = normalize_db_url(raw)
    try:
        assert_database_url(url, apply=False, allow_prod=bool(args.i_know_this_is_prod))
    except ProdDatabaseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.i_know_this_is_prod:
        warn_prod_ack()

    engine = create_async_engine(_normalize_async_url(async_database_url(url)))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    base = (os.environ.get("WEBAPP_BASE_URL") or "https://glide.example").rstrip("/")
    try:
        async with factory() as session:
            arenas = await _all_visible_arenas(session)
            inbound = await _collect_ssr_links(session, base=base)
    finally:
        await engine.dispose()

    orphans = [a for a in arenas if a["path"] not in inbound]
    print(f"arenas_checked={len(arenas)} inbound_paths={len(inbound)} orphans={len(orphans)}")
    for o in orphans:
        print(f"orphan id={o['id']} path={o['path']}")
    return 1 if orphans else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
