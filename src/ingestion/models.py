"""ice_parser_jobs and ice_scrape_runs ORM. Keep these off Arena in infrastructure.db.models."""
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


class IceScrapeRun(Base):
    """One parser attempt. empty/error/blocked must not delete future ice_sessions."""

    __tablename__ = "ice_scrape_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'empty', 'error', 'blocked')",
            name="ck_ice_scrape_runs_status",
        ),
        Index("ix_ice_scrape_runs_job_finished", "job_id", "finished_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("ice_parser_jobs.id", ondelete="CASCADE"), nullable=False
    )
    arena_id: Mapped[int] = mapped_column(
        ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)
    slots_found: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    slots_dropped: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    raw_ref: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
