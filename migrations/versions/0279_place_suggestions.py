"""place_suggestions: user-submitted places + moderation thread; city coords.

Also ``arenas.venue_type`` += ``school`` (``ck_arenas_venue_type``, last set in 0208).

Revision ID: 0279_place_suggestions
Revises: 0278_ice_session_events
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0279_place_suggestions"
down_revision = "0278_ice_session_events"
branch_labels = None
depends_on = None

_KINDS = ("ice", "outdoor", "shop", "school")
_STATUSES = ("new", "needs_info", "approved", "rejected", "duplicate")
_SOURCES = ("site", "miniapp")
_CONTACT_KINDS = ("email", "telegram", "other")
_DIRECTIONS = ("to_author", "from_author", "note")

# Держать в синхроне с src/shared/venue_types.py (VENUE_TYPE_KEYS).
_VENUE_TYPES_NEW = "('ice', 'gym', 'choreo', 'pool', 'outdoor', 'other', 'shop', 'school')"
_VENUE_TYPES_OLD = "('ice', 'gym', 'choreo', 'pool', 'outdoor', 'other', 'shop')"


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.drop_constraint("ck_arenas_venue_type", "arenas", type_="check")
    op.create_check_constraint("ck_arenas_venue_type", "arenas", f"venue_type IN {_VENUE_TYPES_NEW}")

    op.create_table(
        "place_suggestions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("new_city_name", sa.String(120), nullable=True),
        sa.Column("new_city_country", sa.String(2), nullable=True),
        sa.Column("new_city_region", sa.String(160), nullable=True),
        sa.Column("new_city_lat", sa.Float(), nullable=True),
        sa.Column("new_city_lon", sa.Float(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(300), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("contact", sa.String(120), nullable=True),
        sa.Column("contact_kind", sa.String(16), nullable=True),
        sa.Column("author_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("bind_token", sa.String(32), nullable=True, unique=True),
        sa.Column("target_arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("result_arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reject_reason", sa.String(32), nullable=True),
        sa.Column("client_ip_hash", sa.String(64), nullable=True),
        sa.CheckConstraint(_in("kind", _KINDS), name="ck_place_suggestions_kind"),
        sa.CheckConstraint(_in("status", _STATUSES), name="ck_place_suggestions_status"),
        sa.CheckConstraint(_in("source", _SOURCES), name="ck_place_suggestions_source"),
        sa.CheckConstraint(f"contact_kind IS NULL OR {_in('contact_kind', _CONTACT_KINDS)}",
                           name="ck_place_suggestions_contact_kind"),
        sa.CheckConstraint("city_id IS NOT NULL OR new_city_name IS NOT NULL",
                           name="ck_place_suggestions_city"),
    )
    op.create_index("ix_place_suggestions_status", "place_suggestions", ["status", "created_at"])
    op.create_index("ix_place_suggestions_author", "place_suggestions", ["author_telegram_id"])

    op.create_table(
        "place_suggestion_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("suggestion_id", sa.BigInteger(),
                  sa.ForeignKey("place_suggestions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.CheckConstraint(_in("direction", _DIRECTIONS), name="ck_place_suggestion_messages_direction"),
    )
    op.create_index("ix_place_suggestion_messages_sid", "place_suggestion_messages", ["suggestion_id", "created_at"])

    op.add_column("cities", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("cities", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("cities", sa.Column("region", sa.String(160), nullable=True))
    op.add_column("arena_profiles", sa.Column(
        "visitor_prices", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("arena_profiles", "visitor_prices")
    op.drop_column("cities", "region")
    op.drop_column("cities", "longitude")
    op.drop_column("cities", "latitude")
    op.drop_index("ix_place_suggestion_messages_sid", table_name="place_suggestion_messages")
    op.drop_table("place_suggestion_messages")
    op.drop_index("ix_place_suggestions_author", table_name="place_suggestions")
    op.drop_index("ix_place_suggestions_status", table_name="place_suggestions")
    op.drop_table("place_suggestions")
    # Школы в типы катков молча не превращаем: откат упадёт на CHECK, пока они есть.
    op.drop_constraint("ck_arenas_venue_type", "arenas", type_="check")
    op.create_check_constraint("ck_arenas_venue_type", "arenas", f"venue_type IN {_VENUE_TYPES_OLD}")
