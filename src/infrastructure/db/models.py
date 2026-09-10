"""
DB models. One source of truth for schema; Alembic migrations follow these.
"""
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    Boolean,
    func,
    text,
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
    vk_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
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
    # Active trainers: text edits queued here until admin approves; catalog reads trainer_profiles only.
    profile_pending: Mapped[Optional[dict]] = mapped_column(JSONB(), nullable=True)
    # Active trainers: new photo keys here until approve; catalog uses trainer_photos only.
    photo_pending: Mapped[Optional[dict]] = mapped_column(JSONB(), nullable=True)
    # Default venue for online booking when client did not pick a specific arena ("any").
    primary_arena_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # When primary arena has no row in arena_schedule_presets, schedule editor uses this step (10/15/30/60).
    schedule_grid_step_minutes: Mapped[int] = mapped_column(
        SmallInteger(), nullable=False, default=15, server_default="15"
    )
    # Empty catalog fallback: mobile/outdoor format or pending arena request (TTV gate only).
    arena_work_format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    arena_request_text: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    arena_request_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stable short code for referral deep links (e.g. t.me/bot?start=ref_ABC123)
    referral_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, unique=True, index=True)
    # Public client catalog (/api/public/trainers): the trainer's own opt-in. Defaults to false —
    # filling in a profile is not the same intent as asking to be listed publicly, and listings
    # additionally require status = 'active'. See migration 0182_catalog_opt_in.
    is_catalog_visible: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    # First time trainer copied a client-facing invite or booking link in Mini App (growth funnel).
    client_invite_link_first_copied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Europe/Minsk wall-clock hours for Telegram pushes from notification_service; NULL = platform default (8–22).
    push_notification_start_hour: Mapped[Optional[int]] = mapped_column(SmallInteger(), nullable=True)
    push_notification_end_hour: Mapped[Optional[int]] = mapped_column(SmallInteger(), nullable=True)
    # Daily/weekly digest ritual (notification_loops → run_daily_morning_digest_loop, run_weekly_sunday_digest_loop).
    digest_enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    # Europe/Minsk local time for morning digest; NULL = auto morning slot (~8:00), not tied to evening session time.
    digest_send_time: Mapped[Optional[time]] = mapped_column(Time(), nullable=True)

    link_tokens: Mapped[list["TrainerLinkToken"]] = relationship(back_populates="trainer", lazy="raise")
    profile: Mapped[Optional["TrainerProfile"]] = relationship(back_populates="trainer", uselist=False, lazy="raise")
    photos: Mapped[list["TrainerPhoto"]] = relationship(back_populates="trainer", lazy="raise")
    services: Mapped[list["Service"]] = relationship(
        "Service", secondary="trainer_services", back_populates="trainers", lazy="raise"
    )
    arenas: Mapped[list["Arena"]] = relationship(
        "Arena", secondary="trainer_arenas", back_populates="trainers", lazy="raise"
    )
    cities: Mapped[list["City"]] = relationship(
        "City", secondary="trainer_cities", lazy="raise"
    )


class TrainerLinkToken(Base):
    """One-time token for trainer to link Telegram. Issued after site registration/payment."""
    __tablename__ = "trainer_link_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    # NULL for public landing tokens — trainer row is created when the user opens the bot link.
    trainer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optional entitlement attached by admin constructor at issue time; applied on first open.
    # welcome_grant_kind: 'trial' | 'paid' | NULL (legacy → trial on open).
    welcome_grant_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    welcome_grant_modules: Mapped[Optional[dict]] = mapped_column(JSONB(), nullable=True)
    welcome_grant_period_months: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    welcome_grant_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger(), nullable=True)
    welcome_grant_applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    trainer: Mapped[Optional["Trainer"]] = relationship(back_populates="link_tokens", lazy="raise")


class City(Base):
    """City for filtering trainers. Admin fills; trainer_profiles.city_id is the primary city.

    Catalog membership is ``trainer_cities`` (profile city plus cities of public arenas).

    ``country`` (ISO 3166-1 alpha-2: ``BY``/``RU``) drives display currency —
    see ``src.shared.currency.resolve_currency``. ``price_group`` selects which row of
    the subscription pricing tables applies (``BY_BASE``/``RU_BASE``/``RU_MOSCOW``/...) —
    see ``src.shared.currency.PRICE_GROUP_BY_COUNTRY``. Both default to the original
    all-Belarus behavior; only "Москва/МО" and "Санкт-Петербург/ЛО" differ so far.
    """
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    country: Mapped[str] = mapped_column(String(2), server_default="BY", nullable=False)
    price_group: Mapped[str] = mapped_column(String(16), server_default="BY_BASE", nullable=False)


