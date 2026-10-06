"""Публичная главная каталога Glide — ``/`` (TASK-191-A)."""

from __future__ import annotations

import asyncio
import html as html_lib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import _CURRENT_SESSION_SQL
from src.application.ice_city_day import city_slug, get_city_ice_day, plural_ru
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.place_links import join_public_origin, place_path
from src.shared.arena_schedule_mode import arena_schedule_mode_sql
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "catalog-home.html"
_NATIONWIDE_SESSIONS = 8

_PLACE_COUNT_SQL = text(
    f"""
    SELECT c.id, c.name, c.country, c.sort_order, COUNT(DISTINCT a.id) AS place_count
    FROM cities c
    JOIN arenas a ON a.city_id = c.id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    WHERE c.id = ANY(:city_ids)
      AND {PUBLIC_ARENA_VISIBLE_SQL}
    GROUP BY c.id, c.name, c.country, c.sort_order
    HAVING COUNT(DISTINCT a.id) > 0
    ORDER BY c.sort_order, c.id
    """
)

_UPCOMING_SQL = text(
    f"""
    SELECT c.name AS city_name,
           a.name AS arena_name,
           p.slug AS arena_slug,
           s.id AS session_id,
           s.starts_at_local,
           s.ends_at_local
    FROM ice_sessions s
    JOIN arenas a ON a.id = s.arena_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE {_CURRENT_SESSION_SQL}
      AND {PUBLIC_ARENA_VISIBLE_SQL}
      AND {arena_schedule_mode_sql()} <> 'season_closed'
    ORDER BY s.starts_at_utc, s.id
    LIMIT :lim
    """
)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value or ""), quote=True)


async def load_catalog_home_view(session: AsyncSession) -> dict[str, Any]:
    from src.application.ice_city_day import _public_cities

    now = datetime.now(timezone.utc)
    cities = await _public_cities(session)
    if not cities:
        return {"cities": [], "sessions": [], "country": "BY"}

    city_ids = [int(c["id"]) for c in cities]
    rows = (
        await session.execute(
            _PLACE_COUNT_SQL,
            {"city_ids": city_ids, **public_scope_params()},
        )
    ).mappings().all()
    async def _sessions_today(city_id: int) -> int:
        day = await get_city_ice_day(session, city_id=city_id, now=now)
        if not day.get("is_today"):
            return 0
        return int(day.get("session_count") or 0)

    session_counts = await asyncio.gather(*[_sessions_today(int(r["id"])) for r in rows])
    catalog_cities: list[dict[str, Any]] = []
    for row, session_count in zip(rows, session_counts, strict=True):
        catalog_cities.append(
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "country": str(row["country"] or ""),
                "slug": city_slug(str(row["name"])),
                "place_count": int(row["place_count"] or 0),
                "session_count": session_count,
            }
        )

    upcoming = (
        await session.execute(
            _UPCOMING_SQL,
            {"now": now, "st": STATUS_ACTIVE, "lim": _NATIONWIDE_SESSIONS, **public_scope_params()},
        )
    ).mappings().all()
    sessions = [dict(r) for r in upcoming]
    countries = {str(c.get("country") or "") for c in catalog_cities}
    country = "BY" if "BY" in countries else (next(iter(countries), "BY") if countries else "BY")
    return {"cities": catalog_cities, "sessions": sessions, "country": country}


def _city_row(city: Mapping[str, Any]) -> str:
    name = str(city["name"])
    slug = str(city["slug"])
    places = int(city["place_count"] or 0)
    sessions = int(city["session_count"] or 0)
    p_word = plural_ru(places, "место", "места", "мест")
    if sessions:
        s_word = plural_ru(sessions, "сеанс", "сеанса", "сеансов")
        stats = f"{places} {p_word} · {sessions} {s_word} сегодня"
    else:
        stats = f"{places} {p_word}"
    return (
        '<li class="city">'
        f'<h2 class="city__name"><a href="/c/{_esc(slug)}">{_esc(name)}</a></h2>'
        f'<p class="city__stats">{_esc(stats)}</p>'
        f'<p class="city__links">'
        f'<a href="/c/{_esc(slug)}">Все места</a>'
        f' · <a href="/ice/{_esc(slug)}/today">Лёд сегодня</a>'
        "</p></li>"
    )


