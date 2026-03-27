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

TRAINER_EDUCATION_TYPE_FORMAL = "formal_education"
TRAINER_EDUCATION_TYPE_COURSE = "course_or_certificate"
TRAINER_EDUCATION_TYPES = (
    TRAINER_EDUCATION_TYPE_FORMAL,
    TRAINER_EDUCATION_TYPE_COURSE,
)

TRAINER_EDU_MOD_PENDING = "pending_moderation"
TRAINER_EDU_MOD_APPROVED = "approved"
TRAINER_EDU_MOD_REJECTED = "rejected"
TRAINER_EDU_MOD_STATUSES = (
    TRAINER_EDU_MOD_PENDING,
    TRAINER_EDU_MOD_APPROVED,
    TRAINER_EDU_MOD_REJECTED,
)


class Trainer(Base):
    """Trainer: created on site (or by admin); telegram_id set when they open link."""
    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        Enum(*TRAINER_STATUSES, name="trainer_status_enum", create_constraint=True),
        nullable=False,
        default=TRAINER_STATUS_PENDING_PROFILE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    moderation_feedback: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)  # shown on site when not approved
    # Set when trainer successfully queues for admin review; cleared when profile/photo/services/education change.
    moderation_submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")


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
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")

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
    session_duration_minutes: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True, server_default="45")
    min_hours_before_booking: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default="3"
    )  # Only slots at least this many *working* hours (08:00–22:00 Minsk) from now are bookable by clients
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trainer: Mapped["Trainer"] = relationship(back_populates="profile", lazy="raise")


class TrainerEducation(Base):
    """Structured trainer education entries with moderation lifecycle."""
    __tablename__ = "trainer_education"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True)
    education_type: Mapped[str] = mapped_column(
        Enum(*TRAINER_EDUCATION_TYPES, name="trainer_education_type_enum", create_constraint=True),
        nullable=False,
    )
    institution_name: Mapped[str] = mapped_column(String(160), nullable=False)
    program_or_title: Mapped[str] = mapped_column(String(180), nullable=False)
    degree_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    start_year: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    end_year: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    is_in_progress: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    document_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    moderation_status: Mapped[str] = mapped_column(
        Enum(*TRAINER_EDU_MOD_STATUSES, name="trainer_education_moderation_status_enum", create_constraint=True),
        nullable=False,
        default=TRAINER_EDU_MOD_PENDING,
        server_default=TRAINER_EDU_MOD_PENDING,
    )
    moderation_comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    approved_snapshot: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainer_education.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainerEducationModerationEvent(Base):
    """Audit trail for moderation decisions over trainer education rows."""
    __tablename__ = "trainer_education_moderation_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_education_id: Mapped[int] = mapped_column(
        ForeignKey("trainer_education.id", ondelete="CASCADE"), nullable=False, index=True
    )
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class Client(Base):
    """
    Client identity: by telegram_id (bot user) or by phone_normalized (trainer-added, no bot yet).
    At least one of telegram_id or phone_normalized must be set.
    """
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    phone_normalized: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    bookings: Mapped[list["Booking"]] = relationship(back_populates="client", lazy="raise")
    client_requests: Mapped[list["ClientRequest"]] = relationship(back_populates="client", lazy="raise")


# --- Trainer-private notes about clients ---


class TrainerClientNote(Base):
    """Per-trainer private note about a client (goes into trainer CRM; not visible to other trainers)."""
    __tablename__ = "trainer_client_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
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
    """Client booking: one slot, client (FK), service (FK), per-booking comment. notified_at when trainer was pushed."""
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id", ondelete="CASCADE"), nullable=False)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    client_comment: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    client_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    client_notified_trainer_booked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trainer_confirm_reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    client_cancel_comment: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    client: Mapped["Client"] = relationship(back_populates="bookings", lazy="raise")


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
    """Client left a request: city + service + optional comment; optional trainer_id for personalized."""
    __tablename__ = "client_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    trainer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    comment: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=REQUEST_STATUS_NEW)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    no_response_reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    client: Mapped["Client"] = relationship(back_populates="client_requests", lazy="raise")


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


class ClientRequestDecline(Base):
    """Trainer declined a request: hidden from their list; client is not notified."""
    __tablename__ = "client_request_declines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_request_id: Mapped[int] = mapped_column(
        ForeignKey("client_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Pass products (trainer-defined subscription) and instances (client-owned) ---


class TrainerPassProduct(Base):
    """Trainer-defined pass product: e.g. '5 sessions for 200 BYN'. Clients buy these."""
    __tablename__ = "trainer_pass_products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sessions_total: Mapped[int] = mapped_column(Integer(), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer(), nullable=False)
    service_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Client-owned pass instance: trainer issued after client paid externally (no platform payment)
PASS_INSTANCE_STATUS_ACTIVE = "active"
PASS_INSTANCE_STATUS_USED_UP = "used_up"
PASS_INSTANCE_STATUS_CANCELLED = "cancelled"


class PassInstance(Base):
    """One pass held by a client. Issued by trainer when client paid externally. Sessions deducted on completed booking."""
    __tablename__ = "pass_instances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pass_product_id: Mapped[int] = mapped_column(
        ForeignKey("trainer_pass_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sessions_remaining: Mapped[int] = mapped_column(Integer(), nullable=False)
    sessions_total: Mapped[int] = mapped_column(Integer(), nullable=False)
    source_certificate_instance_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("certificate_instances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=PASS_INSTANCE_STATUS_ACTIVE
    )  # active | used_up | cancelled


class PassRedemption(Base):
    """One pass session redeemed for a completed booking. History/audit."""
    __tablename__ = "pass_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    pass_instance_id: Mapped[int] = mapped_column(
        ForeignKey("pass_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrainerCertificateProduct(Base):
    """Trainer-defined certificate: fixed amount (e.g. 100 BYN) or 'any amount'. Info only for clients."""
    __tablename__ = "trainer_certificate_products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="Подарочный сертификат")
    amount_cents: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)  # NULL = "любая сумма"
    expires_in_days: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Issued certificate: trainer gave code to client; client_id nullable (may be issued without account)
CERTIFICATE_INSTANCE_STATUS_ACTIVE = "active"
CERTIFICATE_INSTANCE_STATUS_REDEEMED = "redeemed"
CERTIFICATE_INSTANCE_STATUS_CANCELLED = "cancelled"


class CertificateInstance(Base):
    """One issued certificate: code for client to redeem with trainer."""
    __tablename__ = "certificate_instances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    certificate_product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainer_certificate_products.id", ondelete="SET NULL"), nullable=True
    )
    purchased_by_name: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activated_client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipient_name: Mapped[str] = mapped_column(Text(), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer(), nullable=False)
    amount_remaining_cents: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=CERTIFICATE_INSTANCE_STATUS_ACTIVE
    )  # active | redeemed | cancelled
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recipient_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recipient_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


