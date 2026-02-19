"""
DB models. One source of truth for schema; Alembic migrations follow these.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Trainer(Base):
    """Trainer: created on site (or by admin); telegram_id set when they open link."""
    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    link_tokens: Mapped[list["TrainerLinkToken"]] = relationship(back_populates="trainer", lazy="raise")
    profile: Mapped[Optional["TrainerProfile"]] = relationship(back_populates="trainer", uselist=False, lazy="raise")
    services: Mapped[list["Service"]] = relationship(
        "Service", secondary="trainer_services", back_populates="trainers", lazy="raise"
    )


class TrainerLinkToken(Base):
    """One-time token for trainer to link Telegram. Issued after site registration/payment."""
    __tablename__ = "trainer_link_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    trainer: Mapped["Trainer"] = relationship(back_populates="link_tokens", lazy="raise")


class TrainerProfile(Base):
    """Trainer card: description, phone, contacts. One-to-one with trainers."""
    __tablename__ = "trainer_profiles"

    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id", ondelete="CASCADE"), primary_key=True)
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    contacts: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trainer: Mapped["Trainer"] = relationship(back_populates="profile", lazy="raise")


class Service(Base):
    """Catalog of services (e.g. hockey, figure skating). Admin fills; trainer picks."""
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", nullable=False)

    trainers: Mapped[list["Trainer"]] = relationship(
        "Trainer", secondary="trainer_services", back_populates="services", lazy="raise"
    )
