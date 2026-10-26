"""Mogilev ice palace: schedule and buy links from ByCard.

The hockey.by table has no mass-skating rows for the coming week, while the arena sells
tickets through ByCard with sessions a week ahead. The parser reads ByCard first and keeps
the hockey.by table as the fallback; this adds the ByCard source to the existing job config.

Revision ID: 0273_mogilev_bycard_source
Revises: 0272_single_plan_ru_base
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0273_mogilev_bycard_source"
down_revision = "0272_single_plan_ru_base"
branch_labels = None
depends_on = None

_PARSER_KEY = "mogilev_ds_v1"
_PATCH = {
    "bycard_schedule_url": (
        "https://abws.bycard.by/api/v2/schedule/events/1307519"
        "?cityId=23&lang=ru&slug=true&jsonld=0&ignoreEndTime=1"
    ),
    "bycard_object_id": 4982,
    "session_tickets_url": "https://saleframe.bycard.by/?sid={session_id}&lang=ru",
}


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE ice_parser_jobs SET config = config || CAST(:patch AS jsonb), next_run_at = now() "
            "WHERE parser_key = :key"
        ),
        {"patch": json.dumps(_PATCH), "key": _PARSER_KEY},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE ice_parser_jobs SET config = config - 'bycard_schedule_url' - 'bycard_object_id' "
            "- 'session_tickets_url' WHERE parser_key = :key"
        ),
        {"key": _PARSER_KEY},
    )
