"""ice_parser_jobs ORM. Keep this off Arena in infrastructure.db.models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.models import Base


class IceParserJob(Base):
    """One arena × one parser strategy. Parser code is not this row."""

    __tablename__ = "ice_parser_jobs"
    __table_args__ = (
        UniqueConstraint("arena_id", name="uq_ice_parser_jobs_arena_id"),
        CheckConstraint(
            "cadence IN ('hourly', 'daily', 'weekly')",
            name="ck_ice_parser_jobs_cadence",
        ),
        Index("ix_ice_parser_jobs_due", "is_enabled", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    arena_id: Mapped[int] = mapped_column(
        ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False
    )
    parser_key: Mapped[str] = mapped_column(String(64), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false")
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False, server_default=text("'{}'::jsonb"))
    notes: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
