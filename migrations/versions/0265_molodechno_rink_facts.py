"""Molodechno sports and entertainment centre: cafe and parking.

Confirmed by the owner on 2026-10-24. Changing rooms stay as they are (the old amenities flag
keeps showing the chip until the owner says whether it is a changing room or only a cloakroom).

Revision ID: 0265_molodechno_rink_facts
Revises: 0264_grodno_rink_facts
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0265_molodechno_rink_facts"
down_revision = "0264_grodno_rink_facts"
branch_labels = None
depends_on = None

FACTS: dict[int, dict] = {
    # molodechno-src
    18: {
        "parking": {"state": "yes", "note": ""},
        "cafe": {"state": "yes", "note": ""},
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    for arena_id, facts in FACTS.items():
        amenities = {key: item["state"] == "yes" for key, item in facts.items()}
        bind.execute(
            sa.text(
                "UPDATE arena_profiles SET "
                "visit_info = COALESCE(visit_info, '{}'::jsonb) || jsonb_build_object("
                "'facts', COALESCE(visit_info->'facts', '{}'::jsonb) || CAST(:facts AS jsonb)), "
                "amenities = COALESCE(amenities, '{}'::jsonb) || CAST(:amenities AS jsonb) "
                "WHERE arena_id = :a"
            ),
            {"facts": json.dumps(facts, ensure_ascii=False), "amenities": json.dumps(amenities), "a": arena_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for arena_id, facts in FACTS.items():
        expr = "COALESCE(visit_info->'facts', '{}'::jsonb)" + "".join(f" - '{key}'" for key in facts)
        bind.execute(
            sa.text(
                "UPDATE arena_profiles SET visit_info = COALESCE(visit_info, '{}'::jsonb) "
                f"|| jsonb_build_object('facts', {expr}) WHERE arena_id = :a"
            ),
            {"a": arena_id},
        )
