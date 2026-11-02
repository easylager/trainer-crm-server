"""led.by: disco («Массовое катание*») sessions have their own flat price page.

The ``ledby_html_v1`` parser now reads every time in a timetable cell and prices «*» sessions
from ``disco_prices_url`` (60 мин: взрослый 10,0 / детский 8,0 руб.) instead of the regular
weekday price. This adds the key to the existing job config (merge, other keys untouched).

Revision ID: 0299_ledby_disco_prices_url
Revises: 0298_zhodino_sdyushor_parser
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0299_ledby_disco_prices_url"
down_revision = "0298_zhodino_sdyushor_parser"
branch_labels = None
depends_on = None

_PARSER_KEY = "ledby_html_v1"
_DISCO_URL = (
    "https://led.by/%d0%bc%d0%b0%d1%81%d1%81%d0%be%d0%b2%d0%be%d0%b5-"
    "%d0%ba%d0%b0%d1%82%d0%b0%d0%bd%d0%b8%d0%b5/"
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE ice_parser_jobs "
            "SET config = COALESCE(config, '{}'::jsonb) || jsonb_build_object('disco_prices_url', CAST(:u AS text)) "
            "WHERE parser_key = :k"
        ),
        {"k": _PARSER_KEY, "u": _DISCO_URL},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE ice_parser_jobs SET config = config - 'disco_prices_url' WHERE parser_key = :k"),
        {"k": _PARSER_KEY},
    )
