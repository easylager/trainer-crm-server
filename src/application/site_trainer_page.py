"""Страница тренера на сайте ``/t/{id}-{slug}`` — пара к странице катка ``/p/{city}/{slug}``.

Одна ссылка на человека: её тренер отправляет родителям, её открывают в браузере, её находит поиск.
Логика — карточки тренера в Mini App, своих правил у сайта нет:

* кто виден людям — ``trainer_is_listed`` / ``CATALOG_LISTED_SQL`` (как ``/api/public/trainers/{id}``);
* «Записаться» — только при ``can_book`` (подписка с онлайн-записью, PDEC-025); без неё — «Написать»;
* окна — те же, что «Ближайшие окна» на карточке катка (``_trainer_windows_on_arena``), по всем площадкам.

Тренер не в каталоге (черновик, снят, пауза) — страница по его прямой ссылке открывается, но
``noindex``, её нет в sitemap и на страницах катков: «запись по вашей ссылке работает как обычно».
Деактивированного тренера нет совсем — 404.

Адрес — как у матча ``/m/{id}-{slug}``: решает id, хвост для людей; неверный хвост → 301.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import city_slug, format_price_minor, plural_ru
from src.application.place_links import place_page_url, public_telegram_cta_url, trainer_start_param
from src.application.site_trainers import trainer_initial, trainer_line, trainer_name, trainer_photo_url
from src.application.style_b import esc, section
from src.shared.catalog_visibility import CATALOG_LISTED_SQL, trainer_is_listed
from src.shared.html_template import fill_placeholders

TRAINER_PREFIX = "/t"
TRAINER_SURFACE = "trainer_page"
_B_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "b.html"
_TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
TITLE_LIMIT = 60
DESCRIPTION_LIMIT = 155
#: Сколько окон показываем на странице — дальше «все окна» в Telegram.
WINDOWS_SHOWN = 6


# ── Адрес ────────────────────────────────────────────────────────────


def trainer_slug(trainer_id: int, name: str) -> str:
    """``9-aleksandr-gaevskiy``: id решает, имя — для людей и поиска. Без имени — просто id."""
    tail = city_slug(name) if name and name != "Тренер" else ""
    return f"{int(trainer_id)}-{tail}" if tail else str(int(trainer_id))


def trainer_path(trainer_id: int, name: str) -> str:
    return f"{TRAINER_PREFIX}/{trainer_slug(trainer_id, name)}"


def trainer_page_url(base_url: str, trainer_id: int, name: str) -> str:
    return f"{(base_url or '').rstrip('/')}{trainer_path(trainer_id, name)}"


def parse_trainer_ref(ref: str) -> int | None:
    head = (ref or "").split("-", 1)[0]
    return int(head) if head.isdigit() and 0 < int(head) < 2**31 else None


# ── Данные ───────────────────────────────────────────────────────────


def _service_price(svc: Mapping[str, Any]) -> str:
    """«от 50 BYN» / «50 BYN» / пусто — как цена услуги на карточке Mini App."""
    cur = str(svc.get("currency_code") or "BYN")
    lo, hi = svc.get("price_byn_min"), svc.get("price_byn_max")
    if lo is None:
        lo = hi = svc.get("price_byn")
    if lo is None:
        return ""
    price = format_price_minor(int(round(float(lo) * 100)), cur).replace(" ", " ")
    return price if hi is None or float(hi) == float(lo) else "от " + price


def contact_url(trainer_id: int, telegram_username: str | None, *, listed: bool) -> str | None:
    """«Написать в Telegram»: у тренера в каталоге — учётный ``/r/tg/{id}``, иначе прямой ``t.me``.

    Тот же выбор, что ``contact_telegram_url`` у ``/api/public/trainers/{id}``: ``/r/tg`` отвечает 404
    всем, кого нет в каталоге.
    """
    handle = (telegram_username or "").strip().lstrip("@")
    if not handle or not _TELEGRAM_USERNAME_RE.fullmatch(handle):
        return None
    return f"/r/tg/{int(trainer_id)}" if listed else f"https://t.me/{handle}"


async def _arenas(session: AsyncSession, trainer_id: int) -> list[dict[str, Any]]:
    """Площадки тренера, которые он показывает клиентам; у катка со страницей — ссылка на ``/p/…``."""
    from src.application.indexnow import SITEMAP_PLACE_WHERE_SQL
    from src.shared.ice_discovery_scope import public_scope_params

    rows = (
        await session.execute(
            text(
                f"""
                SELECT a.id, a.name, c.name AS city_name,
                       CASE WHEN {SITEMAP_PLACE_WHERE_SQL} THEN p.slug END AS slug
                FROM trainer_arenas ta
                JOIN arenas a ON a.id = ta.arena_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                LEFT JOIN cities c ON c.id = a.city_id
                WHERE ta.trainer_id = :tid AND COALESCE(ta.is_public, true) AND a.merged_into_arena_id IS NULL
                ORDER BY a.sort_order NULLS LAST, a.id
                """
            ),
            {"tid": int(trainer_id), **public_scope_params()},
        )
    ).mappings().all()
    return [
        {
            "id": int(r["id"]),
            "name": str(r["name"] or "").strip(),
            "city_name": str(r["city_name"] or "").strip(),
            "slug": r["slug"],
        }
        for r in rows
        if str(r["name"] or "").strip()
    ]


async def _city_name(session: AsyncSession, city_id: Any) -> str:
    if not city_id:
        return ""
    row = (await session.execute(text("SELECT name FROM cities WHERE id = :id"), {"id": int(city_id)})).first()
    return str(row[0]) if row and row[0] else ""


async def load_trainer_page(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """Всё для ``/t/…`` или ``None`` (нет такого тренера или он деактивирован)."""
    from src.application.arena_public_use_cases import _trainer_windows_on_arena
    from src.application.subscription_tier_use_cases import get_trainer_booking_availability
    from src.application.trainer_min_price import enrich_min_session_price
    from src.application.trainer_use_cases import get_trainer
    from src.shared.notification_hours import NOTIFICATION_TZ
    from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog

    raw = await get_trainer(session, int(trainer_id))
    if not raw or str(raw.get("status") or "").strip().lower() == "deactivated":
        return None
    listed = trainer_is_listed(raw)
    username = (
        await session.execute(text("SELECT telegram_username FROM trainers WHERE id = :id"), {"id": int(trainer_id)})
    ).scalar()
    body = sanitize_trainer_for_public_catalog(raw)
    await enrich_min_session_price(session, [body])
    availability = await get_trainer_booking_availability(session, int(trainer_id))
    can_book = bool(availability.get("can_book"))
    profile = body.get("profile") or {}
    windows: list[dict[str, Any]] = []
    if can_book:
        windows = (
            await _trainer_windows_on_arena(session, None, [int(trainer_id)], timezone_name=NOTIFICATION_TZ)
        ).get(int(trainer_id), [])
    name = trainer_name(body)
    return {
        "id": int(trainer_id),
        "name": name,
        "initial": trainer_initial(name),
        "photo_url": trainer_photo_url(body),
        "line": trainer_line(body),
        "listed": listed,
        "can_book": can_book,
        "contact_url": contact_url(int(trainer_id), username, listed=listed),
        "city_name": await _city_name(session, profile.get("city_id")),
        "experience_years": profile.get("experience_years"),
        "description": str(profile.get("description") or "").strip(),
        "rating_avg": profile.get("rating_avg"),
        "rating_count": int(profile.get("rating_count") or 0),
        "services": [
            {"name": str(s.get("service_name") or "").strip(), "price": _service_price(s)}
            for s in body.get("services") or []
            if str(s.get("service_name") or "").strip()
        ],
        "arenas": await _arenas(session, int(trainer_id)),
        "windows": windows[:WINDOWS_SHOWN],
        "path": trainer_path(int(trainer_id), name),
    }


async def sitemap_rows(session: AsyncSession) -> list[str]:
    """Пути ``/t/…`` всех, кто в каталоге — тот же предикат, что у списка тренеров в Mini App."""
    rows = (
        await session.execute(
            text(
                f"""
                SELECT t.id, COALESCE(p.first_name, ''), COALESCE(p.last_name, '')
                FROM trainers t LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
                WHERE {CATALOG_LISTED_SQL}
                ORDER BY t.id
                """
            )
        )
    ).all()
    out = []
    for tid, first, last in rows:
        name = f"{str(first).strip()} {str(last).strip()}".strip() or "Тренер"
        out.append(trainer_path(int(tid), name))
    return out


# ── Ссылка, которой тренер делится ───────────────────────────────────

#: Метка ссылки из кабинета: человек пришёл от самого тренера — кнопка ведёт через ``welcome_ref``.
SHARE_VIA = "link"
#: Метка «Поделиться тренером» из Mini App: клиент советует другу — кнопка ведёт через ``share_ref``.
RECOMMEND_VIA = "share"


def share_url(base_url: str, trainer_id: int, name: str, *, via: str = SHARE_VIA) -> str | None:
    """``https://glideclub.by/t/9-aleksandr-gaevskiy?via=link`` — только на настоящем https-адресе сайта."""
    base = (base_url or "").strip().rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    return f"{trainer_page_url(base, trainer_id, name)}?via={via}"


