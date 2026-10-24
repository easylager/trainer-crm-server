"""Brest ice palace: rental-with-ice prices from the price sheet «новые цены с 17.08.2026».

The sheet sells skates only bundled with ice (rental + ice), in two skate fleets,
so they go in as services rows rather than into the single price_rental_minor.
Own-skates ice prices (adult 6.30 / child 5.30) already come from the live prices
page into the session rows.

Revision ID: 0262_brest_rental_prices
Revises: 0261_gomel_rental_price
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0262_brest_rental_prices"
down_revision = "0261_gomel_rental_price"
branch_labels = None
depends_on = None

VISIT = {
    "rental": {"deposit": "документ, удостоверяющий личность"},
    "services": [
        {"kind": "rental", "label": "Прокат + лёд, взрослый", "price": "13,10 BYN"},
        {"kind": "rental", "label": "Прокат + лёд, детский до 12 лет", "price": "11,10 BYN"},
        {
            "kind": "rental",
            "label": "Прокат (коньки 2024 г.) + лёд, взрослый",
            "price": "17,90 BYN",
            "note": "размеры 35–37, 39–43, 46",
        },
        {
            "kind": "rental",
            "label": "Прокат (коньки 2024 г.) + лёд, детский",
            "price": "16,90 BYN",
            "note": "размеры 35–37, 39",
        },
    ],
}


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE arena_profiles SET visit_info = COALESCE(visit_info, '{}'::jsonb) || CAST(:v AS jsonb) "
            "WHERE arena_id = 22"
        ),
        {"v": json.dumps(VISIT, ensure_ascii=False)},
    )


def downgrade() -> None:
    op.execute("UPDATE arena_profiles SET visit_info = visit_info - 'rental' - 'services' WHERE arena_id = 22")
