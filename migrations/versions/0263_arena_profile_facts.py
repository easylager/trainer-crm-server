"""Parking, cafe and changing-room chips for Belarusian rinks, from the owner's check (2026-10-24).

Only what was confirmed: either by the owner or on the rink's own site. Unknown stays unset,
so no chip is shown. Notes carry the nuance (paid parking, cafe name). The amenities flags
are kept in step with the chips so filters and chips never disagree.

Revision ID: 0263_arena_profile_facts
Revises: 0262_brest_rental_prices
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0263_arena_profile_facts"
down_revision = "0262_brest_rental_prices"
branch_labels = None
depends_on = None

FACTS: dict[int, dict] = {
    # zamok
    3: {"parking": {"state": "yes", "note": "бесплатный крытый 4-уровневый паркинг, 2000+ мест"}, "cafe": {"state": "yes", "note": "кафе и рестораны в ТЦ"}, "locker_rooms": {"state": "yes", "note": "есть камеры хранения"}},
    # minsk-ledlife
    4: {"parking": {"state": "yes", "note": ""}, "cafe": {"state": "yes", "note": ""}, "locker_rooms": {"state": "yes", "note": ""}},
    # ledby
    5: {"parking": {"state": "yes", "note": "для клиентов"}, "cafe": {"state": "yes", "note": ""}, "locker_rooms": {"state": "yes", "note": ""}},
    # minsk-diamond
    7: {"parking": {"state": "yes", "note": "бесплатная"}, "cafe": {"state": "yes", "note": "ресторан и кафе-бар на 2 этаже ТРЦ"}, "locker_rooms": {"state": "yes", "note": ""}},
    # grodno-triniti
    10: {"locker_rooms": {"state": "yes", "note": "есть камеры хранения"}},
    # grodno-neman
    11: {"cafe": {"state": "yes", "note": "кафе «Арена»"}},
    # raubichi-rcop
    15: {"parking": {"state": "yes", "note": "перед ареной небольшая бесплатная стоянка; по выходным въезд на территорию комплекса обычно платный (около 5 BYN)"}, "cafe": {"state": "yes", "note": "кафе-пиццерия на 2 этаже"}, "locker_rooms": {"state": "yes", "note": "10 раздевалок в здании"}},
    # vitebsk-ds
    29: {"locker_rooms": {"state": "yes", "note": "гардероб в фойе"}},
    # orsha-arena
    31: {"parking": {"state": "yes", "note": "бесплатная стоянка перед зданием"}, "cafe": {"state": "yes", "note": "буфеты и кофе-автоматы"}, "locker_rooms": {"state": "yes", "note": "большой гардероб"}},
    # bobruisk-arena
    38: {"parking": {"state": "yes", "note": "бесплатная"}, "cafe": {"state": "yes", "note": "буфеты и кафе-бар «Овертайм»"}, "locker_rooms": {"state": "yes", "note": "гардероб и камера хранения"}},
    # ostrovets-lds
    41: {"parking": {"state": "yes", "note": ""}, "cafe": {"state": "no", "note": "в фойе автоматы с кофе, напитками и снеками"}, "locker_rooms": {"state": "yes", "note": "переобуться и оставить обувь"}},
    # mogilev-ds
    43: {"parking": {"state": "yes", "note": "бесплатная парковка вокруг дворца"}, "cafe": {"state": "yes", "note": "ледовые буфеты"}, "locker_rooms": {"state": "yes", "note": "гардероб и зона для переодевания"}},
    # mozyr-global-ice
    217: {"parking": {"state": "yes", "note": ""}, "cafe": {"state": "yes", "note": ""}, "locker_rooms": {"state": "yes", "note": ""}},
}

# Уже были в проде до этой миграции (0258): откат их не трогает.
PREEXISTING: dict[int, set[str]] = {41: {"locker_rooms"}}


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
        removable = [key for key in facts if key not in PREEXISTING.get(arena_id, set())]
        if not removable:
            continue
        expr = "COALESCE(visit_info->'facts', '{}'::jsonb)" + "".join(f" - '{key}'" for key in removable)
        bind.execute(
            sa.text(
                "UPDATE arena_profiles SET visit_info = COALESCE(visit_info, '{}'::jsonb) "
                f"|| jsonb_build_object('facts', {expr}) WHERE arena_id = :a"
            ),
            {"a": arena_id},
        )