def _session_row(row: Mapping[str, Any], *, canonical_url: str) -> str:
    city_name = str(row["city_name"])
    slug = str(row.get("arena_slug") or "").strip()
    arena_name = str(row["arena_name"])
    starts = str(row.get("starts_at_local") or "").strip()
    ends = str(row.get("ends_at_local") or "").strip()
    time_text = f"{starts}–{ends}" if starts and ends else (starts or ends or "—")
    if slug:
        href = place_path(city_name=city_name, slug=slug)
        if row.get("session_id"):
            href += f"?s={int(row['session_id'])}"
        name_html = f'<a href="{_esc(href)}">{_esc(arena_name)}</a>'
    else:
        name_html = _esc(arena_name)
    return (
        '<li class="session">'
        f'<span class="session__time">{_esc(time_text)}</span>'
        f'<span class="session__place">{name_html}</span>'
        f'<span class="session__city">{_esc(city_name)}</span>'
        "</li>"
    )


def _json_ld(view: Mapping[str, Any], *, canonical_url: str) -> str:
    elements = []
    for n, city in enumerate(view.get("cities") or []):
        slug = str(city["slug"])
        elements.append(
            {
                "@type": "ListItem",
                "position": n + 1,
                "name": city.get("name"),
                "url": join_public_origin(canonical_url, f"/c/{slug}"),
            }
        )
    graph = [
        {
            "@type": "WebSite",
            "name": "Glide",
            "url": canonical_url,
            "description": "Катки, расписание массовых катаний и лёд сегодня",
        },
        {
            "@type": "ItemList",
            "name": "Города каталога Glide",
            "itemListElement": elements,
        },
    ]
    return json_for_script({"@context": "https://schema.org", "@graph": graph})


def render_catalog_home_page(
    view: Mapping[str, Any],
    *,
    canonical_url: str,
    og_image_url: str,
    cta_url: str | None,
    trainers_url: str,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    cities = list(view.get("cities") or [])
    sessions = list(view.get("sessions") or [])
    country = str(view.get("country") or "BY")
    lang, og_locale = html_lang_for_country(country)

    title = "Катки Беларуси — расписание и города | Glide"
    description = (
        "Где покататься сегодня: города с катками, расписание массовых катаний "
        "и ссылки на все места в каталоге Glide."
    )
    cities_html = "".join(_city_row(c) for c in cities) or '<p class="muted">Пока нет опубликованных городов.</p>'
    if sessions:
        sessions_html = "<ul class=\"sessions\">" + "".join(
            _session_row(s, canonical_url=canonical_url) for s in sessions
        ) + "</ul>"
    else:
        sessions_html = '<p class="muted">Ближайших сеансов пока нет — загляните в расписание по городу.</p>'

    values = {
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(description),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_IMAGE__": _esc(og_image_url),
        "__ROBOTS__": "index, follow",
        "__JSONLD__": _json_ld(view, canonical_url=canonical_url),
        "__CITIES__": cities_html,
        "__SESSIONS__": sessions_html,
        "__TRAINERS_URL__": _esc(trainers_url),
    }
    html = fill_placeholders(template, values)
    if cta_url:
        html = html.replace("__CTA_URL__", _esc(cta_url))
    else:
        start = html.find('<a class="cta cta--secondary"')
        end = html.find("</a>", start)
        if start != -1 and end != -1:
            html = html[:start] + html[end + 4 :]
    return html


def catalog_home_og_image_url(base_url: str) -> str:
    path = "/logos/02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png"
    base = (base_url or "").strip().rstrip("/")
    if base.lower().startswith("https://"):
        return f"{base}{path}"
    return path