class Arena(Base):
    """Venue/arena in a city: real place with address and optional coords for map link.

    ``is_active`` is soft-delete. ``is_confirmed`` is post-hoc moderation of trainer-created
    workplaces (TASK-046) — not the Ice Discovery vitrine flag. Publication of the catalog
    card lives on ``ArenaProfile.status`` (draft|published|archived).
    """
    __tablename__ = "arenas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_by_trainer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainers.id", ondelete="SET NULL"), nullable=True
    )
    is_confirmed: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger(), nullable=True)

    trainers: Mapped[list["Trainer"]] = relationship(
        "Trainer", secondary= lambda: trainer_arenas_table, back_populates="arenas", lazy="raise"
    )
    profile: Mapped[Optional["ArenaProfile"]] = relationship(
        back_populates="arena", uselist=False, lazy="raise"
    )


class ArenaProfile(Base):
    """
    Ice Discovery vitrine for one arena (1:1). Not parser config (see ice_parser_jobs).

    ``status`` publishes the catalog card (draft|published|archived). It is not
    ``arenas.is_confirmed``, which is post-hoc moderation of trainer-created workplaces.
    ``slug`` is unique per city and must stay stable after first issue — do not edit from
    admin without an explicit warning (future public URLs).
    """

    __tablename__ = "arena_profiles"
    __table_args__ = (
        UniqueConstraint("city_id", "slug", name="uq_arena_profiles_city_slug"),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_arena_profiles_status",
        ),
        CheckConstraint(
            "season_start_month IS NULL OR (season_start_month BETWEEN 1 AND 12)",
            name="ck_arena_profiles_season_start",
        ),
        CheckConstraint(
            "season_end_month IS NULL OR (season_end_month BETWEEN 1 AND 12)",
            name="ck_arena_profiles_season_end",
        ),
    )

    arena_id: Mapped[int] = mapped_column(
        ForeignKey("arenas.id", ondelete="CASCADE"), primary_key=True
    )
    city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    district: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    short_description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    tickets_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    social_urls: Mapped[dict] = mapped_column(JSONB(), nullable=False, server_default="{}")
    opening_hours: Mapped[Optional[dict]] = mapped_column(JSONB(), nullable=True)
    season_start_month: Mapped[Optional[int]] = mapped_column(SmallInteger(), nullable=True)
    season_end_month: Mapped[Optional[int]] = mapped_column(SmallInteger(), nullable=True)
    amenities: Mapped[dict] = mapped_column(JSONB(), nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="published")
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger(), nullable=True)

    arena: Mapped["Arena"] = relationship(back_populates="profile", lazy="raise")


