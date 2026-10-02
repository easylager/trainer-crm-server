"""
Адреса публичной страницы места и входы из неё в Telegram (TASK-146).

Почему своя страница, а не ссылка на бота. До этой задачи «Поделиться» отдавало
``t.me/<bot>?start=…``: превью такой ссылки рисует Telegram по профилю бота, и
получатель видит «бот Glide», а не «Сб 20:30, Минск-Арена, 25 BYN». В Viber и
WhatsApp она вообще не открывается без Telegram. Поэтому шерим HTTPS-страницу
места — её превью наше (og-теги + картинка), её индексирует поиск, и она
открывается у любого человека. Вход в Telegram — кнопка на самой странице.

Один модуль на все адреса, чтобы страница, шер-эндпоинт, бот и диплинки мини-аппа
не собирали URL каждый по-своему.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from src.application.ice_city_day import city_slug
from src.application.trainer_invite_links import normalize_client_bot_username

PLACE_PATH_PREFIX = "/p"

#: ``arena_<id>`` — по id, а не по slug: slug уникален только внутри города.
PLACE_START_PREFIX = "arena_"
#: ``catalog_<city_id>`` или ``catalog_<city_id>_<intent>`` — отфильтрованный каталог.
CATALOG_START_PREFIX = "catalog_"

# Ограничения Telegram на start/startapp: до 64 символов, только [A-Za-z0-9_-].
_START_PARAM_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

CATALOG_INTENTS = ("skate", "coach", "shop", "gym")


def place_path(*, city_name: str, slug: str) -> str:
    """``/p/minsk/minsk-arena``."""
    return f"{PLACE_PATH_PREFIX}/{city_slug(city_name)}/{slug}"


def place_query(*, session_id: int | None = None, invite: bool = False) -> str:
    params: dict[str, str] = {}
    if session_id is not None and int(session_id) > 0:
        params["s"] = str(int(session_id))
    if invite:
        params["i"] = "1"
    return ("?" + urlencode(params)) if params else ""


def place_page_url(
    *,
    base_url: str,
    city_name: str,
    slug: str,
    session_id: int | None = None,
    invite: bool = False,
) -> str:
    base = (base_url or "").strip().rstrip("/")
    return base + place_path(city_name=city_name, slug=slug) + place_query(session_id=session_id, invite=invite)


def place_image_url(
    *,
    base_url: str,
    city_name: str,
    slug: str,
    session_id: int | None = None,
    invite: bool = False,
    story: bool = False,
) -> str:
    """og.png (1200×630) или story.png (1080×1920) — тот же рисунок в двух форматах."""
    base = (base_url or "").strip().rstrip("/")
    name = "story.png" if story else "og.png"
    return (
        base
        + place_path(city_name=city_name, slug=slug)
        + f"/{name}"
        + place_query(session_id=session_id, invite=invite)
    )


def is_valid_start_param(value: str) -> bool:
    return bool(_START_PARAM_RE.match(value or ""))


def place_start_param(arena_id: int) -> str:
    return f"{PLACE_START_PREFIX}{int(arena_id)}"


def catalog_start_param(city_id: int, intent: str | None = None) -> str:
    """``catalog_12`` / ``catalog_12_coach``. Неизвестный intent не попадает в ссылку."""
    param = f"{CATALOG_START_PREFIX}{int(city_id)}"
    if intent and intent in CATALOG_INTENTS:
        param += f"_{intent}"
    return param


#: Голый «catalog» — маркетинговый вход (/go): каталог без города, город — по геолокации.
CATALOG_START_ANY = "catalog"


def parse_catalog_start_param(value: str | None) -> tuple[int | None, str | None] | None:
    """``catalog_12_coach`` → ``(12, "coach")``; ``catalog`` → ``(None, None)``; прочее → ``None``."""
    raw = (value or "").strip()
    if raw == CATALOG_START_ANY:
        return None, None
    if not raw.startswith(CATALOG_START_PREFIX):
        return None
    rest = raw[len(CATALOG_START_PREFIX) :]
    city_part, _, intent = rest.partition("_")
    if not city_part.isdigit() or int(city_part) <= 0:
        return None
    if intent and intent not in CATALOG_INTENTS:
        intent = ""
    return int(city_part), (intent or None)


def parse_place_start_param(value: str | None) -> int | None:
    """``arena_42`` → ``42``. Slug здесь не принимаем: он неоднозначен между городами."""
    raw = (value or "").strip()
    if not raw.startswith(PLACE_START_PREFIX):
        return None
    rest = raw[len(PLACE_START_PREFIX) :]
    return int(rest) if rest.isdigit() and int(rest) > 0 else None


def telegram_open_link(
    *,
    client_bot_username: str | None,
    mini_app_short_name: str | None,
    start_param: str,
) -> str | None:
    """
    Ссылка «Открыть в Telegram» с параметром.

    С коротким именем мини-аппа (BotFather → /newapp) — ``t.me/<bot>/<app>?startapp=…``:
    мини-апп открывается сразу на нужном экране, без сообщения от бота. Без него —
    ``t.me/<bot>?start=…``: бот отвечает одной кнопкой на тот же экран (``cmd_start``).
    Худший случай — один лишний тап, а не блуждание по хабу.
    """
    bot = normalize_client_bot_username(client_bot_username)
    if not bot or not is_valid_start_param(start_param):
        return None
    app = (mini_app_short_name or "").strip().strip("/")
    if app and re.match(r"^[A-Za-z0-9_]{3,64}$", app):
        return f"https://t.me/{bot}/{app}?startapp={start_param}"
    return f"https://t.me/{bot}?start={start_param}"
