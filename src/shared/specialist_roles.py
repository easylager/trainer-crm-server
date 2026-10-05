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
SPECIALIST_ROLE_DISPLAY_MAX_LEN = 200
MAX_SPECIALIST_ROLES = 5
SPECIALIST_ROLE_JOIN = " · "

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


class TooManySpecialistRolesError(ValueError):
    """Слишком много ролей в одной анкете."""


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


def normalize_specialist_roles(values: Any) -> list[str]:
    """Упорядоченный список ролей без дублей; пустой ввод → ``[]``."""
    if values is None:
        return []
    raw_list: list[Any]
    if isinstance(values, (list, tuple)):
        raw_list = list(values)
    else:
        raw_list = [values]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_list:
        role = normalize_specialist_role(item)
        if not role:
            continue
        key = role.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(role)
        if len(out) > MAX_SPECIALIST_ROLES:
            raise TooManySpecialistRolesError(
                f"Не больше {MAX_SPECIALIST_ROLES} специальностей за раз."
            )
    return out


def specialist_roles_join(roles: list[str]) -> str | None:
    """Строка для каталога и legacy ``specialist_role``; ``None`` если список пуст."""
    if not roles:
        return None
    joined = SPECIALIST_ROLE_JOIN.join(roles)
    if len(joined) > SPECIALIST_ROLE_DISPLAY_MAX_LEN:
        raise InvalidSpecialistRoleError(
            f"Слишком длинная подпись ролей — не больше {SPECIALIST_ROLE_DISPLAY_MAX_LEN} символов."
        )
    return joined


def specialist_roles_from_storage(
    roles_json: Any,
    legacy_single: Any = None,
) -> list[str]:
    """Собрать список из JSONB и/или старой одиночной колонки."""
    parsed = normalize_specialist_roles(roles_json) if roles_json is not None else []
    if parsed:
        return parsed
    single = normalize_specialist_role(legacy_single)
    return [single] if single else []


def specialist_role_display(value: Any, roles_json: Any = None) -> str:
    """Подпись роли в карточке; пустая анкета читается как «Тренер»."""
    try:
        roles = specialist_roles_from_storage(roles_json, legacy_single=value)
        if roles:
            return specialist_roles_join(roles) or DEFAULT_SPECIALIST_ROLE
        return normalize_specialist_role(value) or DEFAULT_SPECIALIST_ROLE
    except (InvalidSpecialistRoleError, TooManySpecialistRolesError):
        return DEFAULT_SPECIALIST_ROLE
