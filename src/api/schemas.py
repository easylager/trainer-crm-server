"""API request/response DTOs. All inputs validated (length, range) before use."""
from typing import Literal

from pydantic import BaseModel, Field

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
LEN_PHONE = 32
LEN_DESCRIPTION = 5000
LEN_FILE_KEY = 512


class ProfileCreate(BaseModel):
    first_name: str = Field(default="", max_length=LEN_FIRST_LAST)
    last_name: str = Field(default="", max_length=LEN_FIRST_LAST)
    age: int = Field(default=0, ge=0, le=120)
    city_id: int | None = Field(default=None, ge=0)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    description: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    phone: str | None = Field(default=None, max_length=LEN_PHONE)
    contacts: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    education: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    session_duration_minutes: int | None = Field(default=None, ge=15, le=240)


class TrainerServiceItem(BaseModel):
    """Service offered by trainer with optional price in BYN (rubles). Stored as kopecks in DB."""
    service_id: int = Field(..., ge=1)
    price_byn: float | None = Field(default=None, ge=0)


class TrainerCreateBody(BaseModel):
    profile: ProfileCreate | None = None
    service_ids: list[int] = Field(default_factory=list)  # legacy; use services for prices
    services: list[TrainerServiceItem] = Field(default_factory=list)
    arena_ids: list[int] = Field(default_factory=list)


class ProfilePatch(BaseModel):
    first_name: str | None = Field(default=None, max_length=LEN_FIRST_LAST)
    last_name: str | None = Field(default=None, max_length=LEN_FIRST_LAST)
    age: int | None = Field(default=None, ge=0, le=120)
    city_id: int | None = Field(default=None, ge=0)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    description: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    phone: str | None = Field(default=None, max_length=LEN_PHONE)
    contacts: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    education: str | None = Field(default=None, max_length=LEN_DESCRIPTION)
    session_duration_minutes: int | None = Field(default=None, ge=15, le=240)


class TrainerProfilePatchBody(BaseModel):
    profile: ProfilePatch | None = None
    service_ids: list[int] | None = None  # legacy; use services for prices
    services: list[TrainerServiceItem] | None = None
    arena_ids: list[int] | None = None


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


