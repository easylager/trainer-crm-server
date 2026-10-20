"""Домашний матч Динамо в общем движке шаринга (TASK-304): «Погнали?», «Компания», «Открытка».

Лист шаринга карточки катка (``GlideShareSheet``) берёт из ответа ``/arenas/{ref}/share`` ссылку, тексты
двух тонов и адреса картинок. Здесь те же данные для матча, чтобы страница матча открывала тот же лист.

У матча нет публичной страницы на сайте, поэтому ссылка — вход в Mini App ``startapp=kkm_<матч>``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application import hockey_event
from src.application.client_share_message import share_body_for_native_share_dialog
from src.application.hockey_cards import match_card_version
from src.application.ice_company.service import MATCH_VENUE_LABEL
from src.application.place_links import match_start_param, telegram_open_link
from src.ingestion.hockey_sources import MINSK_TZ
from src.shared.config import Settings

_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MONTHS_GEN = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

INVITE_HOOK = "Погнали?"


def when_phrase(starts_at: datetime) -> str:
    """«ср, 21 октября, 19:30» по Минску. Абсолютная дата: сообщение читают и назавтра."""
    local = starts_at.astimezone(MINSK_TZ)
    return f"{_WEEKDAYS[local.weekday()]}, {local.day} {_MONTHS_GEN[local.month - 1]}, {local:%H:%M}"


def match_link(match_id: int, settings: Settings) -> str:
    """Вход на страницу матча: ``t.me/<бот>?startapp=kkm_<id>``; без бота — страница Mini App в вебе."""
    link = telegram_open_link(
        client_bot_username=settings.client_bot_username,
        mini_app_short_name=settings.client_mini_app_short_name,
        main_mini_app=settings.client_bot_main_mini_app,
        start_param=match_start_param(match_id),
    )
    if link:
        return link
    base = (settings.webapp_base_url or "").strip().rstrip("/")
    path = f"/webapp/{hockey_event.event_href(match_id)}"
    return f"{base}{path}" if base else path


def card_image_url(settings: Settings, *, match_id: int, version: str, invite: bool, story: bool) -> str:
    """Открытка матча. Версия — в адресе (Telegram кэширует фото по адресу), тон — в query."""
    base = (settings.webapp_base_url or "").strip().rstrip("/")
    name = f"{version}.story.png" if story else f"{version}.png"
    return f"{base}/kk/m/{int(match_id)}/{name}" + ("?i=1" if invite else "")


def _texts(*, url: str, home: str, away: str, starts_at: datetime) -> tuple[dict[str, str], dict[str, str]]:
    title = f"{home} — {away}"
    where = f"{when_phrase(starts_at)} · {MATCH_VENUE_LABEL}"
    invite_text = f"{url}\n\n{INVITE_HOOK} {title}, {where}"
    plain_text = f"{url}\n\n{title}\n{where}"

    def pack(text: str) -> dict[str, str]:
        return {
            "share_url": url,
            "share_text": text,
            "share_body": share_body_for_native_share_dialog(text, url),
        }

    return pack(invite_text), pack(plain_text)


async def match_share_payload(
    session: AsyncSession,
    *,
    match_id: int,
    invite: bool,
    share_context: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Тот же контракт, что у ``get_public_place_share``. ``MatchNotFound`` — матч выездной или чужой."""
    cfg = settings or Settings()  # type: ignore[call-arg]
    row = await hockey_event._home_match(session, match_id)  # noqa: SLF001 — одна выборка домашнего матча на модуль
    starts_at = row.starts_at if row.starts_at.tzinfo else row.starts_at.replace(tzinfo=timezone.utc)
    url = match_link(int(row.id), cfg)
    invited, plain = _texts(url=url, home=row.home_team, away=row.away_team, starts_at=starts_at)
    version = match_card_version(row.home_team, row.away_team, starts_at)
    chosen = invited if invite else plain
    return {
        **chosen,
        "invite_share_url": invited["share_url"],
        "invite_share_body": invited["share_body"],
        "invite_share_text": invited["share_text"],
        "place_share_url": plain["share_url"],
        "place_share_body": plain["share_body"],
        "place_share_text": plain["share_text"],
        "og_image_url": card_image_url(cfg, match_id=int(row.id), version=version, invite=invite, story=False),
        "story_image_url": card_image_url(cfg, match_id=int(row.id), version=version, invite=invite, story=True),
        "share_context": share_context,
        "match_id": int(row.id),
    }
