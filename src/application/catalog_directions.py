"""Направления каталога тренеров — наш слой над публичными услугами справочника (PDEC-033).

Вкладка-направление (С нуля, Уже катаюсь, Фигурное, С клюшкой) — не услуга: «С клюшкой» =
Хоккейное катание (4) + ОХМ (6); Ролики (5) и ОФП/СФП (7) — не вкладки, только «Ещё ведёт» на
странице тренера. Своя услуга тренера попадает во вкладку той публичной услуги, к которой её
привязал админ (``services.direction_service_id``, TASK-353).

Единственное место, где услуга превращается во вкладку, и единственное место текстов направления
(лид, шаги, вопросы). Берут каталог ``/c/{city}/trenery`` (TASK-355) и страница тренера ``/t/``
(TASK-356). Город и цифры подставляются из данных у вызывающего.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.application.ice_city_day import city_slug

CATALOG_SEGMENT = "trenery"


@dataclass(frozen=True)
class Direction:
    key: str
    slug: str  # "" — «Все»
    tab: str
    crumb: str
    short: str
    h1: str
    lead: str
    steps: tuple[tuple[str, str], ...]
    faq: tuple[tuple[str, str | None], ...]
    #: Публичные услуги справочника, из которых состоит вкладка, по порядку (цена — с первой с ценой).
    service_ids: tuple[int, ...] = ()
    #: Кусок строки «Занятия с нуля и для уже катающихся.» под именем на странице тренера.
    role: str = ""
    #: Короткая формулировка для сниппета: «с нуля, для уже катающихся и хоккейное катание».
    seo: str = ""
    #: Предмет для title тренера с одним направлением: «тренер по фигурному катанию». Пусто — общая фраза.
    topic: str = ""


_FIRST = ("Выберите тренера и время", "Запись — в Telegram, оплата тренеру лично.")
_ARRIVE = ("Расскажите, какая у вас цель?", "Поделитесь вашим опытом и навыками и тем, к чему хотели бы прийти.")
_TICKET = (
    "Билет на каток входит в цену?",
    "Обычно нет: билет на сеанс покупают отдельно, на кассе. Уточните у тренера.",
)
#: Ответ из данных: ``None`` в FAQ — подставляем при рендере или убираем вопрос.
_Q_RENT = "Своих коньков нет"
_Q_PAIR = "Можно заниматься вместе с ребёнком?"
_Q_PLAY = "Где потом поиграть?"

ALL = Direction(
    key="all",
    slug="",
    tab="Все",
    crumb="",
    short="",
    h1="Тренеры по катанию на коньках",
    lead="Учат кататься с нуля и ставят технику. Есть фигурное катание и хоккей.",
    steps=(
        _FIRST,
        _ARRIVE,
        ("Вперёд тренироваться!", "Тренер посмотрит на ваше катание и подберёт упражнения индивидуально под вас!"),
    ),
    faq=(
        ("С чего начать, если ни разу не катался?", "С занятий «С нуля» — там учат и детей, и взрослых."),
        (_Q_RENT, None),
        _TICKET,
    ),
)

#: Номера — сид справочника (миграция 0028): slug у услуг на проде пуст (проверено 2026-11-07),
#: а id сида одинаков во всех базах. Ролики (5) и ОФП/СФП (7) — не вкладки.
DIRECTIONS: tuple[Direction, ...] = (
    Direction(
        key="zero",
        slug="s-nulya",
        tab="С нуля",
        crumb="С нуля",
        short="с нуля",
        h1="Научиться кататься на коньках с нуля",
        lead=(
            "Для детей и взрослых, которые ни разу не стояли на коньках или стояли пару раз. "
            "Равновесие, падения без страха и первые шаги."
        ),
        steps=(
            _FIRST,
            _ARRIVE,
            ("Начнёте с основ", "Обычно сначала учатся стоять, падать и вставать. Потом — первые шаги."),
        ),
        faq=(
            ("Мне 35 — не поздно начинать?", "Нет. Взрослые учатся кататься с нуля так же, как дети."),
            (
                "Боюсь упасть — это опасно?",
                "Падают все, кто учится. Обычно тренер в начале показывает, как падать и вставать. "
                "Ребёнку стоит надеть шлем.",
            ),
            (_Q_RENT, None),
            ("Во что одеться?", "В тёплую одежду, в которой удобно двигаться, и перчатки."),
            (_Q_PAIR, None),
            _TICKET,
        ),
        service_ids=(1,),
        role="с нуля",
        seo="с нуля",
    ),
    Direction(
        key="better",
        slug="uzhe-katayus",
        tab="Уже катаюсь",
        crumb="Уже катаюсь",
        short="уже катающиеся",
        h1="Уроки катания для тех, кто уже стоит на коньках",
        lead="Ровный ход, повороты, торможение и катание назад — для детей и взрослых.",
        steps=(
            _FIRST,
            ("Покажите, что умеете", "Тренер посмотрит, как вы катаетесь."),
            ("Получите план", "И скажет, над чем работать: ход, торможение или повороты."),
        ),
        faq=(
            ("Мне сюда или в «С нуля»?", "Если едете вперёд сами и не держитесь за бортик — вам сюда."),
            ("Нужны свои коньки?", "Для начала подойдут прокатные. Свои удобнее, когда занимаетесь регулярно."),
            ("Сколько нужно занятий?", "Зависит от цели. Спросите тренера после первого занятия."),
        ),
        service_ids=(2,),
        role="для уже катающихся",
        seo="для уже катающихся",
    ),
    Direction(
        key="fig",
        slug="figurnoe",
        tab="Фигурное",
        crumb="Фигурное катание",
        short="фигурное",
        h1="Фигурное катание с тренером",
        lead="Прыжки, вращения, дорожки шагов и программы — для детей и взрослых.",
        steps=(
            _FIRST,
            ("Знакомство", "Тренер посмотрит, что вы уже умеете."),
            ("Первые элементы", "И предложит, с каких элементов начать."),
        ),
        faq=(
            ("Можно прийти в фигурное с нуля?", "Да. Если ни разу не стояли на коньках, начните с занятий «С нуля»."),
            (
                "Нужны фигурные коньки?",
                "Для первых занятий подойдут прокатные. Когда дойдёте до прыжков, тренер подскажет, какие купить.",
            ),
            (
                "Можно подготовиться к соревнованиям?",
                "Да, если тренер ставит программы — это написано у него на странице.",
            ),
        ),
        service_ids=(3,),
        role="по фигурному катанию",
        seo="фигурное катание",
        topic="фигурному катанию",
    ),
    Direction(
        key="hock",
        slug="s-klyushkoy",
        tab="С клюшкой",
        crumb="Хоккейное катание",
        short="хоккей",
        h1="Хоккейное катание",
        lead="Стойка, ход, повороты и торможение — чтобы на площадке думать об игре, а не о коньках.",
        steps=(
            _FIRST,
            ("Возьмите экипировку", "Как минимум шлем, перчатки и клюшку."),
            ("Разбор катания", "Тренер посмотрит на стойку, ход и торможение и скажет, что поправить."),
        ),
        faq=(
            (
                "Только начинаю играть. С чего начать?",
                "С хоккейного катания. На ОХМ — когда уже уверенно держитесь на коньках.",
            ),
            ("Что такое ОХМ?", "Отработка хоккейного мастерства — тренировка элементов для тех, кто уже играет."),
            (_Q_PLAY, None),
        ),
        service_ids=(4, 6),
        role="по хоккейному катанию",
        seo="хоккейное катание",
        topic="хоккейному катанию",
    ),
)

_BY_SLUG = {d.slug: d for d in DIRECTIONS}
_BY_SERVICE = {sid: d.key for d in DIRECTIONS for sid in d.service_ids}
_BY_KEY = {d.key: d for d in (ALL, *DIRECTIONS)}


def direction_by_slug(slug: str | None) -> Direction | None:
    """``None``/"" — «Все»; неизвестный slug — ``None`` (404)."""
    if not slug:
        return ALL
    return _BY_SLUG.get(slug)


def direction_by_key(key: str) -> Direction:
    return _BY_KEY[key]


#: «С нуля» и «Уже катаюсь» вид не называют (решение владельца 2026-11-13):
#: они не делают тренера фигуристом и не мешают виду, если есть «Фигурное» или «С клюшкой».
_NEUTRAL_KEYS = frozenset({"zero", "better"})


def public_sport_name(direction_keys: Iterable[str]) -> str | None:
    """Публичный вид спорта, если направления тренера сходятся к одному виду.

    Нейтральные вкладки отбрасываются. Нет «Фигурного» и «С клюшкой», оба сразу,
    неизвестный ключ — ``None``: строка героя остаётся названиями вкладок.
    """
    keys = [key for key in direction_keys if key and key != "all" and key not in _NEUTRAL_KEYS]
    if not keys:
        return None
    figure = direction_by_key("fig").crumb
    hockey_short = direction_by_key("hock").short
    hockey = hockey_short[:1].upper() + hockey_short[1:]
    sports: set[str] = set()
    for key in keys:
        if key == "fig":
            sports.add(figure)
        elif key == "hock":
            sports.add(hockey)
        else:
            return None
    if len(sports) != 1:
        return None
    return next(iter(sports))


def own_service_direction(service: Mapping[str, Any]) -> str | None:
    """Вкладка своей услуги тренера: по привязке админа ``direction_service_id`` (TASK-353).

    Поле в ``services`` дописывает вызывающий (``load_service_directions``): в агрегате тренера
    из репозитория его нет. Не разобрано, «Не показывать» или привязка к Роликам/ОФП — ``None``.
    """
    try:
        did = int(service.get("direction_service_id"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return _BY_SERVICE.get(did)


def service_direction(service: Mapping[str, Any]) -> str | None:
    """Ключ вкладки услуги тренера или ``None`` (Ролики, ОФП/СФП, своя услуга без привязки)."""
    try:
        sid = int(service.get("service_id"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return _BY_SERVICE.get(sid) or own_service_direction(service)


def split_service_summary(summary: str | None) -> tuple[str, str]:
    """Клиентское описание услуги из справочника (``services.client_summary``) → ``(крючок, подробности)``.

    Первый абзац — «для кого это и подходит ли вам» (одна-две строки), остальное — «что делаем».
    Наш текст, как есть: ничего не сокращаем и не переписываем. Пусто → ``("", "")``.
    """
    parts = [p.strip() for p in re.split(r"\n\s*\n", (summary or "").strip()) if p.strip()]
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


_NAME_WITH_PARENS = re.compile(r"^(\S+)\s*\((.+)\)$")


def service_title(name: str | None) -> str:
    """Название услуги для клиента: «ОХМ(отработка хоккейного мастерства)» → «ОХМ — отработка хоккейного мастерства»."""
    text_ = (name or "").strip()
    m = _NAME_WITH_PARENS.match(text_)
    if not m:
        return text_
    inner = m.group(2).strip()
    return (
        f"{m.group(1)} — {inner[:1].lower() + inner[1:] if inner[:1].isupper() and not inner[:2].isupper() else inner}"
    )


async def load_service_directions(session: Any, services: list[dict[str, Any]]) -> None:
    """Дописывает услугам из агрегата тренера привязку к направлению и наш клиентский текст (одним запросом).

    ``direction_service_id`` — привязка своей услуги админом (TASK-353). ``summary_hook`` /
    ``summary_body`` — текст справочника, ТОЛЬКО у публичных услуг: у своей услуги тренера описания
    справочника нет, а подставлять чужое («Фигурное катание») к «постановке прыжков» нельзя.
    """
    from sqlalchemy import text

    ids = sorted({int(s["service_id"]) for s in services if s.get("service_id") is not None})
    if not ids:
        return
    rows = await session.execute(
        text(
            "SELECT id, direction_service_id, client_summary, COALESCE(is_public, true) "
            "FROM services WHERE id = ANY(:ids)"
        ),
        {"ids": ids},
    )
    by_id = {int(i): (int(d) if d is not None else None, summ, bool(pub)) for i, d, summ, pub in rows.fetchall()}
    for s in services:
        if s.get("service_id") is None:
            continue
        direction, summary, public = by_id.get(int(s["service_id"]), (None, None, False))
        s["direction_service_id"] = direction
        hook, body = split_service_summary(summary) if public else ("", "")
        s["summary_hook"], s["summary_body"] = hook, body


def catalog_path(city_name: str, direction: Direction = ALL, *, arena_id: int | None = None) -> str:
    path = f"/c/{city_slug(city_name)}/{CATALOG_SEGMENT}" + (f"/{direction.slug}" if direction.slug else "")
    return path + (f"?arena={int(arena_id)}" if arena_id else "")
