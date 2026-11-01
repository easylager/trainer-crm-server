"""Сезонные (зимние) катки и коробки (TASK-343): точка, сезон, отметки, фото, сигналы, модерация.

``arenas`` (venue_type='outdoor') не меняем; ``arena_profiles.catalog_pin`` — nullable-колонка
для закрепа «Немига первой». Остальное — create_table.

Revision ID: 0290_winter_rinks
Revises: 0284_speed_oval_mk_areas
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0290_winter_rinks"
down_revision = "0284_speed_oval_mk_areas"
branch_labels = None
depends_on = None

_NOW = sa.text("now()")


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def upgrade() -> None:
    op.add_column("arena_profiles", sa.Column("catalog_pin", sa.SmallInteger(), nullable=True))

    op.create_table(
        "seasonal_rinks",
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("operator", sa.String(256), nullable=True),
        #: NULL — цена не известна («уточняйте»); false — бесплатно (по умолчанию для seed)
        sa.Column("is_paid", sa.Boolean(), nullable=True),
        sa.Column("price_note", sa.String(128), nullable=True),
        sa.Column("often_hockey", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("geocode_precision", sa.String(16), nullable=False, server_default="none"),
        sa.Column("source_key", sa.String(64), nullable=True, unique=True),
        sa.Column("name_source", sa.String(10), nullable=False, server_default="source"),
        #: тот же стадион / двор: каток и коробка с одним адресом (дубли не склеиваем)
        sa.Column("same_complex_id", sa.Integer(), nullable=True),
        #: пин поставлен вручную — импорт его не двигает
        sa.Column("pin_manual", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _ts("gone_reset_at", nullable=True),
        _ts("created_at", server_default=_NOW, nullable=False),
        _ts("updated_at", server_default=_NOW, nullable=False),
        sa.CheckConstraint("kind IN ('rink', 'hockey_box')", name="ck_seasonal_rinks_kind"),
        sa.CheckConstraint(
            "geocode_precision IN ('osm_exact', 'house', 'street', 'city', 'manual', 'none')",
            name="ck_seasonal_rinks_precision",
        ),
    )

    op.create_table(
        "seasonal_rink_seasons",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="waiting"),
        _ts("state_at", server_default=_NOW, nullable=False),
        sa.Column("state_source", sa.String(12), nullable=False, server_default="import"),
        sa.Column("quality", sa.String(8), nullable=True),
        sa.Column("dispute", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        #: «Возможно, точки больше нет»: 3 сигнала; точку показываем серой, скрывает только админ
        sa.Column("doubtful", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _ts("admin_confirmed_at", nullable=True),
        sa.Column("hidden_reason", sa.String(24), nullable=True),
        sa.Column("hours_text", sa.String(256), nullable=True),
        sa.Column("opening_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("hours_known", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hours_season", sa.String(9), nullable=True),
        sa.Column("season_from", sa.String(5), nullable=True),
        sa.Column("season_to", sa.String(8), nullable=True),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.Column("source_kind", sa.String(16), nullable=True),
        sa.Column("confidence", sa.String(12), nullable=True),
        _ts("updated_at", server_default=_NOW, nullable=False),
        sa.UniqueConstraint("arena_id", "season", name="uq_seasonal_rink_seasons_arena_season"),
        sa.CheckConstraint(
            "state IN ('waiting', 'flooded', 'stale', 'closed', 'hidden')",
            name="ck_seasonal_rink_seasons_state",
        ),
    )
    op.create_index("ix_seasonal_rink_seasons_state", "seasonal_rink_seasons", ["season", "state"])

    op.create_table(
        "seasonal_rink_marks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("value", sa.String(16), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("actor", sa.String(80), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("photo_id", sa.BigInteger(), nullable=True),
        #: uuid шторки: повторная отправка той же отметки возвращает прежний результат
        sa.Column("idem_key", sa.String(40), nullable=True),
        _ts("created_at", server_default=_NOW, nullable=False),
        sa.CheckConstraint("kind IN ('ice', 'crowd', 'hockey')", name="ck_seasonal_rink_marks_kind"),
        sa.CheckConstraint(
            "source IN ('site', 'telegram', 'miniapp', 'photo')", name="ck_seasonal_rink_marks_source"
        ),
    )
    op.create_index("ix_seasonal_rink_marks_arena", "seasonal_rink_marks", ["arena_id", "kind", "created_at"])
    op.create_index("ix_seasonal_rink_marks_actor", "seasonal_rink_marks", ["actor", "arena_id", "created_at"])
    op.execute(
        "CREATE UNIQUE INDEX uq_seasonal_rink_marks_idem ON seasonal_rink_marks (actor, idem_key) "
        "WHERE idem_key IS NOT NULL"
    )

    op.create_table(
        "seasonal_rink_photos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("variants", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("ice_claim", sa.Boolean(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("blurred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("dhash", sa.String(16), nullable=True),
        sa.Column("report_count", sa.SmallInteger(), nullable=False, server_default="0"),
        _ts("created_at", server_default=_NOW, nullable=False),
        _ts("decided_at", nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'wrong_place')",
            name="ck_seasonal_rink_photos_status",
        ),
    )
    op.create_index("ix_seasonal_rink_photos_arena", "seasonal_rink_photos", ["arena_id", "status"])
    op.create_index("ix_seasonal_rink_photos_author", "seasonal_rink_photos", ["author_telegram_id"])
    op.create_index("ix_seasonal_rink_photos_sha", "seasonal_rink_photos", ["sha256"])

    op.create_table(
        "seasonal_rink_photo_reports",
        sa.Column(
            "photo_id", sa.BigInteger(), sa.ForeignKey("seasonal_rink_photos.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("actor", sa.String(80), primary_key=True),
        _ts("created_at", server_default=_NOW, nullable=False),
    )

    op.create_table(
        "seasonal_rink_signals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.String(80), nullable=False),
        _ts("created_at", server_default=_NOW, nullable=False),
    )
    op.create_index("ix_seasonal_rink_signals_arena", "seasonal_rink_signals", ["arena_id", "created_at"])

    op.create_table(
        "seasonal_moderation_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=True),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(8), nullable=False, server_default="open"),
        sa.Column("resolution", sa.String(24), nullable=True),
        _ts("created_at", server_default=_NOW, nullable=False),
        _ts("resolved_at", nullable=True),
        sa.Column("resolved_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('gone', 'dispute', 'photo_first', 'new_point')", name="ck_seasonal_moderation_kind"
        ),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck_seasonal_moderation_status"),
    )
    op.create_index("ix_seasonal_moderation_open", "seasonal_moderation_items", ["status", "created_at"])
    # Одна открытая карточка на (вид, точка, ссылка): повторный сигнал не плодит очередь.
    op.execute(
        "CREATE UNIQUE INDEX uq_seasonal_moderation_open ON seasonal_moderation_items "
        "(kind, COALESCE(arena_id, 0), COALESCE(ref_id, 0)) WHERE status = 'open'"
    )


def downgrade() -> None:
    op.drop_table("seasonal_moderation_items")
    op.drop_table("seasonal_rink_photo_reports")
    op.drop_table("seasonal_rink_signals")
    op.drop_table("seasonal_rink_photos")
    op.drop_table("seasonal_rink_marks")
    op.drop_table("seasonal_rink_seasons")
    op.drop_table("seasonal_rinks")
    op.drop_column("arena_profiles", "catalog_pin")