class Media(Base):
    """Owner-typed image metadata (TASK-049). Files live in object storage; rows are not trainer_photos.

    ``owner_type`` is polymorphic (arena|coach|collective). Arena photos use this table;
    trainer catalog still reads ``trainer_photos``. Do not scrape search-engine images.
    """

    __tablename__ = "media"
    __table_args__ = (
        Index("ix_media_owner", "owner_type", "owner_id"),
        CheckConstraint(
            "owner_type IN ('arena', 'coach', 'collective')",
            name="ck_media_owner_type",
        ),
        CheckConstraint(
            "license IN ('own', 'operator', 'user', 'permitted')",
            name="ck_media_license",
        ),
        CheckConstraint(
            "status IN ('pending', 'published', 'rejected')",
            name="ck_media_status",
        ),
        CheckConstraint(
            "license = 'own' OR COALESCE(btrim(source_url), '') <> '' "
            "OR COALESCE(btrim(attribution), '') <> ''",
            name="ck_media_license_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[int] = mapped_column(Integer(), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    variants: Mapped[dict] = mapped_column(JSONB(), nullable=False, server_default="{}")
    width: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    blurhash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    license: Mapped[str] = mapped_column(String(20), nullable=False)
    attribution: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="published")


class IceSession(Base):
    """Canonical public-skate / open-ice slot (TASK-050).

    Admin manual entry and later parsers write the same columns after transform+validate.
    Client Ice tab will read only ``public_skate`` and ``open_ice``. Recurrence instances
    share ``recurrence_key``; cancelling one row must not resurrect on rematerialize.
    """

    __tablename__ = "ice_sessions"
    __table_args__ = (
        Index("ix_ice_sessions_arena_starts", "arena_id", "starts_at_utc"),
        Index("ix_ice_sessions_local_date_arena", "local_date", "arena_id"),
        Index(
            "uq_ice_sessions_recurrence_date",
            "recurrence_key",
            "local_date",
            unique=True,
            postgresql_where=text("recurrence_key IS NOT NULL"),
        ),
        CheckConstraint(
            "kind IN ('public_skate', 'open_ice', 'rental', 'school_group', 'event')",
            name="ck_ice_sessions_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'cancelled', 'superseded')",
            name="ck_ice_sessions_status",
        ),
        CheckConstraint(
            "price_adult_minor IS NULL OR price_adult_minor >= 0",
            name="ck_ice_sessions_price_adult",
        ),
        CheckConstraint(
            "price_child_minor IS NULL OR price_child_minor >= 0",
            name="ck_ice_sessions_price_child",
        ),
        CheckConstraint(
            "price_rental_minor IS NULL OR price_rental_minor >= 0",
            name="ck_ice_sessions_price_rental",
        ),
        CheckConstraint(
            "EXTRACT(EPOCH FROM (ends_at_utc - starts_at_utc)) / 60 BETWEEN 30 AND 120",
            name="ck_ice_sessions_duration",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    arena_id: Mapped[int] = mapped_column(
        ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_date: Mapped[date] = mapped_column(Date(), nullable=False)
    starts_at_local: Mapped[time] = mapped_column(Time(), nullable=False)
    ends_at_local: Mapped[time] = mapped_column(Time(), nullable=False)
    price_adult_minor: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    price_child_minor: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    price_rental_minor: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    price_minor: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    price_note: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    session_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    age_note: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    capacity_note: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    external_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    recurrence_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True)


class IceCityInterest(Base):
    """Client tap on Ice tab «скоро добавим катки» for a city without map rinks."""

    __tablename__ = "ice_city_interest"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    intent: Mapped[str] = mapped_column(String(16), nullable=False, server_default="skate")
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="coming_soon_cta")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# M2M: trainer works at these arenas; filter catalog by arena via this table
trainer_arenas_table = Table(
    "trainer_arenas",
    Base.metadata,
    Column("trainer_id", ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
    Column("arena_id", ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
    Column("is_public", Boolean(), nullable=False, server_default=text("true")),
    UniqueConstraint("trainer_id", "arena_id", name="uq_trainer_arenas_trainer_arena"),
)

# Catalog geography: profile city (is_primary) plus cities of public trainer_arenas.
trainer_cities_table = Table(
    "trainer_cities",
    Base.metadata,
    Column("trainer_id", ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
    Column("city_id", ForeignKey("cities.id", ondelete="CASCADE"), nullable=False),
    Column("is_primary", Boolean(), nullable=False, server_default=text("false")),
    UniqueConstraint("trainer_id", "city_id", name="uq_trainer_cities_trainer_city"),
    Index("ix_trainer_cities_city_id", "city_id"),
    Index(
        "uq_trainer_cities_one_primary",
        "trainer_id",
        unique=True,
        postgresql_where=text("is_primary"),
    ),
)


class TrainerProfile(Base):
    """Trainer card. Managed on site; required fields are enforced by profile completeness rules."""
    __tablename__ = "trainer_profiles"

    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), primary_key=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
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
    group_classes_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )  # When false, schedule UI/API disallow capacity > 1; opt-in via profile toggle
    # One-time onboarding funnel: first confirmed/completed booking + share-link tip (never repeat after cancel).
    first_booking_milestone_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    share_catalog_tip_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    moderation_readiness_notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Hub «Не сейчас» on the catalog invite. Server-side because a refusal must survive a
    # different device or a cleared cache — otherwise we keep asking someone who said no.
    catalog_invite_dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # P1/P2 (PRD): redeem — auto write-off on no-show for pass/cert; skip — do not redeem.
    pass_cert_no_show_policy: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="redeem"
    )
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
    # Uploaded diploma/certificate photos (list of {"file_key", "file_key_list"} dicts).
    document_photos: Mapped[Optional[dict]] = mapped_column(JSONB(), nullable=True)
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
    #: Plain text for client catalog «Подробнее» modal (what it is, for whom). Editable in DB / admin.
    client_summary: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    slug: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    vertical_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    effort_profile: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    scenario_tags: Mapped[Optional[dict]] = mapped_column(JSONB(), nullable=True)

    trainers: Mapped[list["Trainer"]] = relationship(
        "Trainer", secondary="trainer_services", back_populates="services", lazy="raise"
    )


# --- Client ↔ Trainer edge-state graph ---

class ClientTrainerEdge(Base):
    """
    One row per (client_id, trainer_id) pair — the live state of a client-trainer relationship.

    Design intent: edge-state, not a ledger of relation types.
    Orthogonal flags:
      is_saved    — client explicitly bookmarked this trainer (UX wishlist + intent signal)
      is_primary  — client's "main" trainer for context_type/context_id (overlay, never replaces history)
    Counters:
      completed_count — completed bookings with this trainer (strength signal for ranking/home)
    Timestamps:
      saved_at            — when last saved (recency signal; None if never saved)
      last_booking_at     — latest booking created (any status)
      last_completed_at   — latest completed booking (strongest engagement signal)
      last_interaction_at — latest of any meaningful interaction (union of above)
      created_at          — edge first created

    context_type / context_id: reserved for future scope; unused in APIs (always NULL until used).
    Enforced uniquely on (client_id, trainer_id) — one logical relationship row per pair
    (EPIC1 Slice 5: was (telegram_id, trainer_id) — one row per Telegram account shared across
    every client profile of that account. ``client_id`` is the real per-profile identity now, so a
    guardian/child profile gets its own "мой тренер"/saved/notify state instead of the parent's.
    ``telegram_id`` stays NOT NULL and keeps storing the *account's* Telegram id — still needed to
    address push notifications, since a guardian profile has no Telegram chat of its own).
    """
    __tablename__ = "client_trainer_edges"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "trainer_id",
            name="uq_client_trainer_pair",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_sessions.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- flags (orthogonal) ---
    is_saved: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # One-shot: cleared after notification is sent
    notify_when_slots: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    # --- strength counters ---
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # --- recency timestamps ---
    saved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notify_when_slots_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_booking_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_interaction_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- catalog context (align primary service with primary-trainer tier) ---
    last_booking_service_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    saved_catalog_service_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )

    # --- contextual primary scope (future-proof, unused in initial UI) ---
    context_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    context_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


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
    Client identity: by telegram_id (bot user), vk_user_id (MAX/VK Mini App), or phone_normalized (trainer-added).
    At least one of telegram_id, vk_user_id, or phone_normalized must be set for a valid row.
    """
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    vk_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    middle_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    phone_normalized: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    problematic: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # Onboarding demo identity: a sandbox client is excluded from CRM scope, stats, rhythm hints,
    # automated notifications and reminders. Lives only to show the trainer how the system feels.
    is_sandbox: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    bookings: Mapped[list["Booking"]] = relationship(back_populates="client", lazy="raise")
    client_requests: Mapped[list["ClientRequest"]] = relationship(back_populates="client", lazy="raise")


class ClientFamilyAccessMember(Base):
    """Extra Telegram user sharing the primary ``clients`` row (owner stays on ``clients.telegram_id``)."""

    __tablename__ = "client_family_access_members"
    __table_args__ = (
        UniqueConstraint("member_telegram_id", name="uq_cfam_member_telegram"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    primary_client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_telegram_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    invited_by_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Client profile links: one account can act as several profiles (self + children) ---
# Orthogonal to ClientFamilyAccessMember above: that table is "several Telegram accounts
# share ONE clients row" (e.g. both parents see the same kid's bookings). This table is the
# mirror case — "one Telegram account acts as SEVERAL clients rows" (one parent, several kids,
# each with independent booking history). See docs/adr/004-multi-profile-clients.md.
CLIENT_PROFILE_ROLE_SELF = "self"
CLIENT_PROFILE_ROLE_GUARDIAN = "guardian"


class ClientProfileLink(Base):
    """Which Telegram/VK account (``account_telegram_id``) may act as which client profile."""

    __tablename__ = "client_profile_links"
    __table_args__ = (
        UniqueConstraint(
            "account_telegram_id", "profile_client_id", name="uq_client_profile_links_account_profile"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_telegram_id: Mapped[int] = mapped_column(BigInteger(), nullable=False, index=True)
    profile_client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default=CLIENT_PROFILE_ROLE_GUARDIAN)
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Trainer-private notes about clients ---


class TrainerClientNote(Base):
    """Per-trainer private dossier about a client: profile fields + legacy note."""
    __tablename__ = "trainer_client_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    goals: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    limitations: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    level: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    season_goal: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    preferred_booking_daypart: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainerClientEntry(Base):
    """Timeline entry: dated note about a client (e.g. after a session)."""
    __tablename__ = "trainer_client_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainerClientTag(Base):
    """Quick-access tag for a client (e.g. 'Травма колена', 'Цель: аксель')."""
    __tablename__ = "trainer_client_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainerClientRoster(Base):
    """Explicit CRM link: trainer added client in «Мои клиенты» before any booking."""

    __tablename__ = "trainer_client_roster"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


RELAY_SESSION_OPEN = "open"
RELAY_SESSION_CLOSED = "closed"
RELAY_SENDER_TRAINER = "trainer"
RELAY_SENDER_CLIENT = "client"


class TrainerClientRelaySession(Base):
    """Bot-mediated chat when trainer↔client cannot use native Telegram DM (e.g. no @username)."""

    __tablename__ = "trainer_client_relay_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class TrainerClientRelayMessage(Base):
    __tablename__ = "trainer_client_relay_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("trainer_client_relay_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_role: Mapped[str] = mapped_column(String(16), nullable=False)
    body_text: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Trainer schedule: weekly template → generated slots for booking ---

class TrainerScheduleTemplate(Base):
    """Weekly pattern: e.g. 'every Monday 10:00 for 60 min'. Trainer adds these; we generate concrete slots."""
    __tablename__ = "trainer_schedule_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer(), nullable=False)  # 0=Monday .. 6=Sunday
    start_time: Mapped[time] = mapped_column(Time(), nullable=False)  # e.g. 10:00
    duration_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="60")
    capacity: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    service_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Required when capacity > 1 (group slot for this service).
    arena_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Group: venue on rows; individual: optional override (NULL → trainer default when generating slots).

    trainer: Mapped["Trainer"] = relationship(back_populates="schedule_templates", lazy="raise")


class TrainingGroup(Base):
    """Long-term cohort: roster, recurring schedule, optional catalog listing for recruitment."""

    __tablename__ = "training_groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False)
    arena_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    max_members: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="10")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    season_start_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    catalog_visible: Mapped[bool] = mapped_column(default=False, server_default="false")
    catalog_pitch: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingGroupScheduleRule(Base):
    """One recurring weekday + time within a training group."""

    __tablename__ = "training_group_schedule_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    training_group_id: Mapped[int] = mapped_column(
        ForeignKey("training_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_of_week: Mapped[int] = mapped_column(Integer(), nullable=False)  # 0=Monday .. 6=Sunday
    start_time: Mapped[time] = mapped_column(Time(), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="60")


class TrainingGroupMember(Base):
    __tablename__ = "training_group_members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    training_group_id: Mapped[int] = mapped_column(
        ForeignKey("training_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("training_group_id", "client_id", name="uq_training_group_member"),)


class TrainingGroupJoinRequest(Base):
    __tablename__ = "training_group_join_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    training_group_id: Mapped[int] = mapped_column(
        ForeignKey("training_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GroupAttendancePrompt(Base):
    """RSVP: one row per (group slot, member); send_at when to Telegram-prompt attendance."""

    __tablename__ = "group_attendance_prompts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    training_group_id: Mapped[int] = mapped_column(
        ForeignKey("training_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    response: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    booking_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("slot_id", "client_id", name="uq_group_attendance_prompt_slot_client"),)


class Slot(Base):
    """Concrete bookable slot: one date + time window. Generated from templates or added manually."""
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    slot_date: Mapped[date] = mapped_column(Date(), nullable=False)
    start_time: Mapped[time] = mapped_column(Time(), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available")  # available | booked | cancelled
    capacity: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    service_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Set when capacity > 1: group slot is for this service only.
    arena_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Venue for this slot (group: fixed; individual: default from trainer).
    training_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("training_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Set when slot is generated from a cohort (TrainingGroup).

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
    client_booking_completed_push_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    client_cancel_comment: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    # Resolved venue for this booking (primary when client chose "any arena", or explicit primary filter).
    arena_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    service_price_variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainer_service_price_variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    booking_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_tier_kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # tariff code snapshot
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )  # pending|confirmed|completed|cancelled|declined|no_show|payment_dispute|trainer_removed
    # Onboarding demo booking: excluded from stats, revenue, rhythm hints, reminders, repeat-gap pings,
    # inactive-client loop. Still claims the first-booking milestone so TTV step 2 mirrors real UX.
    is_sandbox: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # When status becomes cancelled: trainer / client / bulk system reasons. Stats omit recurring_detach & roster_detach churn.
    cancellation_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Set when this booking was created by recurring materialization (trainer CRM «постоянный клиент»).
    recurring_client_slot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recurring_client_slots.id", ondelete="SET NULL"), nullable=True, index=True
    )

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
    # Extra booking ids (same client, same calendar day) covered by this single push; ordered by slot start.
    merged_booking_ids: Mapped[Optional[list[int]]] = mapped_column(JSONB, nullable=True)


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
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainerPassProductService(Base):
    """Pass applies to listed services only; absence of rows for a product means all trainer services."""

    __tablename__ = "trainer_pass_product_services"

    pass_product_id: Mapped[int] = mapped_column(
        ForeignKey("trainer_pass_products.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), primary_key=True)


class TrainerPassProductTier(Base):
    """Pass applies to listed tier_kinds only; absence of rows means all price tiers are covered."""

    __tablename__ = "trainer_pass_product_tiers"

    pass_product_id: Mapped[int] = mapped_column(
        ForeignKey("trainer_pass_products.id", ondelete="CASCADE"), primary_key=True
    )
    tier_kind: Mapped[str] = mapped_column(String(64), primary_key=True)


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
    price_cents: Mapped[int] = mapped_column(Integer(), nullable=False)
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


class CertificateBookingCredit(Base):
    """Certificate balance applied to a completed booking (trainer analytics; avoids double revenue)."""

    __tablename__ = "certificate_booking_credits"

    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    certificate_instance_id: Mapped[int] = mapped_column(
        ForeignKey("certificate_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer(), nullable=False)


class TrainerCertificateProduct(Base):
    """Trainer-defined certificate: fixed amount (e.g. 100 BYN) or 'any amount'. Info only for clients."""
    __tablename__ = "trainer_certificate_products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="Подарочный сертификат")
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
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
    )  # Canonical base is crm; legacy values may exist until migrated
    modules: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"online": false, "analytics": false, "groups": false}',
    )  # Independent add-ons; each implies CRM base when true
    # 1 / 3 / 12 — last paid billing period for tier mock checkout (UX: "current" on period tab)
    billing_period_months: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # trial, active, past_due, cancelled
    payment_external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    trial_roi_recap_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    # When set, paid catalog checkout (tier/constructor): confirm applies modules + billing_period_months to trainer_subscriptions.
    checkout_modules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    checkout_billing_period_months: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    checkout_bundle_tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Referral "wallet": list price before proration; bonus days applied at payment confirm (redeemed from balance).
    referral_bonus_days_applied: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    amount_cents_before_referral: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)


class SubscriptionTierPricing(Base):
    """Admin-editable pricing for subscription tiers (crm/online/analytics).

    One row per (tier, price_group) — ``price_group`` (e.g. ``BY_BASE``/``RU_BASE``/
    ``RU_MOSCOW``) lets the same tier have different prices for different city groups,
    resolved via ``src.shared.currency.resolve_price_group``.
    """
    __tablename__ = "subscription_tier_pricing"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tier: Mapped[str] = mapped_column(
        Enum(*SUBSCRIPTION_TIERS, name="subscription_tier_enum", create_constraint=False),
        nullable=False,
    )
    price_group: Mapped[str] = mapped_column(String(16), server_default="BY_BASE", nullable=False)
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

    __table_args__ = (
        UniqueConstraint("tier", "price_group", name="uq_subscription_tier_pricing_tier_group"),
    )


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


class SubscriptionModulePeriodPricing(Base):
    """Surcharge pricing per module (online, analytics, groups) for 1/3/12 month periods.

    One row per (module, period_months, price_group) — see ``SubscriptionTierPricing``.
    """

    __tablename__ = "subscription_module_period_pricing"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    period_months: Mapped[int] = mapped_column(Integer(), nullable=False)
    price_group: Mapped[str] = mapped_column(String(16), server_default="BY_BASE", nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer(), nullable=False)
    period_days: Mapped[int] = mapped_column(Integer(), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), server_default="BYN", nullable=False)
    name_ru: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "module", "period_months", "price_group", name="uq_subscription_module_period_group"
        ),
    )


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


# --- Referral program (B2B: trainer invites trainer) ---

REFERRAL_CREDIT_REASON_ACCRUAL = "referral_accrual"
REFERRAL_CREDIT_REASON_ACCRUAL_ONBOARDING = "referral_accrual_onboarding"
REFERRAL_CREDIT_REASON_ACCRUAL_FIRST_BOOKING = "referral_accrual_first_booking"
REFERRAL_CREDIT_REASON_ACCRUAL_PAYMENT = "referral_accrual_payment"
REFERRAL_CREDIT_REASON_REDEMPTION = "subscription_redemption"
REFERRAL_CREDIT_REASON_ADMIN = "admin_adjustment"
REFERRAL_CREDIT_REASON_EXPIRY = "expiry"

REFERRAL_CREDIT_REASONS = (
    REFERRAL_CREDIT_REASON_ACCRUAL,
    REFERRAL_CREDIT_REASON_ACCRUAL_ONBOARDING,
    REFERRAL_CREDIT_REASON_ACCRUAL_FIRST_BOOKING,
    REFERRAL_CREDIT_REASON_ACCRUAL_PAYMENT,
    REFERRAL_CREDIT_REASON_REDEMPTION,
    REFERRAL_CREDIT_REASON_ADMIN,
    REFERRAL_CREDIT_REASON_EXPIRY,
)

# Positive referral-program accruals (excludes admin/redemption/expiry) — for caps and stats.
REFERRAL_PROGRAM_ACCRUAL_REASONS = (
    REFERRAL_CREDIT_REASON_ACCRUAL,
    REFERRAL_CREDIT_REASON_ACCRUAL_ONBOARDING,
    REFERRAL_CREDIT_REASON_ACCRUAL_FIRST_BOOKING,
    REFERRAL_CREDIT_REASON_ACCRUAL_PAYMENT,
)


class TrainerReferral(Base):
    """Attribution: which trainer referred which new trainer."""
    __tablename__ = "trainer_referrals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referred_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attribution_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    credit_granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarding_bonus_granted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_booking_bonus_granted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TrainerReferralCredit(Base):
    """Ledger of referral credit movements: accrual, redemption, admin adjustments."""
    __tablename__ = "trainer_referral_credits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_days: Mapped[int] = mapped_column(Integer(), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    referral_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainer_referrals.id", ondelete="SET NULL"), nullable=True
    )
    subscription_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainer_subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger(), nullable=True)


# --- Lead Mode: anonymous demand signals (proof of demand for post-trial trainers) ---
# Append-only event log. dedup_hash collapses refresh storms inside 24h windows.
# No user identifiers stored — only hash(ip||ua||trainer_id||day) which is irreversible.

DEMAND_EVENT_PROFILE_VIEW = "profile_view"
DEMAND_EVENT_CONTACT_CLICK = "contact_click"
DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED = "booking_attempt_blocked"
DEMAND_EVENT_CATALOG_FAVORITE = "catalog_favorite"

DEMAND_EVENT_KINDS = (
    DEMAND_EVENT_PROFILE_VIEW,
    DEMAND_EVENT_CONTACT_CLICK,
    DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED,
    DEMAND_EVENT_CATALOG_FAVORITE,
)

DEMAND_SOURCE_CATALOG = "catalog"
DEMAND_SOURCE_DIRECT_LINK = "direct_link"
DEMAND_SOURCE_SEARCH = "search"
DEMAND_SOURCE_BOT = "bot"
DEMAND_SOURCE_CLIENT_APP = "client_app"
# Opened via a shared trainer profile link (client→friend recommendation loop)
DEMAND_SOURCE_CLIENT_SHARE = "client_share"

DEMAND_SOURCES = (
    DEMAND_SOURCE_CATALOG,
    DEMAND_SOURCE_DIRECT_LINK,
    DEMAND_SOURCE_SEARCH,
    DEMAND_SOURCE_BOT,
    DEMAND_SOURCE_CLIENT_APP,
    DEMAND_SOURCE_CLIENT_SHARE,
)


class TrainerDemandEvent(Base):
    """Anonymous proof-of-demand event for a trainer's public presence (Lead Mode)."""
    __tablename__ = "trainer_demand_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # sha256(ip || ua || trainer_id || day) — irreversible, narrow window. Never store IP/UA in cleartext.
    dedup_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


# ---------------------------------------------------------------------------
# Client share events (TASK-096, gate G-P5) — what a client sent into a chat.
#
# Deliberately not trainer_demand_events: that one is Lead Mode and requires trainer_id,
# while the headline artifact is a city's ice schedule, which has no trainer at all.
# ---------------------------------------------------------------------------

CLIENT_SHARE_KIND_ICE_CITY_DAY = "ice_city_day"
CLIENT_SHARE_KIND_TRAINER = "trainer"

CLIENT_SHARE_KINDS = (
    CLIENT_SHARE_KIND_ICE_CITY_DAY,
    CLIENT_SHARE_KIND_TRAINER,
)


class ClientShareEvent(Base):
    """Append-only: a client opened the Telegram share dialog for one artifact."""
    __tablename__ = "client_share_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    share_context: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    city_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cities.id", ondelete="SET NULL"), nullable=True
    )
    arena_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True
    )
    trainer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trainers.id", ondelete="SET NULL"), nullable=True
    )
    # sha256(telegram_id || kind || day) — irreversible. Counts people, not identities.
    actor_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


