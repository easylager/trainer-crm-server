"""
Validate trainer profile field input for the bot wizard. Mirrors API limits (ProfilePatch / schemas).
"""
from __future__ import annotations

from pydantic import ValidationError

from src.api.schemas import (
    LEN_DESCRIPTION,
    LEN_FIRST_LAST,
    ProfilePatch,
    TRAINER_EDUCATION_OPTIONS,
)
from src.application.trainer_profile_completeness import MIN_DESCRIPTION_CHARS
from src.shared.profile_phone import normalize_phone_input, validate_phone_non_empty


def validate_first_name(value: str) -> tuple[str | None, str | None]:
    t = (value or "").strip()
    if not t:
        return None, "Введите имя."
    try:
        ProfilePatch(first_name=t)
    except ValidationError:
        return None, f"Имя не длиннее {LEN_FIRST_LAST} символов."
    return t, None


def validate_last_name(value: str) -> tuple[str | None, str | None]:
    t = (value or "").strip()
    if not t:
        return None, "Введите фамилию."
    try:
        ProfilePatch(last_name=t)
    except ValidationError:
        return None, f"Фамилия не длиннее {LEN_FIRST_LAST} символов."
    return t, None


def validate_age_line(value: str) -> tuple[int | None, str | None]:
    t = (value or "").strip()
    if not t:
        return None, "Введите возраст числом."
    try:
        ProfilePatch(age=int(t))
    except (ValueError, ValidationError):
        return None, "Возраст — целое число от 1 до 120."
    return int(t), None


def validate_phone(value: str) -> tuple[str | None, str | None]:
    """Returns normalized phone or None if empty; error message if invalid."""
    t = normalize_phone_input(value)
    if not t:
        return None, None
    return validate_phone_non_empty(t)


def validate_contacts(value: str) -> tuple[str | None, str | None]:
    t = (value or "").strip()
    if not t:
        return None, None
    try:
        ProfilePatch(contacts=t)
    except ValidationError:
        return None, f"Текст контактов не длиннее {LEN_DESCRIPTION} символов."
    return t, None


def validate_description_for_moderation(value: str) -> tuple[str | None, str | None]:
    t = (value or "").strip()
    if len(t) < MIN_DESCRIPTION_CHARS:
        return None, f"Описание — не менее {MIN_DESCRIPTION_CHARS} символов (сейчас {len(t)})."
    try:
        ProfilePatch(description=t)
    except ValidationError:
        return None, f"Описание не длиннее {LEN_DESCRIPTION} символов."
    return t, None


def validate_experience_line(value: str) -> tuple[int | None, str | None]:
    t = (value or "").strip()
    if t in ("", "-", "—", "пропустить", "skip"):
        return None, None
    try:
        ProfilePatch(experience_years=int(t))
    except (ValueError, ValidationError):
        return None, "Опыт — целое число лет от 0 до 80, или «-» чтобы пропустить."
    return int(t), None


def validate_session_duration_line(value: str) -> tuple[int | None, str | None]:
    t = (value or "").strip()
    if t in ("", "-", "—", "пропустить", "skip"):
        return None, None
    try:
        ProfilePatch(session_duration_minutes=int(t))
    except (ValueError, ValidationError):
        return None, "Длительность — число минут 15–240, или «-» чтобы пропустить."
    return int(t), None


def education_option_by_index(idx: int) -> str | None:
    opts = list(TRAINER_EDUCATION_OPTIONS)
    if 0 <= idx < len(opts):
        return opts[idx]
    return None
