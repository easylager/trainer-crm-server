"""Единый блок «Учиться с тренером» на сайте (TASK-354, PDEC-033).

Один рендер на город ``/c/{city}``, «Покататься», каток ``/p/…`` и «С клюшкой». Заголовок и кнопка
везде одинаковые; меняются лица, цифры, одна строка и цель. Чипы направлений — только на городе.

Цифры не считаем заново: число тренеров, «от» и ближайшее время берутся из ``load_city_catalog`` и
``listed_trainers`` / ``direction_min_price`` каталога (тот же предикат показа, что на
``/c/{city}/trenery``). Ссылки блока ведут только в каталог, не в Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import plural_ru
from src.application.site_trainer_catalog import (
    ALL,
    DIRECTIONS,
    Direction,
    _card_windows,
    _money,
    _n_trainers,
    best_offer,
    catalog_path,
    direction_by_slug,
    direction_min_price,
    listed_trainers,
    load_city_catalog,
    offer_phrase,
)
from src.application.style_b import esc
from src.shared.city_locative import city_locative

Place = Literal["city", "skate", "arena", "hockey"]

#: Сколько лиц в блоке.
FACES_SHOWN = 4
TITLE = "Учиться с тренером"
BUTTON = "Выбрать тренера"
_ZERO = direction_by_slug("s-nulya")
_HOCKEY = direction_by_slug("s-klyushkoy")
_NUM_WORDS = {1: "Один", 2: "Два", 3: "Три", 4: "Четыре"}


@dataclass(frozen=True)
class LearnBlock:
    #: (url фото | None, буква) — до ``FACES_SHOWN``.
    faces: tuple[tuple[str | None, str], ...]
    count: int
    line: str
    href: str
    #: (подпись, ссылка) — только на городе.
    chips: tuple[tuple[str, str], ...] = ()
    #: «от», минимальные единицы валюты — для пункта «Чем займёмся?».
    price: tuple[int, str] | None = None


def _min_price(rows: list[dict[str, Any]], direction: Direction) -> tuple[int, str] | None:
    prices = [p for p in (direction_min_price(t, direction) for t in rows) if p]
    return min(prices) if prices else None


def _min_phrase(rows: list[dict[str, Any]], direction: Direction, *, capital: bool = False) -> str:
    """«от 25 BYN в группе» / «от 41,87 BYN по абонементу» / «от 45 BYN за занятие» — как на карточке."""
    offer = best_offer(rows, direction)
    return offer_phrase(offer, capital=capital) if offer else ""


def _nearest(rows: list[dict[str, Any]], arena_id: int | None) -> str:
    """«сегодня, 17:15» — самое раннее окно среди показанных тренеров; нет окон — пусто."""
    wins = [w for t in rows for w in _card_windows(t, arena_id)[:1]]
    if not wins:
        return ""
    first = min(wins, key=lambda w: str(w["starts_at"]))
    return f"{first['day']}, {first['time']}"


def _faces(rows: list[dict[str, Any]]) -> tuple[tuple[str | None, str], ...]:
    return tuple((t.get("photo_url"), str(t["initial"])) for t in rows[:FACES_SHOWN])


def _is_one(n: int) -> bool:
    return n % 10 == 1 and n % 100 != 11


def learn_block(data: Mapping[str, Any], place: Place, *, arena_id: int | None = None) -> LearnBlock | None:
    """Блок для места или ``None`` — показывать нечего (нет тренеров, у которых есть что показать)."""
    city_name = str(data["city"]["name"])
    everyone = listed_trainers(data, ALL)
    if not everyone:
        return None

    if place == "city":
        price = _min_price(everyone, ALL)
        bits = []
        if price:
            bits.append(f"{_min_phrase(everyone, ALL, capital=True)}.")
        soon = _nearest(everyone, None)
        if soon:
            bits.append(f"Ближайшее свободное время — {soon}.")
        chips = tuple(
            (d.tab, catalog_path(city_name, d)) for d in DIRECTIONS if listed_trainers(data, d)
        )
        return LearnBlock(
            faces=_faces(everyone),
            count=len(everyone),
            line=" ".join(bits),
            href=catalog_path(city_name),
            # Одна вкладка повторяла бы кнопку — как в каталоге, где вкладок при одном направлении нет.
            chips=chips if len(chips) > 1 else (),
            price=price,
        )

    if place == "skate":
        rows = listed_trainers(data, _ZERO)
        if not rows:
            return None
        n = len(rows)
        who = f"{_NUM_WORDS[n]} {plural_ru(n, 'тренер', 'тренера', 'тренеров')}" if n in _NUM_WORDS else _n_trainers(n)
        verb = "учит" if _is_one(n) else "учат"
        price = _min_price(rows, _ZERO)
        line = f"Первый раз на льду? {who} {verb} с нуля — детей и взрослых."
        if price:
            line += f" От {_money(*price)}."
        return LearnBlock(faces=_faces(rows), count=n, line=line, href=catalog_path(city_name, _ZERO), price=price)

    if place == "hockey":
        rows = listed_trainers(data, _HOCKEY)
        if not rows:
            return None
        price = _min_price(rows, _HOCKEY)
        line = f"Хоккейное катание: стойка, ход и торможение. {_n_trainers(len(rows))}"
        line += f", от {_money(*price)}." if price else "."
        return LearnBlock(
            faces=_faces(rows), count=len(rows), line=line, href=catalog_path(city_name, _HOCKEY), price=price
        )

    # Каток. Название в падеж не ставим (нет склонения названий) — страница и так про этот каток.
    here = listed_trainers(data, ALL, arena_id) if arena_id is not None else []
    if here:
        n = len(here)
        verb = "занимается" if _is_one(n) else "занимаются"
        line = f"На этом катке {verb} {_n_trainers(n)}."
        soon = _nearest(here, arena_id)
        if soon:
            line += f" Ближайшее свободное время — {soon}."
        return LearnBlock(
            faces=_faces(here), count=n, line=line, href=catalog_path(city_name, ALL, arena_id=arena_id)
        )
    loc = city_locative(city_name)
    price = _min_price(everyone, ALL)
    where = f"В {loc}" if loc else "В городе"
    line = f"На этом катке тренеров пока нет. {where} — {len(everyone)}"
    line += f", {_min_phrase(everyone, ALL)}." if price else "."
    return LearnBlock(
        faces=_faces(everyone), count=len(everyone), line=line, href=catalog_path(city_name), price=price
    )


def hockey_count(data: Mapping[str, Any]) -> int:
    """«· N тренера» в строке «С клюшкой» — тот же показ, что у вкладки «С клюшкой»."""
    return len(listed_trainers(data, _HOCKEY))


def render_learn_block(block: LearnBlock | None) -> str:
    if block is None:
        return ""
    faces = "".join(
        f'<img src="{esc(photo)}" alt="" width="42" height="42" loading="lazy" decoding="async" />'
        if photo
        else f'<span class="b-learn__mono" aria-hidden="true">{esc(initial)}</span>'
        for photo, initial in block.faces
    )
    chips = (
        '<nav class="b-learn__chips" aria-label="Направления">'
        + "".join(f'<a href="{esc(href)}">{esc(label)}</a>' for label, href in block.chips)
        + "</nav>"
        if block.chips
        else ""
    )
    line = f'<p class="b-learn__line">{esc(block.line)}</p>' if block.line else ""
    return (
        '<section class="b-sec b-learn-sec" id="learn"><div class="b-learn">'
        f'<div class="b-learn__faces">{faces}<span>{esc(_n_trainers(block.count))}</span></div>'
        f'<h2 class="b-learn__t">{TITLE}</h2>{line}{chips}'
        f'<a class="b-learn__go" href="{esc(block.href)}"><span>{BUTTON}</span><span aria-hidden="true">→</span></a>'
        "</div></section>"
    )


async def load_learn_data(session: AsyncSession, city: Mapping[str, Any]) -> dict[str, Any]:
    """Данные каталога города — те же, что у ``/c/{city}/trenery``."""
    return await load_city_catalog(session, city)
