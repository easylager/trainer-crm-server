"""Third batch of chips (owner's check, 2026-10-25): the remaining gaps.

Soligorsk (parking, changing rooms), Baranovichi (changing rooms, cafe), Vitebsk (cafe «Айс»),
Molodechno (changing rooms: a cloakroom for visitors). Brest stays open: no facts came back.

Revision ID: 0267_arena_facts_batch3
Revises: 0266_arena_facts_batch2
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0267_arena_facts_batch3"
down_revision = "0266_arena_facts_batch2"
branch_labels = None
depends_on = None

FACTS: dict[int, dict] = {
    # soligorsk-szk
    19: {"parking": {"state": "yes", "note": ""}, "locker_rooms": {"state": "yes", "note": ""}},
    # baranovichi-lds
    23: {"locker_rooms": {"state": "yes", "note": ""}, "cafe": {"state": "yes", "note": "кафе и буфет"}},
    # vitebsk-ds
    29: {"cafe": {"state": "yes", "note": "кафе «Айс»"}},
    # molodechno-src
    18: {"locker_rooms": {"state": "yes", "note": "гардероб для посетителей"}},
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
