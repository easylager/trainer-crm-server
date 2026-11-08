"""services.client_summary for «Хоккейное катание»: shorter, player-facing copy.

The row is a shared reference (same text on every trainer's card, catalog modal and Mini App).
Only the untouched seed text from 0130 is replaced — a manually edited summary stays.

Revision ID: 0308_hockey_skating_summary
Revises: 0307_booking_source
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0308_hockey_skating_summary"
down_revision = "0307_booking_source"
branch_labels = None
depends_on = None

_NAME = "Хоккейное катание"
_OLD = """Хоккейная стойка, ход, повороты и торможения так, чтобы техника катания не мешала в игре с шайбой и не требовала переделки.

Подойдёт и тем, кто уже в хоккее, и тем, кто мечтает уверенно держаться на льду «как игрок». Фокус — скорость, стабильность и экономичность движений под будущие элементы с шайбой и клюшкой."""
_NEW = "Взрывной старт, маневренность и всё, что нужно для идеального катания в игре."


def _swap(src: str, dst: str) -> None:
    op.execute(
        sa.text("UPDATE services SET client_summary = :dst WHERE name = :name AND client_summary = :src").bindparams(
            dst=dst, src=src, name=_NAME
        )
    )


def upgrade() -> None:
    _swap(_OLD, _NEW)


def downgrade() -> None:
    _swap(_NEW, _OLD)
