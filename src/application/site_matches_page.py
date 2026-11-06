"""HTML матчей на сайте (TASK-347): лента города, строка арены, список «Хоккей», страница матча.

Вёрстка — по холсту «Сайт: матчи и зимний лёд», экраны 1–5; стили — ``static/share/matches.css`` на
токенах ``glide-tokens.css``. Данные — ``site_matches``. Слов «ставка», «коэффициент», «прогноз» здесь
нет (стережёт ``test_site_matches_words``), название лиги — наше, не из источника.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.application.catalog_icons import icon_svg
from src.application.ice_city_day import city_slug, plural_ru
from src.application.place_links import (
    match_start_param,
    public_telegram_cta_url,
    telegram_bot_start_link,
)
from src.application.site_matches import (
    LEAGUE_EXTRALIGA,
    MATCH_PREFIX,
    PHASE_AFTER,
    PHASE_BEFORE,
    PHASE_LIVE,
    PHASE_REVIEW,
    PHASE_WAIT,
    SITE_PATH,
    WEEKDAYS_FULL,
    WEEKDAYS_SHORT,
    day_word,
    local,
    score_text,
    when_text,
    yandex_link,
)
from src.application.hockey_teams import display_name
from src.shared.city_locative import city_locative
from src.shared.config import Settings
from src.shared.copy_ru import t
from src.shared.html_template import fill_placeholders, json_for_script, safe_external_url
from src.shared.public_display import format_public_name

MATCH_SURFACE = "match_page"
BELL_PREFIX = "mbell_"
_B_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "b.html"
_PAGE_CACHE_FAR = "public, max-age=60, stale-while-revalidate=300"
TITLE_LIMIT = 60
DESCRIPTION_LIMIT = 155


def _e(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


# ── Ссылки в Telegram ────────────────────────────────────────────────


def bell_param(match_id: int) -> str:
    return f"{BELL_PREFIX}{int(match_id)}"


def bell_link(base_url: str, match_id: int, *, city_id: int | None = None) -> str | None:
    """Колокольчик → чат бота (``/start mbell_<id>``). Через учёт кликов; без HTTPS — прямая ссылка на бота."""
    param = bell_param(match_id)
    proxied = public_telegram_cta_url(base_url, start_param=param, surface=MATCH_SURFACE, city_id=city_id)
    if proxied:
        return proxied
    return telegram_bot_start_link(client_bot_username=Settings().client_bot_username, start_param=param)  # type: ignore[call-arg]


def game_link(base_url: str, match_id: int, *, city_id: int | None = None) -> str | None:
    """«Кто кого» → Mini App на матче (``startapp=kkm_<id>``)."""
    return public_telegram_cta_url(
        base_url, start_param=match_start_param(match_id), surface=MATCH_SURFACE, city_id=city_id
    )


def ics_path(card: Mapping[str, Any]) -> str:
    return f"{card['path']}/calendar.ics"


# ── Кирпичики ────────────────────────────────────────────────────────


def logo(team: Mapping[str, Any], size: str = "") -> str:
    """Белый круг с логотипом клуба; у команды без логотипа (КХЛ) — две буквы."""
    klass = "m-logo" + (f" m-logo--{size}" if size else "")
    if team.get("logo"):
        return f'<span class="{klass}"><img src="{_e(team["logo"])}" alt="" width="30" height="30" loading="lazy"></span>'
    return f'<span class="{klass}">{_e(team.get("short") or "")}</span>'


def _band(card: Mapping[str, Any]) -> str:
    result = card.get("result")
    mid = score_text(result).replace(" ОТ", "").replace(" Б", "") if result else card["time"]
    if card["phase"] == PHASE_LIVE:
        mid = "идёт"
    return (
        '<span class="m-band">'
        f'<span style="background:{_e(card["home"]["color"])}"></span>'
        f'<span style="background:{_e(card["away"]["color"])}"></span>'
        '<span class="m-band__mid">'
        f'{logo(card["home"])}<span class="m-band__time">{_e(mid)}</span>{logo(card["away"])}'
        "</span></span>"
    )


def sheet_html() -> str:
    """Шторка перед уходом в Telegram: что произойдёт после нажатия. Наполняется из matches.js."""
    return (
        '<dialog class="b-sheet" id="mSheet" aria-labelledby="mSheetTitle">'
        '<div class="b-sheet__in" tabindex="-1" autofocus>'
        '<button type="button" class="b-sheet__x" data-sheet-close aria-label="Закрыть">'
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>'
        '<h2 class="b-sheet__title" id="mSheetTitle"></h2>'
        '<p class="b-sheet__text" data-m-text></p>'
        '<ul class="m-sheet-list" data-m-list></ul>'
        '<a class="m-sheet__go" data-m-go href="#" rel="nofollow">'
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M21.5 4.2 2.9 11.4c-1.2.5-1.2 1.2 0 1.5l4.7 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.5l2.3-2.2 '
        '4.8 3.5c.9.5 1.5.2 1.7-.8l3.1-14.7c.3-1.3-.5-1.9-1.6-1.4z"/></svg>Открыть Telegram</a>'
        '<a class="b-sheet__alt" data-m-alt href="#" hidden>Без Telegram — добавить в календарь</a>'
        "</div></dialog>"
    )


def head_extra() -> str:
    from src.application.style_b import MATCHES_STYLE_VERSION

    return f'<link rel="stylesheet" href="/static/share/matches.css?v={MATCHES_STYLE_VERSION}" />'


def scripts_html() -> str:
    from src.application.style_b import MATCHES_SCRIPT_VERSION

    return f'<script defer src="/static/share/matches.js?v={MATCHES_SCRIPT_VERSION}"></script>'


def assets_tail() -> str:
    """Шторка и скрипт — один раз в конец страницы, где есть колокольчик или «Кто кого»."""
    return sheet_html() + scripts_html()


def _bell_attrs(card: Mapping[str, Any]) -> str:
    return (
        f' data-m-sheet="bell" data-m-name="{_e(card["title"])}"'
        f' data-m-when="{_e(_when_label(card))}"'
        f' data-m-ics="{_e(ics_path(card))}"'
    )


def _when_label(card: Mapping[str, Any]) -> str:
    return f"{WEEKDAYS_SHORT[card['day'].weekday()]} {card['time']}"


# ── Лента города ─────────────────────────────────────────────────────


def _feed_card(card: Mapping[str, Any], *, base_url: str, today: Any, city_id: int | None) -> str:
    sub = " · ".join(
        bit for bit in (day_word(card["day"], today), card["arena"], card["league_label"]) if bit
    )
    href = card["path"]
    bell = ""
    if card["phase"] == PHASE_BEFORE:
        link = bell_link(base_url, card["id"], city_id=city_id)
        if link:
            bell = (
                f'<a class="m-bell" href="{_e(link)}" rel="nofollow"{_bell_attrs(card)} '
                f'aria-label="Напомнить о матче {_e(card["title"])}">{icon_svg("bell")}</a>'
            )
    return (
        '<div class="m-card">'
        f'<a class="m-card__link" href="{_e(href)}">{_band(card)}'
        f'<span class="m-card__body"><span class="m-card__title">{_e(card["title"])}</span>'
        f'<span class="m-card__sub">{_e(sub)}</span></span></a>{bell}</div>'
    )


def feed_title(feed: Mapping[str, Any], city_name: str) -> str:
    where = city_locative(city_name)
    return f"Хоккей в {where}" if where else f"Хоккей — {format_public_name(city_name)}"


def list_href(city_name: str | None = None, club: str | None = None) -> str:
    from urllib.parse import urlencode

    params = {k: v for k, v in (("city", city_slug(city_name) if city_name else None), ("club", club)) if v}
    return SITE_PATH + (f"?{urlencode(params)}" if params else "")


def feed_section(feed: Mapping[str, Any] | None, *, city_name: str, base_url: str, city_id: int | None) -> str:
    """«Хоккей в Минске» под «Лёд сегодня»: матчи, которые идут в этом городе. Нет матчей на неделе —
    честная строка и ближайший матч; в городе матчей нет совсем — нет блока."""
    if not feed:
        return ""
    from src.application.style_b import section

    today = feed["today"]
    if feed.get("empty"):
        nxt = feed["next"]
        note = f"{empty_line(feed, city_name)}"
        return section(
            feed_title(feed, city_name),
            f'<p class="m-feed-empty">{_e(note)}</p>'
            f'<div class="b-scroll">{_feed_card(nxt, base_url=base_url, today=today, city_id=city_id)}</div>',
            aside_html=f'<a class="b-more" href="{_e(list_href(city_name))}">Все матчи</a>',
            klass="b-sec--flush",
            sec_id="hockey",
        ) + assets_tail()
    cards = "".join(_feed_card(c, base_url=base_url, today=today, city_id=city_id) for c in feed["matches"])
    n = int(feed["week_count"])
    more = (
        f'<a class="b-more" href="{_e(list_href(city_name))}">'
        f'{n} {plural_ru(n, "матч", "матча", "матчей")}</a>'
    )
    return section(
        feed_title(feed, city_name),
        f'<div class="b-scroll">{cards}</div>',
        aside_html=more,
        klass="b-sec--flush",
        sec_id="hockey",
    ) + assets_tail()


def empty_line(feed: Mapping[str, Any], city_name: str) -> str:
    """«В Минске до 10 ноября матчей нет» — честно, когда на неделе в городе ничего не идёт."""
    nxt = feed["next"]
    day = nxt["day"]
    where = city_locative(city_name)
    head = f"В {where}" if where else format_public_name(city_name)
    return f"{head} до {day.day} {_months(day.month)} матчей нет"


def route_row_line(feed: Mapping[str, Any]) -> str:
    first = feed["first"]
    if feed.get("empty"):
        day = first["day"]
        return f"до {day.day} {_months(day.month)} матчей нет · ближайший — {first['title']}"
    n = int(feed["city_count"])
    base = f"{n} {plural_ru(n, 'матч', 'матча', 'матчей')} на неделе"
    word = feed.get("first_word")
    return f"{base} · {word} {first['title']}" if word else base


# ── Расписание арены ─────────────────────────────────────────────────


def arena_ticket(card: Mapping[str, Any], note: str) -> str:
    """Тёмная строка матча в списке сеансов дня (экран 3): «19:00 · Юность — Шахтёр · Матч ›»."""
    return (
        f'<a class="b-ticket b-ticket--dark m-ticket" href="{_e(card["path"])}">'
        f'<span class="b-ticket__time">{_e(card["time"])}</span>'
        '<span class="m-ticket__body"><span class="m-ticket__names">'
        f'<span class="m-logos">{logo(card["home"], "xs")}{logo(card["away"], "xs")}</span>'
        f'<span>{_e(card["title"])}</span></span>'
        f'<span class="b-ticket__sub">{_e(note)}</span></span>'
        '<span class="b-ticket__go">Матч ›</span></a>'
    )


def here_section(matches: list[Mapping[str, Any]], *, today: Any) -> str:
    """«Матчи здесь» — ближайшие три матча арены."""
    if not matches:
        return ""
    from src.application.style_b import section

    rows = "".join(
        f'<a class="m-here__row" href="{_e(m["path"])}">'
        f'<span class="m-here__when">{_e(WEEKDAYS_SHORT[m["day"].weekday()])} {m["day"].day}<br>{_e(m["time"])}</span>'
        f'<span class="m-here__name">{_e(m["title"])}</span><span class="m-here__go">›</span></a>'
        for m in matches[:3]
    )
    return section("Матчи здесь", f'<div class="m-here">{rows}</div>', klass="b-sec--place", sec_id="matches")


# ── Список «Хоккей» ──────────────────────────────────────────────────


def _row(m: Mapping[str, Any]) -> str:
    score = score_text(m["result"]) if m.get("result") else ""
    right = f'<span class="m-row__go">{_e(score)} ›</span>' if score else '<span class="m-row__go">›</span>'
    where = m.get("venue") or m["where"]
    if m["league"] != LEAGUE_EXTRALIGA:
        where = f"{where} · {m['league_label']}" if where else m["league_label"]
    klass = "m-row m-row--mine" if m.get("mine") else "m-row"
    return (
        f'<a class="{klass}" href="{_e(m["path"])}"><span class="m-row__time">{_e(m["time"])}</span>'
        f'<span class="m-row__main"><span class="m-logos">{logo(m["home"], "sm")}{logo(m["away"], "sm")}</span>'
        f'<span class="m-row__text"><span class="m-row__name">{_e(m["title"])}</span>'
        f'<span class="m-row__where">{_e(where)}</span></span></span>{right}</a>'
    )


def list_title(data: Mapping[str, Any]) -> str:
    return "Хоккей в Беларуси — матчи Экстралиги и Динамо-Минск | Glideclub"


def list_description() -> str:
    return (
        "Расписание хоккейных матчей Экстралиги и Динамо-Минск по дням: время, арена, билеты, "
        "как добраться и где покататься рядом."
    )


def render_matches_list(
    data: Mapping[str, Any], *, base_url: str, city_name: str | None, city_id: int | None, noindex: bool = False
) -> str:
    canonical = f"{base_url}{SITE_PATH}"
    chips = [
        '<a class="m-chip" href="{h}" aria-current="{cur}">Все</a>'.format(
            h=_e(list_href(city_name)), cur="true" if not data["club"] else "false"
        )
    ]
    for club in data["clubs"]:
        cur = "true" if data["club"] == club["slug"] else "false"
        chips.append(
            f'<a class="m-chip m-chip--logo" href="{_e(list_href(city_name, club["slug"]))}" aria-current="{cur}">'
            f'{logo({"logo": club["logo"], "short": club["name"][:2]}, "sm")}{_e(club["name"])}</a>'
        )
    def day_blocks(day_list: list[Mapping[str, Any]]) -> str:
        out = ""
        for day in day_list:
            rows = "".join(_row(m) for m in day["items"])
            out += f'<section class="m-day"><h2 class="m-day__h">{_e(day["label"])}</h2>{rows}</section>'
        return out

    days = ""
    if data.get("sections"):
        for sec in data["sections"]:
            days += f'<h2 class="m-sec">{_e(sec["title"])}</h2>' + day_blocks(sec["days"])
    else:
        days = day_blocks(data["days"])
    if not data["days"]:
        text = "Матчей пока нет."
    elif data["pause"]:
        first = data["first_day"]
        text = f"На этой неделе матчей нет — ближайшие с {first.day} {_months(first.month)}."
    else:
        text = ""
    back = ""
    if city_name:
        back = f'<a class="m-back" href="/c/{_e(city_slug(city_name))}">‹ {_e(format_public_name(city_name))}</a>'
    first_line = "Экстралига и Динамо-Минск"
    if data["club"]:
        first_line = "Все матчи клуба — дома и на выезде"
    body = (
        f'<div class="m-top">{back}<h1 class="m-title">Хоккей</h1><p class="m-lead">{_e(first_line)}</p>'
        f'<nav class="m-chips" aria-label="Клуб">{"".join(chips)}</nav></div>'
        + (f'<p class="m-empty">{_e(text)}</p>' if text else "")
        + f'<div class="m-days">{days}</div>'
    )
    # Фильтр по клубу и город из адреса — варианты той же страницы: канон на /hockey, в индекс не идут.
    robots = "noindex, follow" if noindex else "index, follow"
    return _page(
        title=list_title(data),
        description=list_description(),
        canonical=canonical,
        og_url=canonical,
        og_image=_default_og(base_url),
        robots=robots,
        jsonld="{}",
        body=body,
        base_url=base_url,
        city_id=city_id,
        city_slug_value=city_slug(city_name) if city_name else "",
        surface="matches_list",
    )


def _months(month: int) -> str:
    from src.application.site_matches import MONTHS_GEN

    return MONTHS_GEN[month - 1]


# ── Страница матча ───────────────────────────────────────────────────


def _fit(candidates: list[str], limit: int) -> str:
    """Первый вариант, влезающий в лимит; иначе последний, обрезанный по границе слова."""
    for text in candidates:
        if len(text) <= limit:
            return text
    text = candidates[-1]
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,·—-")
    return cut + "…"


def match_title(data: Mapping[str, Any]) -> str:
    m = data["match"]
    teams = m["title"]
    day = f"{m['day'].day} {_months(m['day'].month)}"
    arena = data["arena_name"]
    if data["gone"]:
        return _fit([f"{teams}: матч перенесён или отменён", teams], TITLE_LIMIT)
    if data.get("away_trip") and m["phase"] == PHASE_BEFORE:
        return _fit([f"{teams} {day}, {m['time']} · выезд Динамо", f"{teams} {day}, {m['time']}", teams], TITLE_LIMIT)
    phase = m["phase"]
    if phase == PHASE_AFTER:
        score = score_text(m["result"])
        return _fit([f"{teams} {score}, {day} · голы и итог", f"{teams} {score}, {day}", teams], TITLE_LIMIT)
    if phase == PHASE_LIVE:
        return _fit([f"{teams} сегодня: идёт матч", teams], TITLE_LIMIT)
    if phase in (PHASE_WAIT, PHASE_REVIEW):
        return _fit([f"{teams} {day}: матч завершён", teams], TITLE_LIMIT)
    return _fit(
        [f"{teams} {day}, {m['time']} · билеты, {arena}", f"{teams} {day}, {m['time']} · билеты", f"{teams} {day}, {m['time']}", teams],
        TITLE_LIMIT,
    )


def _standing_phrase(data: Mapping[str, Any]) -> str:
    pv = data.get("preview") or {}
    bits = []
    for side in ("home", "away"):
        block = pv.get(side) or {}
        if block.get("place") is not None and block.get("points") is not None:
            bits.append(f"{block['team']} — {block['place']}-е место, {block['points']} {_points(block['points'])}")
    return "; ".join(bits)


def _points(n: int) -> str:
    return plural_ru(int(n), "очко", "очка", "очков")


def match_description(data: Mapping[str, Any]) -> str:
    m = data["match"]
    league = m["league_label"]
    where = ", ".join(bit for bit in (data["arena_name"], data["city"]) if bit)
    when = f"{m['day'].day} {_months(m['day'].month)} в {m['time']}"
    if data["gone"]:
        return f"Матч {m['title']} ({league}) перенесён или отменён — уточните на hockey.by. Время, арена и билеты на странице Glideclub."
    if m["phase"] == PHASE_AFTER:
        goals = len(data["goals"])
        tail = f" Голы по минутам: {goals}." if goals else ""
        return _fit_text(f"{m['title']}: итог матча {league} {score_text(m['result'])}, {m['day'].day} {_months(m['day'].month)}, {where}.{tail}")
    if data.get("away_trip"):
        base = f"Выездной матч {league} {m['title']} {when}."
        return _fit_text(base + " Трансляция и протокол — у клуба, напомнить о матче можно в Telegram.")
    base = f"Матч {league} {m['title']} {when}, {where}."
    standing = _standing_phrase(data)
    tail = f" {standing}." if standing else " Билеты, как добраться и катание рядом."
    if data.get("tickets") and not standing:
        tail = " Билеты на hockey.by, как добраться и катание рядом."
    return _fit_text(base + tail)


def _fit_text(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;—-")
    return cut + "…"


def _iso(dt: datetime) -> str:
    return local(dt).isoformat()


def match_jsonld(data: Mapping[str, Any], *, canonical: str, now: datetime) -> str:
    """SportsEvent только из фактов: нет билетов — нет ``offers``, нет адреса — нет ``address``."""
    m = data["match"]
    row = data["row"]
    status = "EventScheduled"
    previous = getattr(row, "previous_starts_at", None)
    if row.status == "cancelled":
        status = "EventCancelled"
    elif data["gone"]:
        status = "EventPostponed"
    elif previous is not None and previous > now:
        status = "EventRescheduled"
    arena = data["arena"] or {}
    place: dict[str, Any] = {"@type": "Place", "name": data["arena_name"]}
    address: dict[str, Any] = {"@type": "PostalAddress", "addressLocality": data["city"], "addressCountry": "BY"}
    if arena.get("address"):
        address["streetAddress"] = arena["address"]
    place["address"] = {k: v for k, v in address.items() if v}
    if arena.get("latitude") is not None and arena.get("longitude") is not None:
        place["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": arena["latitude"],
            "longitude": arena["longitude"],
        }
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        "name": m["title"],
        "url": canonical,
        "sport": "Хоккей",
        "startDate": _iso(m["starts_at"]),
        "eventStatus": f"https://schema.org/{status}",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "homeTeam": {"@type": "SportsTeam", "name": row.home_team},
        "awayTeam": {"@type": "SportsTeam", "name": row.away_team},
        "description": match_description(data),
    }
    if arena:  # выезд Динамо: места в каталоге нет — location не выдумываем
        payload["location"] = place
    if status == "EventRescheduled":
        payload["previousStartDate"] = _iso(previous)
    tickets = data.get("tickets")
    if tickets and safe_external_url(tickets["url"]) and not data["gone"]:
        payload["offers"] = {
            "@type": "Offer",
            "url": tickets["url"],
            "availability": "https://schema.org/InStock",
        }
    return json_for_script(payload)


_FORM_LABEL = {
    "В": ("В", "Победа в основное время"),
    "П": ("П", "Поражение в основное время"),
    "Во": ("В·ОТ", "Победа в овертайме"),
    "По": ("П·ОТ", "Поражение в овертайме"),
    "Вб": ("В·ОТ", "Победа по буллитам"),
    "Пб": ("П·ОТ", "Поражение по буллитам"),
}


def _form_marks(marks: list[str]) -> str:
    out = []
    for mark in marks:
        label, title = _FORM_LABEL.get(mark, (mark, mark))
        win = " data-win" if mark.startswith("В") else ""
        out.append(f'<i{win} title="{_e(title)}" aria-label="{_e(title)}">{_e(label)}</i>')
    return "".join(out)


def _before_card(data: Mapping[str, Any]) -> str:
    pv = data.get("preview") or {}
    rows: list[str] = []
    for side in ("home", "away"):
        block = pv.get(side) or {}
        if block.get("place") is not None and block.get("points") is not None:
            rows.append(
                f'<div class="m-kv"><span>{_e(block["team"])} в таблице</span>'
                f'<b>{block["place"]}-е · {block["points"]} {_points(block["points"])}</b></div>'
            )
    for side in ("home", "away"):
        block = pv.get(side) or {}
        if block.get("form"):
            rows.append(
                f'<div class="m-kv"><span>Форма: {_e(block["team"])}</span>'
                f'<span class="m-form">{_form_marks(block["form"])}</span></div>'
            )
    meeting = pv.get("last_meeting")
    if meeting:
        suffix = {"ot": " ОТ", "so": " Б"}.get(meeting.get("decided_in") or "", "")
        rows.append(
            f'<div class="m-kv"><span>Прошлая встреча</span><b>{_e(meeting["home_team"])} — {_e(meeting["away_team"])} '
            f'{meeting["home_score"]}:{meeting["away_score"]}{suffix}</b></div>'
        )
    if not rows:
        return ""
    return f'<section class="m-panel"><span class="m-lbl">ПЕРЕД МАТЧЕМ</span>{"".join(rows)}</section>'


def _after_card(data: Mapping[str, Any]) -> str:
    m = data["match"]
    parts: list[str] = []
    periods = data["periods"]
    if periods:
        n = len(periods)
        head = "".join(f"<span>{_e(p['label'])}</span>" for p in periods)
        vals = "".join(f"<span>{_e(p['score'])}</span>" for p in periods)
        parts.append(
            '<span class="m-lbl">ПО ПЕРИОДАМ</span>'
            f'<div class="m-grid" style="grid-template-columns:repeat({n},minmax(0,1fr))">{head}{vals}</div>'
        )
    goals = data["goals"]
    if goals:
        rows = []
        for i, g in enumerate(goals):
            last = i == len(goals) - 1
            who = f"{g['team']}, овертайм" if g["over"] and m["result"] and m["result"]["decided_in"] == "ot" else g["team"]
            scorer = f"<small>{_e(g['scorer'])}</small>" if g["scorer"] else ""
            score = f"<b>{_e(g['score'])}</b>" if last else _e(g["score"])
            rows.append(f'<div class="m-kv"><span>{_e(g["minute"])} · {_e(who)}{scorer}</span><span>{score}</span></div>')
        parts.append('<span class="m-lbl">ГОЛЫ</span>' + "".join(rows))
    if data.get("protocol_url"):
        parts.append(f'<a class="m-text-link" href="{_e(data["protocol_url"])}" rel="noopener nofollow" target="_blank">Протокол на hockey.by ›</a>')
    if not parts:
        return ""
    return f'<section class="m-panel">{"".join(parts)}</section>'


def _game_card(data: Mapping[str, Any], *, base_url: str, city_id: int | None) -> str:
    game = data.get("game")
    if not game:
        return ""
    m = data["match"]
    link = game_link(base_url, m["id"], city_id=city_id)
    if game["kind"] == "soon":
        head, sub, cta = "Скоро можно будет угадывать и Экстралигу", "Как откроем, напишем в Telegram.", "Напомнить в Telegram"
    else:
        phase = game["phase"]
        nxt = game.get("next")
        if phase == PHASE_BEFORE:
            head = "Угадай, кто победит"
            sub = "Тап за команду — и ты в таблице всей страны. Очки после матча, короны каждый месяц."
            cta = "Угадать в Telegram"
        else:
            home_name, away_name = display_name(data["row"].home_team), display_name(data["row"].away_team)
            nxt_day = local(nxt["starts_at"]) if nxt else None
            nxt_text = (
                f" Следующий: {home_name} — {display_name(nxt['away'])}, {nxt_day.day} {_months(nxt_day.month)}."
                if nxt
                else ""
            )
            if phase == PHASE_AFTER and game["total"] >= 10:
                head = f"Победу угадали {game['right']} из {game['total']}"
                sub = nxt_text.strip() or "Матч сыгран."
            else:
                head = "Ходы закрыты — матч идёт" if phase == PHASE_LIVE else "Ходы закрыты"
                home_n, away_n = game.get("home_n"), game.get("away_n")
                who = (
                    f"За {home_name} — {home_n} {plural_ru(home_n, 'игрок', 'игрока', 'игроков')}, "
                    f"за {away_name} — {away_n}."
                    if home_n is not None
                    else ""
                )
                sub = who + nxt_text
                sub = sub.strip() or "Игра продолжится на следующем матче."
            cta = "Сделать ход на следующий матч" if nxt else "Открыть игру"
            link = game_link(base_url, nxt["id"], city_id=city_id) if nxt else link
    button = (
        f'<a class="m-btn m-btn--fill" href="{_e(link)}" rel="nofollow" data-m-sheet="game" data-m-name="{_e(m["title"])}">{_e(cta)}</a>'
        if link
        else ""
    )
    return (
        '<section class="m-panel m-panel--game" aria-label="Кто кого"><span class="m-sticker">КТО КОГО?</span>'
        f'<span class="m-panel__head">{_e(head)}</span><span class="m-panel__sub">{_e(sub)}</span>{button}</section>'
    )


def _hero(data: Mapping[str, Any], *, city_href: str | None, city_label: str) -> str:
    m = data["match"]
    phase = m["phase"]
    gone = data["gone"]
    badge = m["league_label"].upper()
    big, sub = m["time"], WEEKDAYS_FULL[m["day"].weekday()]
    if gone:
        big, sub = "—", "уточняется"
    elif phase == PHASE_AFTER:
        big = score_text(m["result"]).replace(" ОТ", "").replace(" Б", "").replace(":", " : ")
        decided = (m["result"] or {}).get("decided_in")
        sub = {"ot": "в овертайме", "so": "по буллитам"}.get(decided or "", "")
        badge = f"ИТОГ · {badge}"
    elif phase == PHASE_LIVE:
        live = data.get("live")
        big, sub, badge = "идёт", "счёт — в протоколе", f"● ИДЁТ · {badge}"
        if live:
            big, sub = live["score"].replace(":", " : "), f"обновлено в {live['at']}"
    elif phase == PHASE_WAIT:
        big, sub = "—", "матч завершён, итог скоро"
    elif phase == PHASE_REVIEW:
        big, sub = "—", "итог уточняем"
    back = (
        f'<a class="b-pill b-pill--back" href="{_e(city_href)}">{icon_svg("back")}{_e(city_label)}</a>'
        if city_href
        else f'<a class="b-pill b-pill--back" href="{SITE_PATH}">{icon_svg("back")}Хоккей</a>'
    )
    return (
        '<header class="m-hero">'
        f'<div class="m-hero__halves"><span style="background:{_e(m["home"]["color"])}"></span>'
        f'<span style="background:{_e(m["away"]["color"])}"></span></div>'
        f'<div class="m-hero__in"><div class="m-hero__bar">{back}<span class="m-badge">{_e(badge)}</span></div>'
        '<div class="m-hero__teams">'
        f'<div class="m-team">{logo(m["home"], "lg")}<span>{_e(m["home"]["name"])}</span></div>'
        f'<div class="m-centre"><span class="m-centre__big">{_e(big)}</span><span class="m-centre__sub">{_e(sub)}</span></div>'
        f'<div class="m-team">{logo(m["away"], "lg")}<span>{_e(m["away"]["name"])}</span></div>'
        "</div></div></header>"
    )


def _tickets_block(data: Mapping[str, Any]) -> str:
    tickets = data.get("tickets")
    if not tickets:
        return ""
    url = safe_external_url(tickets["url"])
    if not url:
        return ""
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "hockey.by").removeprefix("www.")
    label = "Билеты на матч" if tickets["direct"] else "Билеты"
    note = f"на {host}" if tickets["direct"] else f"раздел билетов на {host}"
    return (
        f'<a class="m-btn m-btn--dark" href="{_e(url)}" rel="noopener nofollow" target="_blank">{label}<small>{_e(note)}</small></a>'
    )


def _away_card(data: Mapping[str, Any]) -> str:
    """Выезд Динамо: «Как добраться» тут не нужно — арены у нас нет; смотреть можно по трансляции и протоколу."""
    url = safe_external_url(data.get("protocol_url") or "")
    link = (
        f'<a class="m-text-link" href="{_e(url)}" rel="noopener nofollow" target="_blank">Трансляция и протокол ›</a>'
        if url
        else ""
    )
    return (
        '<section class="m-panel"><span class="m-lbl">ВЫЕЗД</span>'
        f'<div class="m-where"><b>Динамо-Минск в гостях</b><span>Матч проходит не в Минске</span></div>{link}</section>'
    )


def _club_links(data: Mapping[str, Any]) -> str:
    links = data.get("club_links") or []
    if not links:
        return ""
    items = "".join(
        f'<a class="m-text-link" href="{_e(list_href(None, c["slug"]))}">Все матчи · {_e(c["name"])} ›</a>' for c in links
    )
    return f'<div class="m-links">{items}</div>'


def _where_card(data: Mapping[str, Any]) -> str:
    if not data.get("arena"):
        return _away_card(data)
    arena = data["arena"]
    address = (arena.get("address") or "").strip()
    name = data["arena_name"]
    head = (
        f'<a class="m-where" href="{_e(data["arena_path"])}"><b>{_e(name)} ›</b>'
        f"<span>{_e(address or data['city'])}</span></a>"
        if data.get("arena_path")
        else f'<div class="m-where"><b>{_e(name)}</b><span>{_e(address or data["city"])}</span></div>'
    )
    ice = data.get("ice_before")
    ice_html = ""
    if ice:
        price = f", {_e(ice['price'])}" if ice.get("price") else ""
        ice_html = (
            f'<div class="m-ice"><b>{_e(ice["time"])}</b>'
            f"<span>Перед матчем — массовое катание здесь же{price}</span></div>"
        )
    return (
        '<section class="m-panel"><span class="m-lbl">КАК ДОБРАТЬСЯ</span>'
        f"{head}"
        '<div class="m-maps">'
        f'<a class="m-btn m-btn--soft" href="{_e(yandex_link(arena))}" rel="noopener nofollow" target="_blank">{icon_svg("route")}Маршрут в Яндекс Картах</a>'
        f"</div>{ice_html}</section>"
    )


def _others_card(data: Mapping[str, Any]) -> str:
    others = data.get("others") or []
    if not others:
        return ""
    m = data["match"]
    rows = "".join(
        f'<a class="m-kv" href="{_e(o["path"])}"><span>{_e(o["time"])} · {_e(o["title"])}</span>'
        f'<span style="color:var(--g-muted)">{_e(o["city"] or "")}</span></a>'
        for o in others
    )
    label = f"ЕЩЁ МАТЧИ {m['day'].day} {_months(m['day'].month).upper()}"
    return (
        f'<section class="m-panel"><span class="m-lbl">{_e(label)}</span>{rows}'
        f'<a class="m-text-link" href="{SITE_PATH}">Все матчи ›</a></section>'
    )


def render_match_page(
    data: Mapping[str, Any], *, base_url: str, now: datetime, city_href: str | None, city_id: int | None
) -> str:
    m = data["match"]
    canonical = f"{base_url}{m['path']}"
    phase = m["phase"]
    gone = data["gone"]
    before = phase == PHASE_BEFORE and not gone
    city_label = format_public_name(data['city']) if data.get("city") else ""
    h1 = f"{m['title']}, {when_text(m['starts_at'])} · {data['arena_name'] or 'выезд'}"

    actions = ""
    if before:
        link = bell_link(base_url, m["id"], city_id=city_id)
        bell = (
            f'<a class="m-btn m-btn--tg" href="{_e(link)}" rel="nofollow"{_bell_attrs(m)}>{icon_svg("bell")}Напомнить в Telegram</a>'
            if link
            else ""
        )
        tickets = _tickets_block(data)
        if not tickets and not data.get("away_trip"):
            tickets = '<p class="m-note">Билеты — у клуба и на hockey.by.</p>'
        actions = (
            '<div class="m-actions" data-m-before>'
            f"{tickets}{bell}"
            f'<a class="m-text-link" href="{_e(ics_path(m))}" download>Добавить в календарь</a></div>'
        )
    elif phase == PHASE_LIVE and data.get("protocol_url"):
        actions = (
            f'<a class="m-text-link" href="{_e(data["protocol_url"])}" rel="noopener nofollow" target="_blank">'
            "Протокол на hockey.by ›</a>"
        )

    gone_html = ""
    if gone:
        gone_html = (
            '<div class="m-gone"><b>Матч перенесён или отменён</b>'
            "<span>Уточните время и билеты на hockey.by — мы обновим страницу, когда клуб подтвердит.</span></div>"
        )
    middle = ""
    if not gone:
        middle = _before_card(data) if before else (_after_card(data) if phase == PHASE_AFTER else "")
        if phase == PHASE_AFTER and not middle and data.get("protocol_url"):
            middle = (
                f'<a class="m-text-link" href="{_e(data["protocol_url"])}" rel="noopener nofollow" target="_blank">'
                "Протокол на hockey.by ›</a>"
            )
    body = (
        _hero(data, city_href=city_href, city_label=city_label)
        + f'<div class="m-body" data-m-start="{_e(m["starts_at"].isoformat())}">'
        + f'<h1 class="m-h1">{_e(h1)}</h1>'
        + gone_html
        + _club_links(data)
        + actions
        + _game_card(data, base_url=base_url, city_id=city_id)
        + middle
        + _where_card(data)
        + _others_card(data)
        + "</div>"
        + assets_tail()
    )
    og_image = _match_og(base_url, m, row=data["row"])
    return _page(
        title=match_title(data),
        description=match_description(data),
        canonical=canonical,
        og_url=canonical,
        og_image=og_image,
        robots="noindex, follow" if gone else "index, follow",
        jsonld=match_jsonld(data, canonical=canonical, now=now),
        body=body,
        base_url=base_url,
        city_id=city_id,
        city_slug_value=city_slug(data["city"]) if data.get("city") else "",
        surface=MATCH_SURFACE,
        breadcrumbs=[("Glideclub", f"{base_url}/"), ("Хоккей", f"{base_url}{SITE_PATH}"), (m["title"], canonical)],
        canonical_for_crumbs=canonical,
    )


def _default_og(base_url: str) -> str:
    from src.application.catalog_home_page import catalog_home_og_image_url

    return catalog_home_og_image_url(base_url)


def _match_og(base_url: str, card: Mapping[str, Any], *, row: Any) -> str:
    """Открытка матча из игры — когда игра включена (её адрес иначе 404); иначе логотип сайта."""
    from src.application import hockey_event
    from src.application.hockey_cards import match_card_version
    from src.application.hockey_match_share import card_image_url

    cfg = Settings()  # type: ignore[call-arg]
    if base_url.startswith("https://") and hockey_event.enabled(cfg):
        version = match_card_version(row.home_team, row.away_team, card["starts_at"])
        return card_image_url(cfg, match_id=int(card["id"]), version=version, invite=False, story=False)
    return _default_og(base_url)


# ── Каркас страницы ──────────────────────────────────────────────────


def _page(
    *,
    title: str,
    description: str,
    canonical: str,
    og_url: str,
    og_image: str,
    robots: str,
    jsonld: str,
    body: str,
    base_url: str,
    city_id: int | None,
    city_slug_value: str,
    surface: str,
    breadcrumbs: list[tuple[str, str]] | None = None,
    canonical_for_crumbs: str = "",
) -> str:
    from src.application.catalog_list_share import catalog_list_share_tail
    from src.application.place_links import breadcrumb_script
    from src.application.public_analytics import public_analytics_head_html_from_settings
    from src.application.public_site_footer import render_site_footer_html
    from src.application.public_web_cta import public_page_view_beacon_script
    from src.application.style_b import COMPONENTS_VERSION, STYLE_VERSION, TOKENS_VERSION, public_fonts_head_html
    from src.shared.glide_city_cookie import glide_city_pin_script

    tail = catalog_list_share_tail(scripts=False)
    tail["__PLACE_SHARE_BAR__"] = ""
    if breadcrumbs:
        body += breadcrumb_script(canonical_for_crumbs, breadcrumbs)
    return fill_placeholders(
        _B_TEMPLATE_PATH.read_text(encoding="utf-8"),
        {
            "__OG_TITLE__": _e(title),
            "__OG_DESCRIPTION__": _e(description),
            "__DESCRIPTION__": _e(description),
            "__CANONICAL__": _e(canonical),
            "__OG_URL__": _e(og_url),
            "__OG_IMAGE__": _e(og_image),
            "__LANG__": "ru",
            "__OG_LOCALE__": "ru_RU",
            "__ROBOTS__": robots,
            "__HEAD_EXTRA__": head_extra(),
            "__JSONLD__": jsonld,
            "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
            "__PUBLIC_ANALYTICS_HEAD__": public_analytics_head_html_from_settings(),
            "__TOKENS_V__": TOKENS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__COMPONENTS_V__": COMPONENTS_VERSION,
            "__SITE_FOOTER__": render_site_footer_html(
                context_html='<div class="elsewhere"><a href="/">Массовое катание по всей Беларуси</a></div>',
            ),
            "__BODY__": body,
            "__PAGE_VIEW_BEACON__": public_page_view_beacon_script(surface=surface, city_id=city_id),
            "__GLIDE_CITY_PIN__": glide_city_pin_script(city_slug_value),
            **tail,
        },
    )


_FORBIDDEN = re.compile(r"ставк|коэффициент|прогноз|букмек|\bbet", re.IGNORECASE)


def has_forbidden_words(html: str) -> bool:
    """Для теста и для самопроверки: слова, которых в выдаче матчей быть не должно."""
    return bool(_FORBIDDEN.search(html))


def cache_header(phase: str) -> dict[str, str]:
    """До матча и во время него страница меняется быстро; итог живёт дольше (B12)."""
    if phase in (PHASE_BEFORE, PHASE_LIVE, PHASE_WAIT):
        return {"Cache-Control": "public, max-age=30, stale-while-revalidate=60"}
    return {"Cache-Control": "public, max-age=300, stale-while-revalidate=600"}


__all__ = [
    "BELL_PREFIX",
    "MATCH_PREFIX",
    "arena_ticket",
    "assets_tail",
    "bell_link",
    "bell_param",
    "cache_header",
    "feed_section",
    "game_link",
    "has_forbidden_words",
    "head_extra",
    "here_section",
    "ics_path",
    "list_href",
    "match_description",
    "match_jsonld",
    "match_title",
    "render_match_page",
    "render_matches_list",
    "route_row_line",
]
