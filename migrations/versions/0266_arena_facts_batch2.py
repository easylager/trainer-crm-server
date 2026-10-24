"""Second batch of parking, cafe and changing-room chips (owner's check, 2026-10-24).

Pinsk, Chizhovka, Yunost (no parking — the chip says so), Soligorsk (cafe), Novopolotsk,
Gomel, Vitebsk and Baranovichi (own parking), Gorki. Additive: facts already on a card stay
unless this batch states the same key again.

Revision ID: 0266_arena_facts_batch2
Revises: 0265_molodechno_rink_facts
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0266_arena_facts_batch2"
down_revision = "0265_molodechno_rink_facts"
branch_labels = None
depends_on = None

FACTS: dict[int, dict] = {
    # pinsk-volna
    24: {"locker_rooms": {"state": "yes", "note": "раздевалки и душевые"}, "cafe": {"state": "yes", "note": "буфет: горячие напитки и выпечка"}, "parking": {"state": "yes", "note": ""}},
    # chizhovka
    6: {"parking": {"state": "yes", "note": ""}, "cafe": {"state": "yes", "note": ""}, "locker_rooms": {"state": "yes", "note": ""}},
    # minsk-junost
    8: {"cafe": {"state": "yes", "note": ""}, "locker_rooms": {"state": "yes", "note": ""}, "parking": {"state": "no", "note": ""}},
    # soligorsk-szk
    19: {"cafe": {"state": "yes", "note": "буфеты в фойе; в здании бар SHTUKA DJ BAR"}},
    # novopolotsk-lds
    30: {"parking": {"state": "yes", "note": ""}, "cafe": {"state": "yes", "note": ""}, "locker_rooms": {"state": "yes", "note": ""}},
    # gomel-lds
    33: {"parking": {"state": "yes", "note": ""}, "cafe": {"state": "yes", "note": ""}, "locker_rooms": {"state": "yes", "note": ""}},
    # vitebsk-ds
    29: {"parking": {"state": "yes", "note": "собственная парковка"}},
    # baranovichi-lds
    23: {"parking": {"state": "yes", "note": "собственная парковка"}},
    # gorki-lds
    32: {"locker_rooms": {"state": "yes", "note": ""}, "cafe": {"state": "yes", "note": "стационарное кафе"}, "parking": {"state": "yes", "note": "бесплатная, перед зданием"}},
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