async def trainer_invite_link(session: AsyncSession, trainer_id: int) -> tuple[str | None, str | None]:
    """Ссылка тренера ученикам — страница сайта ``/t/…`` (TASK-350), а не ``t.me``.

    Контракт ``build_trainer_universal_invite_link``: ``(ссылка, ошибка)``. Без https-адреса сайта
    (локально) — прежняя ``t.me/…?start=welcome_ref_{id}``. Кнопка на странице по ``via=link`` ведёт
    туда же, через ``welcome_ref``: бот привязывает и регистрирует ученика, как раньше.
    """
    from src.application.trainer_invite_links import build_trainer_universal_invite_link
    from src.shared.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    fallback, err = build_trainer_universal_invite_link(
        client_bot_username=settings.client_bot_username, trainer_id=int(trainer_id)
    )
    if err:
        return None, err
    return await site_share_link(session, int(trainer_id), via=SHARE_VIA) or fallback, None


async def site_share_link(session: AsyncSession, trainer_id: int, *, via: str) -> str | None:
    """Канонический ``/t/…?via=…`` по имени из профиля (не по подписи вроде «Анна К.» — без лишнего 301)."""
    from src.shared.config import Settings

    row = (
        await session.execute(
            text("SELECT first_name, last_name FROM trainer_profiles WHERE trainer_id = :id"), {"id": int(trainer_id)}
        )
    ).first()
    name = " ".join(str(v or "").strip() for v in (row or ())).strip()
    return share_url(Settings().webapp_base_url or "", int(trainer_id), name, via=via)  # type: ignore[call-arg]