# ---------------------------------------------------------------------------
# Lead Mode recovery nudges (D+0..D+30 reactivation series — idempotency log).
# ---------------------------------------------------------------------------

RECOVERY_STEP_D0 = "d0"
RECOVERY_STEP_D3 = "d3"
RECOVERY_STEP_D14 = "d14"
RECOVERY_STEP_D30 = "d30"

# Order matters: the loop fires the highest-eligible step at each tick, so steps with smaller
# offsets must come first. Days are anchored to last_subscription_expires_at.
RECOVERY_STEPS_ORDERED: tuple[tuple[str, int], ...] = (
    (RECOVERY_STEP_D0, 0),
    (RECOVERY_STEP_D3, 3),
    (RECOVERY_STEP_D14, 14),
    (RECOVERY_STEP_D30, 30),
)

RECOVERY_STEP_KEYS = tuple(s for s, _ in RECOVERY_STEPS_ORDERED)


# ---------------------------------------------------------------------------
# Care pulse — silence-aware presence check-in (trainers + clients).
# ---------------------------------------------------------------------------

CARE_PULSE_AUDIENCE_TRAINER = "trainer"
CARE_PULSE_AUDIENCE_CLIENT = "client"

CARE_PULSE_KIND_TOMORROW_PLAN = "tomorrow_plan"
CARE_PULSE_KIND_OPEN_SLOTS = "open_slots"
CARE_PULSE_KIND_INVITE_BACK = "invite_back"
CARE_PULSE_KIND_QUIET_CHECKIN = "quiet_checkin"
CARE_PULSE_KIND_CONFIRMED_BOOKING = "confirmed_booking"


