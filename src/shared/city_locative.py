"""Предложный падеж городов для заголовков поиска: «Массовое катание в Минске».

Таблица ручная: белорусские топонимы автоматом склоняются с ошибками («в Гродне»,
«в Жодине»), а заголовок в выдаче — первое, что человек читает о Glide.
Нет города в таблице — ``None``, и вызывающий код строит фразу без падежа.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_LOCATIVE: dict[str, str] = {
    "Барановичи": "Барановичах",
    "Берёза": "Берёзе",
    "Бобруйск": "Бобруйске",
    "Брест": "Бресте",
    "Витебск": "Витебске",
    "Гомель": "Гомеле",
    "Горки": "Горках",
    "Гродно": "Гродно",
    "Жлобин": "Жлобине",
    "Жодино": "Жодино",
    "Ивацевичи": "Ивацевичах",
    "Кобрин": "Кобрине",
    "Лида": "Лиде",
    "Лунинец": "Лунинце",
    "Минск": "Минске",
    "Могилёв": "Могилёве",
    "Мозырь": "Мозыре",
    "Молодечно": "Молодечно",
    "Новополоцк": "Новополоцке",
    "Озерный": "Озёрном",
    "Орша": "Орше",
    "Островец": "Островце",
    "Пинск": "Пинске",
    "Пружаны": "Пружанах",
    "Раубичи": "Раубичах",
    "Светлогорск": "Светлогорске",
    "Силичи": "Силичах",
    "Солигорск": "Солигорске",
    "Шклов": "Шклове",
    "Санкт-Петербург/ЛО": "Санкт-Петербурге",
    "Санкт-Петербург": "Санкт-Петербурге",
    "Москва/МО": "Москве",
    "Москва": "Москве",
}


def city_locative(name: str) -> str | None:
    """«Минск» → «Минске». ``ё``/``е`` в базе пишут по-разному — сверяем без различия."""
    key = (name or "").strip()
    if key in _LOCATIVE:
        return _LOCATIVE[key]
    folded = key.replace("ё", "е").casefold()
    for known, value in _LOCATIVE.items():
        if known.replace("ё", "е").casefold() == folded:
            return value
    return None


_WARNED: set[str] = set()


def warn_if_no_locative(city_name: str, *, where: str) -> None:
    """Предупреждение в лог: у города с опубликованным тренером нет предложного падежа.

    Без него заголовок и сниппет честно обходятся без «в Минске», но выдача теряет запрос с городом —
    такой город надо добавить в таблицу выше. Один раз на город за процесс, чтобы не засорять лог.
    """
    from src.shared.public_display import format_public_name

    raw = (city_name or "").strip()
    if not raw or raw in _WARNED:
        return
    if city_locative(raw) or city_locative(format_public_name(raw)):
        return
    _WARNED.add(raw)
    logger.warning(
        "city_locative: no prepositional case for city %r with a published trainer (%s); "
        "titles and snippets fall back to the bare phrase — add it to src/shared/city_locative.py",
        raw,
        where,
    )