# ── Ссылки в Telegram ────────────────────────────────────────────────


def app_url(
    base_url: str, page: Mapping[str, Any], *, client_bot_username: str | None, via: str | None = None
) -> str | None:
    """Куда ведёт «Записаться в Telegram»: карточка тренера в Mini App.

    В каталоге — через учётный ``/api/public/catalog/open-telegram`` (``trainer_{id}``). Пришли по
    ссылке самого тренера (``via=link``) или тренера нет в каталоге — постоянная ссылка
    ``welcome_ref_{id}``: бот привяжет человека к тренеру, как раньше по ссылке из кабинета
    (карточка Mini App незнакомому клиенту скрытого тренера отвечает 404).
    """
    if via == RECOMMEND_VIA:
        from src.application.trainer_invite_links import build_trainer_share_link

        rec, _err = build_trainer_share_link(
            webapp_base_url=base_url, client_bot_username=client_bot_username, trainer_id=int(page["id"])
        )
        if rec is not None:
            return rec.bot_deep_link
    if page["listed"] and via != SHARE_VIA:
        return public_telegram_cta_url(
            base_url, start_param=trainer_start_param(int(page["id"])), surface=TRAINER_SURFACE
        )
    from src.application.trainer_invite_links import build_trainer_universal_invite_link

    link, _err = build_trainer_universal_invite_link(
        client_bot_username=client_bot_username, trainer_id=int(page["id"])
    )
    return link


