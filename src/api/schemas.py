"""API request/response DTOs. All inputs validated (length, range) before use.

Trainer onboarding completeness for the moderation queue is defined in code as
`src.application.trainer_profile_completeness` (not every optional field here is required for PATCH).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.shared.profile_phone import PHONE_MAX_LEN, coerce_optional_phone_for_profile
from src.shared.price_tier_kind import normalize_price_tier_kind

# Allowed trainer lifecycle statuses
TrainerStatus = Literal[
    "pending_profile",
    "pending_contract",
    "pending_payment",
    "active",
    "deactivated",
]

# Limits aligned with DB: String(32/64/128), Text() capped for API safety
LEN_FIRST_LAST = 64
LEN_PHONE = PHONE_MAX_LEN
LEN_DESCRIPTION = 5000
LEN_FILE_KEY = 512

TRAINER_EDUCATION_OPTIONS = (
    "Среднее специальное",
    "Высшее профильное",
    "Высшее непрофильное",
    "Курсы и сертификация",
    "Ученая степень",
    "Другое",
)

TrainerEducation = Literal[
    "Среднее специальное",
    "Высшее профильное",
    "Высшее непрофильное",
    "Курсы и сертификация",
    "Ученая степень",
    "Другое",
]


class ProfileCreate(BaseModel):
    first_name: str = Field(default="", max_length=LEN_FIRST_LAST)
    last_name: str = Field(default="", max_length=LEN_FIRST_LAST)
    age: int = Field(default=0)
    city_id: int | None = Field(default=None, ge=0)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    description: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    phone: str | None = Field(default=None, max_length=LEN_PHONE)
    contacts: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    education: TrainerEducation | None = Field(default=None)
    session_duration_minutes: int | None = Field(default=None, ge=15, le=240)

    @field_validator("phone", mode="before")
    @classmethod
    def _phone_create(cls, v: object) -> str | None:
        return coerce_optional_phone_for_profile(v)


class TrainerServicePriceTierItem(BaseModel):
    """One fixed tariff for a service (tier_kind from price_tier_kind.PRICE_TIER_*)."""

    tier_kind: str = Field(..., min_length=1, max_length=32)
    price_byn: float = Field(..., ge=0)

    @field_validator("tier_kind")
    @classmethod
    def _normalize_tier_kind(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("Некорректный тип тарифа.")
        n = normalize_price_tier_kind(v.strip())
        if n is None:
            raise ValueError("Неизвестный тип тарифа.")
        return n


class TrainerServiceItem(BaseModel):
    """Service offered by trainer with optional price in BYN (rubles). Stored as kopecks in DB."""

    service_id: int = Field(..., ge=1)
    price_byn: float | None = Field(default=None, ge=0, description="Legacy: single adult price.")
    price_child_byn: float | None = Field(default=None, ge=0, description="Legacy: child price.")
    price_tiers: list[TrainerServicePriceTierItem] | None = Field(
        default=None,
        description="Up to five fixed tariffs per service (checkboxes in trainer profile).",
    )

    @model_validator(mode="after")
    def _tiers_or_legacy_price(self) -> TrainerServiceItem:
        tiers = self.price_tiers
        if tiers is not None and len(tiers) > 0:
            if len(tiers) > 5:
                raise ValueError("Не более пяти тарифов на одну услугу.")
            seen: set[str] = set()
            for t in tiers:
                if t.tier_kind in seen:
                    raise ValueError("Один и тот же тариф указан дважды.")
                seen.add(t.tier_kind)
            return self
        if self.price_child_byn is not None and self.price_byn is None:
            raise ValueError("Укажите цену для взрослых или уберите детскую цену.")
        return self


class TrainerCreateBody(BaseModel):
    profile: ProfileCreate | None = None
    service_ids: list[int] = Field(default_factory=list)  # legacy; use services for prices
    services: list[TrainerServiceItem] = Field(default_factory=list)
    arena_ids: list[int] = Field(default_factory=list)


class ProfilePatch(BaseModel):
    first_name: str | None = Field(default=None, max_length=LEN_FIRST_LAST)
    last_name: str | None = Field(default=None, max_length=LEN_FIRST_LAST)
    age: int | None = Field(default=None)
    city_id: int | None = Field(default=None)
    experience_years: int | None = Field(default=None)
    description: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    phone: str | None = Field(default=None, max_length=LEN_PHONE)
    contacts: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    education: TrainerEducation | None = Field(default=None)
    session_duration_minutes: int | None = Field(default=None)
    min_hours_before_booking: int | None = Field(default=None)

    @field_validator("phone", mode="before")
    @classmethod
    def _phone_patch(cls, v: object) -> str | None:
        return coerce_optional_phone_for_profile(v)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def _name_not_blank_if_sent(cls, v: object, info) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Некорректный тип.")
        s = v.strip()
        if not s:
            label = "Имя" if info.field_name == "first_name" else "Фамилия"
            raise ValueError(f"{label} не может быть пустым — укажите текст или уберите поле из запроса.")
        return s

    @field_validator("age", mode="before")
    @classmethod
    def _age_patch(cls, v: object) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError("Некорректное значение возраста.")
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValueError("Возраст укажите целым числом.")
        return iv

    @field_validator("city_id", mode="before")
    @classmethod
    def _city_patch(cls, v: object) -> int | None:
        if v is None:
            return None
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValueError("Город: некорректное значение.")
        if iv < 1:
            raise ValueError("Выберите город из списка.")
        return iv

    @field_validator("experience_years", mode="before")
    @classmethod
    def _experience_patch(cls, v: object) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError("Некорректное значение.")
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValueError("Опыт укажите целым числом (лет).")
        if iv < 0 or iv > 80:
            raise ValueError("Опыт: от 0 до 80 лет.")
        return iv

    @field_validator("session_duration_minutes", mode="before")
    @classmethod
    def _session_duration_patch(cls, v: object) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError("Некорректное значение.")
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValueError("Длительность занятия — целое число минут.")
        if iv < 15 or iv > 240:
            raise ValueError("Длительность: от 15 до 240 минут.")
        return iv

    @field_validator("min_hours_before_booking", mode="before")
    @classmethod
    def _min_hours_patch(cls, v: object) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError("Некорректное значение.")
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValueError("Мин. часов до записи — целое число.")
        if iv < 0 or iv > 168:
            raise ValueError("От 0 до 168 часов.")
        return iv


class TrainerProfilePatchBody(BaseModel):
    profile: ProfilePatch | None = None
    service_ids: list[int] | None = None  # legacy; use services for prices
    services: list[TrainerServiceItem] | None = None
    arena_ids: list[int] | None = None
    primary_arena_id: int | None = Field(
        default=None,
        ge=1,
        description="Основная площадка для онлайн-записи при выборе «Любая арена» в каталоге.",
    )


class PhotoRegisterBody(BaseModel):
    file_key: str = Field(..., max_length=LEN_FILE_KEY)


class PresignBody(BaseModel):
    trainer_id: int = Field(..., ge=1)
    content_type: str = Field(default="image/jpeg", max_length=128)


class TrainerStatusPatchBody(BaseModel):
    status: TrainerStatus


class TrainerTermsCreateBody(BaseModel):
    """Admin: create trainer_terms legal document metadata. File is stored in bucket under file_key."""
    version: int = Field(..., ge=1)
    title: str | None = Field(default=None, max_length=256)
    file_key: str = Field(..., max_length=LEN_FILE_KEY)
    make_active: bool = True


TrainerEducationType = Literal["formal_education", "course_or_certificate"]


class TrainerEducationCreateBody(BaseModel):
    education_type: TrainerEducationType
    institution_name: str = Field(..., min_length=2, max_length=160)
    program_or_title: str = Field(..., min_length=2, max_length=180)
    degree_level: str | None = Field(default=None, max_length=64)
    country: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=64)
    start_year: int | None = Field(default=None, ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)
    is_in_progress: bool = False
    document_url: str | None = Field(default=None, max_length=512)


class TrainerEducationPatchBody(BaseModel):
    education_type: TrainerEducationType | None = None
    institution_name: str | None = Field(default=None, min_length=2, max_length=160)
    program_or_title: str | None = Field(default=None, min_length=2, max_length=180)
    degree_level: str | None = Field(default=None, max_length=64)
    country: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=64)
    start_year: int | None = Field(default=None, ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)
    is_in_progress: bool | None = None
    document_url: str | None = Field(default=None, max_length=512)


