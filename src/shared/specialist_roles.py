"""
Кто такой специалист на платформе — свободный текст с подсказками, не enum.

К нам идут не только тренеры по конькам: спортивные психологи, хореографы,
реабилитологи, нутрициологи. Жёсткий список ролей мы бы угадывали, и каждая
новая смежная дисциплина стоила бы миграции — поэтому ``specialist_role``
хранится как текст, а ``SUGGESTED_ROLES`` лишь подсказывает частое.

Подсказки нужны не для ограничения, а чтобы разнобой был терпимым: без них
одно и то же пишут как «тренер», «Тренер по ОФП» и «фитнес-тренер», и роль
перестаёт что-либо значить в карточке.

Пусто = «Тренер»: так было до появления колонки у всех существующих анкет,
и подставлять это на чтении честнее, чем бэкфилить 50+ строк выдуманным.
"""
from __future__ import annotations

import re
from typing import Any

SPECIALIST_ROLE_MAX_LEN = 64

DEFAULT_SPECIALIST_ROLE = "Тренер"

#: Порядок = порядок чипсов в онбординге. «Тренер» первый: это по-прежнему
#: подавляющее большинство, и лишний тап им платить не за что.
SUGGESTED_ROLES: tuple[str, ...] = (
    "Тренер",
    "ОФП-тренер",
    "Хореограф",
    "Спортивный психолог",
    "Реабилитолог",
    "Нутрициолог",
)


class InvalidSpecialistRoleError(ValueError):
    """Роль длиннее лимита или из одних пробелов/знаков препинания."""


def normalize_specialist_role(value: Any) -> str | None:
    """Схлопнуть пробелы, обрезать, отдать ``None`` для пустого.

    ``None`` (а не ``"Тренер"``) — чтобы отличить «не спрашивали» от
    «выбрал Тренера»: первое можно переспросить в онбординге, второе нет.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    collapsed = re.sub(r"\s+", " ", raw)
    if len(collapsed) > SPECIALIST_ROLE_MAX_LEN:
        raise InvalidSpecialistRoleError(
            f"Роль — не длиннее {SPECIALIST_ROLE_MAX_LEN} символов."
        )
    if not re.search(r"\w", collapsed, flags=re.UNICODE):
        raise InvalidSpecialistRoleError("Напишите, кто вы — буквами.")
    return collapsed


def specialist_role_display(value: Any) -> str:
    """Подпись роли в карточке; пустая анкета читается как «Тренер»."""
    try:
        return normalize_specialist_role(value) or DEFAULT_SPECIALIST_ROLE
    except InvalidSpecialistRoleError:
        return DEFAULT_SPECIALIST_ROLE