def primary_cta(
    base_url: str, page: Mapping[str, Any], *, client_bot_username: str | None, via: str | None = None
) -> tuple[str, str] | None:
    """(подпись, адрес) главной кнопки. Подпись не обещает того, чего нет: без подписки — «Написать»."""
    app = app_url(base_url, page, client_bot_username=client_bot_username, via=via)
    if page["can_book"] and app:
        return "Записаться в Telegram", app
    if page.get("contact_url"):
        return "Написать в Telegram", str(page["contact_url"])
    if app:
        return "Открыть в Telegram", app
    return None


# ── Вёрстка ──────────────────────────────────────────────────────────


def _rating_text(page: Mapping[str, Any]) -> str:
    avg, n = page.get("rating_avg"), int(page.get("rating_count") or 0)
    if not avg or n <= 0:
        return ""
    return f"★ {float(avg):.1f}".replace(".", ",") + f" · {n} {plural_ru(n, 'отзыв', 'отзыва', 'отзывов')}"


def _experience_text(page: Mapping[str, Any]) -> str:
    years = page.get("experience_years")
    if not years or int(years) <= 0:
        return ""
    y = int(years)
    return f"опыт {y} {plural_ru(y, 'год', 'года', 'лет')}"


def page_title(page: Mapping[str, Any]) -> str:
    name = str(page["name"])
    city = str(page.get("city_name") or "")
    first_service = (page.get("services") or [{}])[0].get("name") if page.get("services") else ""
    candidates = [
        f"{name} — тренер{', ' + city if city else ''} · Glideclub",
        f"{name} — тренер · Glideclub",
        name,
    ]
    if first_service:
        candidates.insert(0, f"{name} — {first_service}{', ' + city if city else ''} · Glideclub")
    for c in candidates:
        if len(c) <= TITLE_LIMIT:
            return c
    return candidates[-1][:TITLE_LIMIT]


def page_description(page: Mapping[str, Any]) -> str:
    bits = [str(page["name"]), "тренер"]
    arenas = [a["name"] for a in page.get("arenas") or []]
    if arenas:
        bits.append("занимается: " + ", ".join(arenas[:3]))
    line = str(page.get("line") or "")
    if line:
        bits.append(line.replace(" ", " "))
    tail = "Запись в Telegram, ничего не устанавливая." if page.get("can_book") else "Написать тренеру в Telegram."
    text_ = ". ".join([" — ".join(bits[:2])] + bits[2:]) + ". " + tail
    return text_ if len(text_) <= DESCRIPTION_LIMIT else text_[: DESCRIPTION_LIMIT - 1].rstrip() + "…"