# --- Trainer subscription to platform (billing: trial + paid plans) ---

SUBSCRIPTION_STATUS_TRIAL = "trial"
SUBSCRIPTION_STATUS_ACTIVE = "active"
SUBSCRIPTION_STATUS_PAST_DUE = "past_due"
SUBSCRIPTION_STATUS_CANCELLED = "cancelled"

INVOICE_STATUS_DRAFT = "draft"
INVOICE_STATUS_SENT = "sent"
INVOICE_STATUS_PAID = "paid"
INVOICE_STATUS_OVERDUE = "overdue"
INVOICE_STATUS_CANCELLED = "cancelled"

# Subscription tiers: hierarchical access levels (analytics > online > crm)
SUBSCRIPTION_TIER_NONE = "none"  # No active subscription or expired
SUBSCRIPTION_TIER_CRM = "crm"
SUBSCRIPTION_TIER_ONLINE = "online"
SUBSCRIPTION_TIER_ANALYTICS = "analytics"

SUBSCRIPTION_TIERS = (
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_ONLINE,
    SUBSCRIPTION_TIER_ANALYTICS,
)

# Tier hierarchy for access checks: higher index = more access
SUBSCRIPTION_TIER_LEVELS = {
    SUBSCRIPTION_TIER_NONE: 0,
    SUBSCRIPTION_TIER_CRM: 1,
    SUBSCRIPTION_TIER_ONLINE: 2,
    SUBSCRIPTION_TIER_ANALYTICS: 3,
}


class SubscriptionPlan(Base):
    """Tariff plan for trainer platform subscription (trial or paid)."""
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer(), nullable=False)
    period_days: Mapped[int] = mapped_column(Integer(), nullable=False)
    is_trial: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)


class TrainerSubscription(Base):
    """One subscription period per trainer: trial or paid. Active when expires_at > now() and status in (trial, active)."""
    __tablename__ = "trainer_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tier: Mapped[Optional[str]] = mapped_column(
        Enum(*SUBSCRIPTION_TIERS, name="subscription_tier_enum", create_constraint=False),
        nullable=True,
    )  # crm | online | analytics — determines feature access
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # trial, active, past_due, cancelled
    payment_external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class TrainerInvoice(Base):
    """Invoice for trainer subscription (one per period). Paid via checkout link or manual bank transfer."""
    __tablename__ = "trainer_invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_plan_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer(), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # draft, sent, paid, overdue, cancelled
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class SubscriptionTierPricing(Base):
    """Admin-editable pricing for subscription tiers (crm/online/analytics)."""
    __tablename__ = "subscription_tier_pricing"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tier: Mapped[str] = mapped_column(
        Enum(*SUBSCRIPTION_TIERS, name="subscription_tier_enum", create_constraint=False),
        nullable=False,
        unique=True,
    )
    price_cents: Mapped[int] = mapped_column(Integer(), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), server_default="BYN", nullable=False)
    period_days: Mapped[int] = mapped_column(Integer(), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(128), nullable=False)
    short_description_ru: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    bullets_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubscriptionTierPricingAudit(Base):
    """Audit trail for tier pricing changes by admin."""
    __tablename__ = "subscription_tier_pricing_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tier_pricing_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_tier_pricing.id", ondelete="CASCADE"), nullable=False, index=True
    )
    admin_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    changed_fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Support: messages from clients/trainers to admins ---

SUPPORT_FROM_CLIENT = "client"
SUPPORT_FROM_TRAINER = "trainer"
SUPPORT_STATUS_NEW = "new"
SUPPORT_STATUS_REPLIED = "replied"
SUPPORT_STATUS_CLOSED = "closed"


class SupportMessage(Base):
    """One support ticket: user writes, admin can reply. from_role = client|trainer for which bot to use when sending reply."""
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    from_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    from_role: Mapped[str] = mapped_column(String(16), nullable=False)  # client | trainer
    message_text: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="new")  # new | replied | closed
    admin_reply_text: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    admin_replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


# --- Legal: documents (e.g. trainer terms) and trainer acceptances ---


class LegalDocument(Base):
    """Legal document stored in bucket (HTML/PDF), versioned in DB by code + version."""
    __tablename__ = "legal_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # e.g. 'trainer_terms'
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)  # key in bucket, e.g. legal/trainer_terms_v1.html
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainerAgreement(Base):
    """Trainer accepted specific version of a legal document (e.g. trainer_terms v1)."""
    __tablename__ = "trainer_agreements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("legal_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    accepted_version: Mapped[int] = mapped_column(Integer(), nullable=False)


