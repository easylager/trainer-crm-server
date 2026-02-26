"""
DB models. One source of truth for schema; Alembic migrations follow these.
"""
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Lifecycle: only "active" trainers are shown to clients (e.g. in catalog/channel).
TRAINER_STATUS_PENDING_PROFILE = "pending_profile"
TRAINER_STATUS_PENDING_CONTRACT = "pending_contract"
TRAINER_STATUS_PENDING_PAYMENT = "pending_payment"
TRAINER_STATUS_ACTIVE = "active"
TRAINER_STATUS_DEACTIVATED = "deactivated"

TRAINER_STATUSES = (
    TRAINER_STATUS_PENDING_PROFILE,
    TRAINER_STATUS_PENDING_CONTRACT,
    TRAINER_STATUS_PENDING_PAYMENT,
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
)


class Trainer(Base):
    """Trainer: created on site (or by admin); telegram_id set when they open link."""
    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        Enum(*TRAINER_STATUSES, name="trainer_status_enum", create_constraint=True),
        nullable=False,
        default=TRAINER_STATUS_PENDING_PROFILE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    moderation_feedback: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)  # shown on site when not approved

    link_tokens: Mapped[list["TrainerLinkToken"]] = relationship(back_populates="trainer", lazy="raise")
    profile: Mapped[Optional["TrainerProfile"]] = relationship(back_populates="trainer", uselist=False, lazy="raise")
    photos: Mapped[list["TrainerPhoto"]] = relationship(back_populates="trainer", lazy="raise")
    services: Mapped[list["Service"]] = relationship(
        "Service", secondary="trainer_services", back_populates="trainers", lazy="raise"
    )
    arenas: Mapped[list["Arena"]] = relationship(
        "Arena", secondary="trainer_arenas", back_populates="trainers", lazy="raise"
    )


class TrainerLinkToken(Base):
    """One-time token for trainer to link Telegram. Issued after site registration/payment."""
    __tablename__ = "trainer_link_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    trainer: Mapped["Trainer"] = relationship(back_populates="link_tokens", lazy="raise")


class City(Base):
    """City for filtering trainers. Admin fills; trainer profile has one city."""
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)


class Arena(Base):
    """Venue/arena in a city: real place with address and optional coords for map link."""
    __tablename__ = "arenas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(nullable=True)

    trainers: Mapped[list["Trainer"]] = relationship(
        "Trainer", secondary= lambda: trainer_arenas_table, back_populates="arenas", lazy="raise"
    )


# M2M: trainer works at these arenas; filter catalog by arena via this table
trainer_arenas_table = Table(
    "trainer_arenas",
    Base.metadata,
    Column("trainer_id", ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
    Column("arena_id", ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
    UniqueConstraint("trainer_id", "arena_id", name="uq_trainer_arenas_trainer_arena"),
)


class TrainerProfile(Base):
    """Trainer card. Managed on site; required: first_name, last_name, age. Optional: city, experience_years, etc."""
    __tablename__ = "trainer_profiles"

    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), primary_key=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), nullable=True)
    experience_years: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    contacts: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    education: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    rating_avg: Mapped[Optional[float]] = mapped_column(nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trainer: Mapped["Trainer"] = relationship(back_populates="profile", lazy="raise")


class TrainerPhoto(Base):
    """Metadata only. Actual files live in S3 (S3_ENDPOINT + S3_BUCKET); file_key = object key in bucket."""
    __tablename__ = "trainer_photos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)  # S3 object key
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)

    trainer: Mapped["Trainer"] = relationship(back_populates="photos", lazy="raise")


class TrainerRating(Base):
    """Client rating 1–5 for a trainer; optional review text. One rating per (trainer_id, client_telegram_id)."""
    __tablename__ = "trainer_ratings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True)
    client_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rating: Mapped[int] = mapped_column(Integer(), nullable=False)  # 1..5
    review_text: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Service(Base):
    """Catalog of services (e.g. hockey, figure skating). Admin fills; trainer picks."""
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)

    trainers: Mapped[list["Trainer"]] = relationship(
        "Trainer", secondary="trainer_services", back_populates="services", lazy="raise"
    )


# --- Client bot session (one row per telegram_id); city_id for future cities table ---
CLIENT_STATE_IDLE = "idle"
CLIENT_STATE_TRAINER_SELECTED = "trainer_selected"


class ClientSession(Base):
    """Client bot: current step and choices (city, service, trainer). Extensible via payload."""
    __tablename__ = "client_sessions"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default=CLIENT_STATE_IDLE)
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), nullable=True)
    selected_service_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    selected_trainer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainers.id", ondelete="SET NULL"), nullable=True
    )
    selected_arena_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Trainer schedule: weekly template → generated slots for booking ---

class TrainerScheduleTemplate(Base):
    """Weekly pattern: e.g. 'every Monday 10:00 for 60 min'. Trainer adds these; we generate concrete slots."""
    __tablename__ = "trainer_schedule_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer(), nullable=False)  # 0=Monday .. 6=Sunday
    start_time: Mapped[time] = mapped_column(Time(), nullable=False)  # e.g. 10:00
    duration_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="60")

    trainer: Mapped["Trainer"] = relationship(back_populates="schedule_templates", lazy="raise")


class Slot(Base):
    """Concrete bookable slot: one date + time window. Generated from templates or added manually."""
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    slot_date: Mapped[date] = mapped_column(Date(), nullable=False)
    start_time: Mapped[time] = mapped_column(Time(), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available")  # available | booked | cancelled

    trainer: Mapped["Trainer"] = relationship(back_populates="slots", lazy="raise")


class Booking(Base):
    """Client booking: one slot, client telegram + phone + comment. notified_at when trainer was pushed."""
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id", ondelete="CASCADE"), nullable=False)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    client_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    client_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    client_comment: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    client_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Reminder(Base):
    """Client reminder for a booking: when and what to send to Telegram."""
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)
    client_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. before_24h, before_2h
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending | sent | failed | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)


# --- Client "leave request" when no suitable trainer found ---
REQUEST_STATUS_NEW = "new"
REQUEST_STATUS_CONTACTED = "contacted"
REQUEST_STATUS_ARCHIVED = "archived"


class ClientRequest(Base):
    """Client left a request: city + service + optional comment. Admin/trainers can process later."""
    __tablename__ = "client_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=REQUEST_STATUS_NEW)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientRequestResponse(Base):
    """Trainer responded to a client request: can fulfill it (one response per request per trainer)."""
    __tablename__ = "client_request_responses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_request_id: Mapped[int] = mapped_column(
        ForeignKey("client_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
