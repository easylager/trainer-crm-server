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

from dataclasses import dataclass
from typing import Any, Mapping

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
    #: Кусок строки «С нуля и для тех, кто уже катается.» под именем на странице тренера.
    role: str = ""


_FIRST = ("Выберите тренера и время", "Запись — в Telegram, оплата тренеру на месте.")
_ARRIVE = ("Приезжайте за 15–20 минут", "Нет своих коньков — возьмите в прокате. Билет на сеанс покупают на кассе.")
_TICKET = ("Билет на каток входит в цену?", "Обычно нет: билет на сеанс покупают отдельно, на кассе. Уточните у тренера.")
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
    lead="Учат с нуля, ставят ход, фигурное катание и хоккей. Оплата тренеру на месте.",
    steps=(
        _FIRST,
        _ARRIVE,
        ("Начните с тренером", "Он посмотрит, что вы уже умеете, и скажет, с чего начать."),
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
        role="для тех, кто уже катается",
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
            ("Можно подготовиться к соревнованиям?", "Да, если тренер ставит программы — это написано у него на странице."),
        ),
        service_ids=(3,),
        role="фигурное катание",
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
        role="хоккейное катание",
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


async def load_service_directions(session: Any, services: list[dict[str, Any]]) -> None:
    """Дописывает ``direction_service_id`` услугам из агрегата тренера (одним запросом)."""
    from sqlalchemy import text

    ids = sorted({int(s["service_id"]) for s in services if s.get("service_id") is not None})
    if not ids:
        return
    rows = await session.execute(
        text("SELECT id, direction_service_id FROM services WHERE id = ANY(:ids)"), {"ids": ids}
    )
    by_id = {int(i): (int(d) if d is not None else None) for i, d in rows.fetchall()}
    for s in services:
        if s.get("service_id") is not None:
            s["direction_service_id"] = by_id.get(int(s["service_id"]))


def catalog_path(city_name: str, direction: Direction = ALL, *, arena_id: int | None = None) -> str:
    path = f"/c/{city_slug(city_name)}/{CATALOG_SEGMENT}" + (f"/{direction.slug}" if direction.slug else "")
    return path + (f"?arena={int(arena_id)}" if arena_id else "")
