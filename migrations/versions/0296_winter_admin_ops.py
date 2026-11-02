"""Админ-часть «Зимних катков» (TASK-343, волна 2): пачки действий, импорт-раны, 301 со старых slug.

Только create_table.

* ``winter_admin_batches`` / ``winter_admin_batch_items`` — журнал массовых действий («подтвердить на
  сезон», «скрыть», применение диффа) с данными для отмены в течение 10 минут;
* ``winter_import_runs`` — сверка с таблицей нового сезона: дифф и исходные строки до подтверждения;
* ``arena_slug_redirects`` — старый slug -> актуальная точка (переименование, слияние дублей).

Revision ID: 0296_winter_admin_ops
Revises: 0295_kk_bot_notices
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0296_winter_admin_ops"
down_revision = "0295_kk_bot_notices"
branch_labels = None
depends_on = None

_NOW = sa.text("now()")


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def upgrade() -> None:
    op.create_table(
        "winter_admin_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("selection", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        _ts("created_at", server_default=_NOW, nullable=False),
        _ts("undone_at", nullable=True),
        sa.CheckConstraint(
            "action IN ('confirm', 'hide', 'import_changed', 'import_missing', 'merge')",
            name="ck_winter_admin_batches_action",
        ),
    )
    op.create_table(
        "winter_admin_batch_items",
        sa.Column(
            "batch_id", sa.BigInteger(), sa.ForeignKey("winter_admin_batches.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("closed_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
    )
    op.create_table(
        "winter_import_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(256), nullable=True),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("applied_parts", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        _ts("created_at", server_default=_NOW, nullable=False),
        _ts("closed_at", nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'rejected', 'failed')", name="ck_winter_import_runs_status"
        ),
    )
    op.create_index("ix_winter_import_runs_status", "winter_import_runs", ["status", "created_at"])
    op.create_index("ix_winter_import_runs_sha", "winter_import_runs", ["season", "file_sha256"])
    op.create_table(
        "arena_slug_redirects",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_slug", sa.String(160), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.String(8), nullable=False),
        _ts("created_at", server_default=_NOW, nullable=False),
        sa.UniqueConstraint("city_id", "old_slug", name="uq_arena_slug_redirects_city_slug"),
        sa.CheckConstraint("reason IN ('rename', 'merge')", name="ck_arena_slug_redirects_reason"),
    )
    op.create_index("ix_arena_slug_redirects_arena", "arena_slug_redirects", ["arena_id"])


def downgrade() -> None:
    op.drop_table("arena_slug_redirects")
    op.drop_table("winter_import_runs")
    op.drop_table("winter_admin_batch_items")
    op.drop_table("winter_admin_batches")