class CarePulse(Base):
    """One honest Telegram check-in. Cooldown + unique (audience, recipient, kind, context)."""

    __tablename__ = "care_pulses"
    __table_args__ = (
        UniqueConstraint(
            "audience",
            "recipient_id",
            "kind",
            "context_key",
            name="uq_care_pulses_audience_recipient_kind_ctx",
        ),
        Index(
            "ix_care_pulses_audience_recipient_sent",
            "audience",
            "recipient_id",
            "sent_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_id: Mapped[int] = mapped_column(Integer(), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    context_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrainerRecoveryNudge(Base):
    """Idempotency log for Lead Mode recovery series. One row per (trainer_id, step) — append-only."""
    __tablename__ = "trainer_recovery_nudges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str] = mapped_column(String(8), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at_anchor: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# Onboarding reactivation nudges (D+1/D+3/D+7 series for stalled onboarding — idempotency log).
# ---------------------------------------------------------------------------

ONBOARDING_NUDGE_STEP_D1 = "d1"
ONBOARDING_NUDGE_STEP_D3 = "d3"
ONBOARDING_NUDGE_STEP_D7 = "d7"

# Order matters: the loop fires the highest-eligible step at each tick, so steps with smaller
# offsets must come first. Days are anchored to trainers.created_at (≈ Telegram link moment).
ONBOARDING_NUDGE_STEPS_ORDERED: tuple[tuple[str, int], ...] = (
    (ONBOARDING_NUDGE_STEP_D1, 1),
    (ONBOARDING_NUDGE_STEP_D3, 3),
    (ONBOARDING_NUDGE_STEP_D7, 7),
)

# TASK-035: a trainer whose trial burned out before they finished onboarding is otherwise total
# silence (no LEAD_MODE reachable from pending_profile). This step is deliberately NOT part of
# ONBOARDING_NUDGE_STEPS_ORDERED — that list is calendar offsets from created_at, but trial length
# is configurable (see resolve_trial_period_days), so this step is scheduled off the trainer's
# actual trial expiry instead (see get_trial_expired_days_ago).
ONBOARDING_NUDGE_STEP_TRIAL_OVER = "trialend"

ONBOARDING_NUDGE_STEP_KEYS = tuple(s for s, _ in ONBOARDING_NUDGE_STEPS_ORDERED) + (
    ONBOARDING_NUDGE_STEP_TRIAL_OVER,
)


# ---------------------------------------------------------------------------
# Profile enrichment after first real booking (tariffs / «что не входит»).
# ---------------------------------------------------------------------------

PROFILE_NUDGE_STEP_P1 = "p1"
PROFILE_NUDGE_STEP_P8 = "p8"
PROFILE_NUDGE_STEP_P21 = "p21"

# Days since first non-sandbox booking. Largest-unfired, same as onboarding reactivation.
PROFILE_NUDGE_STEPS_ORDERED: tuple[tuple[str, int], ...] = (
    (PROFILE_NUDGE_STEP_P1, 1),
    (PROFILE_NUDGE_STEP_P8, 8),
    (PROFILE_NUDGE_STEP_P21, 21),
)

PROFILE_NUDGE_STEP_KEYS = tuple(s for s, _ in PROFILE_NUDGE_STEPS_ORDERED)


class TrainerProfileNudge(Base):
    """Idempotency log for post-booking profile enrichment series. One row per (trainer_id, step)."""

    __tablename__ = "trainer_profile_nudges"
    __table_args__ = (
        UniqueConstraint("trainer_id", "step", name="ux_profile_nudges_trainer_step"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str] = mapped_column(String(8), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrainerOnboardingNudge(Base):
    """Idempotency log for onboarding reactivation series. One row per (trainer_id, step) — append-only."""
    __tablename__ = "trainer_onboarding_nudges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str] = mapped_column(String(8), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Stage id (see trainer_onboarding_recovery_use_cases) at the moment this step was sent —
    # lets us audit which nudge copy a trainer actually received.
    stage_anchor: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class TrainerFeatureFirstUse(Base):
    """
    Idempotency log for TASK-028 feature-adoption tracking. One row per (trainer_id, feature),
    ever — atomic ``INSERT ... ON CONFLICT DO NOTHING`` claims it exactly once (see
    ``trainer_feature_tracking.record_feature_first_use``). Small table by construction: at
    most ``len(FEATURE_KEYS)`` rows per trainer for the trainer's whole lifetime.
    """

    __tablename__ = "trainer_feature_first_use"
    __table_args__ = (
        UniqueConstraint("trainer_id", "feature", name="ux_feature_first_use_trainer_feature"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False
    )
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    first_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrainerHintDismissal(Base):
    """
    TASK-029: server-side «Не сейчас» for hub rhythm hints. One row per (trainer_id, hint_id)
    — upserted, not append-only (unlike the nudge logs above): ``snooze_until`` moves forward
    each time the trainer dismisses the same hint again after it returned. ``dismissed_at`` is
    the most recent dismissal timestamp, kept for display/audit; the *decision* of whether the
    hint is currently hidden is ``snooze_until > now()``, checked in
    ``trainer_hint_dismissal_use_cases.get_active_snoozes``.
    """

    __tablename__ = "trainer_hint_dismissals"
    __table_args__ = (
        UniqueConstraint("trainer_id", "hint_id", name="ux_hint_dismissals_trainer_hint"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trainer_id: Mapped[int] = mapped_column(
        ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False
    )
    hint_id: Mapped[str] = mapped_column(String(32), nullable=False)
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    snooze_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
