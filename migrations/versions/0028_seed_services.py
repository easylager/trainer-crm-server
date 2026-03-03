"""Seed default services (catalog). One-time insert; downgrade removes by name.

Revision ID: 0028_seed_services
Revises: 0027_session_duration
"""
from alembic import op
import sqlalchemy as sa


revision = "0028_seed_services"
down_revision = "0027_session_duration"
branch_labels = None
depends_on = None

SERVICES = [
    "Обучение катанию «с нуля»",
    "Совершенствование катания",
    "Фигурное катание",
    "Хоккейное катание",
    "Катание на роликах",
    "ОХМ(отработка хоккейного мастерства)",
    "ОФП/СФП",
]


def upgrade() -> None:
    for i, name in enumerate(SERVICES):
        op.execute(
            sa.text("INSERT INTO services (name, sort_order) VALUES (:name, :sort_order)").bindparams(
                name=name, sort_order=i
            ),
        )


def downgrade() -> None:
    for name in SERVICES:
        op.execute(sa.text("DELETE FROM services WHERE name = :name").bindparams(name=name))
