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

#: Токены startapp. shop/gym/ice/… — фильтр типа места; skate/coach — интент вкладки.
CATALOG_LINK_TOKENS = (
    "skate",
    "coach",
    "shop",
    "gym",
    "ice",
    "outdoor",
    "choreo",
    "pool",
    "other",
)
#: Окно, которое умеет унести диплинк. ``any`` и ``auto`` в ссылку не кладём.
CATALOG_WHEN_TOKENS = ("today_evening", "today", "tomorrow", "weekend")
_WHEN_WITH = frozenset({"skate", "ice", "outdoor"})


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


def place_start_param(arena_id: int, session_id: int | None = None) -> str:
    """``arena_42`` или ``arena_42_s_9001`` — карточка на конкретном сеансе."""
    param = f"{PLACE_START_PREFIX}{int(arena_id)}"
    if session_id is not None and int(session_id) > 0:
        param += f"_s_{int(session_id)}"
    return param


def catalog_start_param(city_id: int, intent: str | None = None, when: str | None = None) -> str:
    """``catalog_12`` / ``catalog_12_coach`` / ``catalog_12_skate_weekend``.

    Неизвестный токен не попадает в ссылку. Окно времени — только у льда
    (``skate`` / ``ice`` / ``outdoor``): без ``intent=skate`` сохранённая вкладка
    «Тренеры» съедает окно. У магазина и зала окна нет, ``when`` отбрасывается.
    """
    token = intent if intent in CATALOG_LINK_TOKENS else None
    when_ok = when if when in CATALOG_WHEN_TOKENS else None
    if when_ok and token not in _WHEN_WITH:
        if token is None:
            token = "skate"
        else:
            when_ok = None
    param = f"{CATALOG_START_PREFIX}{int(city_id)}"
    if token:
        param += f"_{token}"
    if when_ok:
        param += f"_{when_ok}"
    return param


#: Голый «catalog» — маркетинговый вход (/go): каталог без города, город — по геолокации.
CATALOG_START_ANY = "catalog"


def parse_catalog_start_param(value: str | None) -> tuple[int | None, str | None, str | None] | None:
    """``catalog_12_skate_weekend`` → ``(12, "skate", "weekend")``.

    ``catalog`` → ``(None, None, None)`` (маркетинговый вход). Чужой payload → ``None``.
    Неизвестный токен после города отбрасывается, город остаётся: ``catalog_12_sauna`` → ``(12, None, None)``.
    """
    raw = (value or "").strip()
    if raw == CATALOG_START_ANY:
        return None, None, None
    if not raw.startswith(CATALOG_START_PREFIX):
        return None
    rest = raw[len(CATALOG_START_PREFIX) :]
    when: str | None = None
    for key in ("today_evening", "tomorrow", "weekend", "today"):
        suffix = "_" + key
        if rest.endswith(suffix):
            when = key
            rest = rest[: -len(suffix)]
            break
    city_part, _, token = rest.partition("_")
    if not city_part.isdigit() or int(city_part) <= 0:
        return None
    if token and token not in CATALOG_LINK_TOKENS:
        token = ""
        when = None
    if when and token and token not in _WHEN_WITH:
        when = None
    return int(city_part), (token or None), when


_PLACE_DEEP_RE = re.compile(r"^arena_([1-9][0-9]*)(?:_s_([1-9][0-9]*))?$")


def parse_place_deep_link(value: str | None) -> tuple[int, int | None] | None:
    """``arena_42`` → ``(42, None)``; ``arena_42_s_7`` → ``(42, 7)``. Slug не принимаем."""
    match = _PLACE_DEEP_RE.match((value or "").strip())
    if match is None:
        return None
    session_id = int(match.group(2)) if match.group(2) else None
    return int(match.group(1)), session_id


def parse_place_start_param(value: str | None) -> int | None:
    """``arena_42`` / ``arena_42_s_7`` → id места. Slug здесь не принимаем."""
    parsed = parse_place_deep_link(value)
    return parsed[0] if parsed is not None else None


def telegram_open_link(
    *,
    client_bot_username: str | None,
    mini_app_short_name: str | None,
    start_param: str,
    main_mini_app: bool = False,
) -> str | None:
    """
    Ссылка «Открыть в Telegram» с параметром.

    * Основное мини-приложение бота (BotFather → Main Mini App) — ``t.me/<bot>?startapp=…``:
      мини-апп открывается сразу на нужном экране, без сообщения от бота;
    * отдельный мини-апп с коротким именем (BotFather → /newapp) — ``t.me/<bot>/<app>?startapp=…``;
    * ни того ни другого — ``t.me/<bot>?start=…``: бот отвечает одной кнопкой на тот же
      экран (``cmd_start``). Худший случай — один лишний тап, а не блуждание по хабу.
    """
    bot = normalize_client_bot_username(client_bot_username)
    if not bot or not is_valid_start_param(start_param):
        return None
    app = (mini_app_short_name or "").strip().strip("/")
    if app and re.match(r"^[A-Za-z0-9_]{3,64}$", app):
        return f"https://t.me/{bot}/{app}?startapp={start_param}"
    if main_mini_app:
        return f"https://t.me/{bot}?startapp={start_param}"
    return f"https://t.me/{bot}?start={start_param}"
