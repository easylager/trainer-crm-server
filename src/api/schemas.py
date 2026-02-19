"""API request/response DTOs."""
from typing import Any, Literal

from pydantic import BaseModel, Field

# Allowed trainer lifecycle statuses
TrainerStatus = Literal[
    "pending_profile",
    "pending_contract",
    "pending_payment",
    "active",
    "deactivated",
]


class ProfileCreate(BaseModel):
    first_name: str = ""
    last_name: str = ""
    age: int = 0
    experience_years: int | None = None
    description: str | None = None
    phone: str | None = None
    contacts: str | None = None
    education: str | None = None


class TrainerCreateBody(BaseModel):
    profile: ProfileCreate | None = None
    service_ids: list[int] = Field(default_factory=list)


class ProfilePatch(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    age: int | None = None
    experience_years: int | None = None
    description: str | None = None
    phone: str | None = None
    contacts: str | None = None
    education: str | None = None


class TrainerProfilePatchBody(BaseModel):
    profile: ProfilePatch | None = None
    service_ids: list[int] | None = None


class PhotoRegisterBody(BaseModel):
    file_key: str


class PresignBody(BaseModel):
    trainer_id: int
    content_type: str = "image/jpeg"


class TrainerStatusPatchBody(BaseModel):
    status: TrainerStatus