def jsonld(page: Mapping[str, Any], *, canonical: str, base_url: str) -> str:
    person: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": page["name"],
        "url": canonical,
        "jobTitle": "Тренер по катанию",
    }
    if page.get("photo_url"):
        person["image"] = _absolute(base_url, str(page["photo_url"]))
    if page.get("description"):
        person["description"] = str(page["description"])[:300]
    if page.get("city_name"):
        person["address"] = {"@type": "PostalAddress", "addressLocality": page["city_name"]}
    places = [
        {"@type": "SportsActivityLocation", "name": a["name"], "url": place_page_url(base_url=base_url, city_name=a["city_name"], slug=a["slug"])}
        for a in page.get("arenas") or []
        if a.get("slug") and a.get("city_name")
    ]
    if places:
        person["workLocation"] = places
    payload = json.dumps(person, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{payload}</script>'


def _absolute(base_url: str, url: str) -> str:
    return url if url.startswith("http") else f"{(base_url or '').rstrip('/')}{url}"


def _hero(page: Mapping[str, Any]) -> str:
    photo = page.get("photo_url")
    ava = (
        f'<img class="tp-ava" src="{esc(photo)}" alt="" width="96" height="96" decoding="async" />'
        if photo
        else f'<span class="tp-ava tp-ava--mono" aria-hidden="true">{esc(page["initial"])}</span>'
    )
    facts = [f for f in (_experience_text(page), _rating_text(page)) if f]
    city = str(page.get("city_name") or "")
    kicker = "Тренер" + (f" · {city}" if city else "")
    facts_html = f'<p class="tp-facts">{esc(" · ".join(facts))}</p>' if facts else ""
    return (
        '<header class="tp-hero">'
        '<div class="tp-bar"><a class="b-brand" href="/">Glideclub</a></div>'
        f'<div class="tp-head">{ava}<div><p class="tp-kicker">{esc(kicker)}</p>'
        f'<h1 class="tp-name">{esc(page["name"])}</h1>{facts_html}</div></div></header>'
    )


def _cta_html(cta: tuple[str, str] | None, *, note: str = "") -> str:
    if not cta:
        return ""
    label, href = cta
    note_html = f'<p class="tp-note">{esc(note)}</p>' if note else ""
    return (
        f'<div class="tp-cta"><a class="b-tgbtn tp-cta__btn" href="{esc(href)}" rel="nofollow">{esc(label)}</a>'
        f"{note_html}</div>"
    )


def _arena_names(page: Mapping[str, Any]) -> dict[int, str]:
    return {int(a["id"]): str(a["name"]) for a in page.get("arenas") or []}


def _windows_html(page: Mapping[str, Any], href: str | None) -> str:
    wins = page.get("windows") or []
    if not wins or not href:
        return ""
    names = _arena_names(page)
    rows = []
    for w in wins:
        where = names.get(int(w["arena_id"])) if w.get("arena_id") is not None else ""
        rows.append(
            f'<a class="b-row tp-win" href="{esc(href)}" rel="nofollow">'
            f'<span class="b-row__body"><span class="b-row__title">{esc(w["day"])}, {esc(w["time"])}</span>'
            + (f'<span class="b-row__line">{esc(where)}</span>' if where else "")
            + '</span><span class="b-row__cta">Записаться</span></a>'
        )
    return section("Свободные окна", f'<div class="b-list">{"".join(rows)}</div>', nosnippet=True)


def _services_html(page: Mapping[str, Any]) -> str:
    rows = [
        f'<div class="b-row"><span class="b-row__body"><span class="b-row__title">{esc(s["name"])}</span></span>'
        + (f'<span class="b-row__cta tp-price">{esc(s["price"])}</span>' if s.get("price") else "")
        + "</div>"
        for s in page.get("services") or []
    ]
    return section("Занятия и цены", f'<div class="b-list">{"".join(rows)}</div>') if rows else ""


def _arenas_html(page: Mapping[str, Any], base_url: str) -> str:
    rows = []
    for a in page.get("arenas") or []:
        if a.get("slug") and a.get("city_name"):
            href = place_page_url(base_url=base_url, city_name=a["city_name"], slug=a["slug"])
            rows.append(
                f'<a class="b-row" href="{esc(href)}"><span class="b-row__body"><span class="b-row__title">{esc(a["name"])}</span>'
                '<span class="b-row__line">Расписание катка и тренеры</span></span><span class="b-row__cta">›</span></a>'
            )
        else:
            rows.append(f'<div class="b-row"><span class="b-row__body"><span class="b-row__title">{esc(a["name"])}</span></span></div>')
    return section("Где занимается", f'<div class="b-list">{"".join(rows)}</div>') if rows else ""


def _about_html(page: Mapping[str, Any]) -> str:
    desc = str(page.get("description") or "")
    return section("О тренере", f'<p class="tp-about">{esc(desc)}</p>') if desc else ""


def _trainer_hook() -> str:
    """Тренер среди родителей — тоже вход в Glide (trainer-acquisition, канал 3)."""
    return (
        '<p class="tp-hook"><a href="/trainers?utm_source=glide&amp;utm_medium=trainer_page">'
        "Вы тренер? Ведите запись так же — бесплатная страница и ссылка для учеников ›</a></p>"
    )


def render_trainer_page(
    page: Mapping[str, Any], *, base_url: str, client_bot_username: str | None, via: str | None = None
) -> str:
    from src.application.catalog_home_page import catalog_home_og_image_url
    from src.application.place_links import breadcrumb_script
    from src.application.public_analytics import public_analytics_head_html_from_settings
    from src.application.public_site_footer import render_site_footer_html
    from src.application.public_web_cta import public_page_view_beacon_script
    from src.application.catalog_list_share import catalog_list_share_tail
    from src.application.style_b import COMPONENTS_VERSION, STYLE_VERSION, TOKENS_VERSION, public_fonts_head_html

    canonical = f"{(base_url or '').rstrip('/')}{page['path']}"
    cta = primary_cta(base_url, page, client_bot_username=client_bot_username, via=via)
    app = app_url(base_url, page, client_bot_username=client_bot_username, via=via)
    note = "Откроется Glide в Telegram — ничего устанавливать не нужно." if page["can_book"] else ""
    body = (
        _hero(page)
        + '<main class="tp-body">'
        + _cta_html(cta, note=note)
        + (_windows_html(page, app) if page["can_book"] else "")
        + _services_html(page)
        + _arenas_html(page, base_url)
        + _about_html(page)
        + _trainer_hook()
        + "</main>"
    )
    crumbs = [("Glideclub", f"{(base_url or '').rstrip('/')}/")]
    if page.get("city_name"):
        crumbs.append((str(page["city_name"]), f"{(base_url or '').rstrip('/')}/c/{city_slug(str(page['city_name']))}"))
    crumbs.append((str(page["name"]), canonical))
    body += breadcrumb_script(canonical, crumbs)
    og_image = _absolute(base_url, str(page["photo_url"])) if page.get("photo_url") else catalog_home_og_image_url(base_url)
    tail = catalog_list_share_tail(scripts=False)
    tail["__PLACE_SHARE_BAR__"] = ""
    title = page_title(page)
    description = page_description(page)
    return fill_placeholders(
        _B_TEMPLATE_PATH.read_text(encoding="utf-8"),
        {
            "__OG_TITLE__": esc(title),
            "__OG_DESCRIPTION__": esc(description),
            "__DESCRIPTION__": esc(description),
            "__CANONICAL__": esc(canonical),
            "__OG_URL__": esc(canonical),
            "__OG_IMAGE__": esc(og_image),
            "__LANG__": "ru",
            "__OG_LOCALE__": "ru_RU",
            "__ROBOTS__": "index, follow" if page["listed"] else "noindex, follow",
            "__HEAD_EXTRA__": f'<link rel="stylesheet" href="/static/share/trainer-page.css?v={TRAINER_PAGE_STYLE_VERSION}" />',
            "__JSONLD__": jsonld(page, canonical=canonical, base_url=base_url) if page["listed"] else "",
            "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
            "__PUBLIC_ANALYTICS_HEAD__": public_analytics_head_html_from_settings(),
            "__TOKENS_V__": TOKENS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__COMPONENTS_V__": COMPONENTS_VERSION,
            "__SITE_FOOTER__": render_site_footer_html(
                context_html='<div class="elsewhere"><a href="/">Массовое катание по всей Беларуси</a></div>',
            ),
            "__BODY__": body,
            "__PAGE_VIEW_BEACON__": public_page_view_beacon_script(surface=TRAINER_SURFACE, city_id=None),
            "__GLIDE_CITY_PIN__": "",
            **tail,
        },
    )


TRAINER_PAGE_STYLE_VERSION = "2026110602"
