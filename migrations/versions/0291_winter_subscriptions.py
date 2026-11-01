"""Зимние подписки, лимит рассылки и вопрос «Были? Как лёд?» (TASK-343).

Revision ID: 0291_winter_subscriptions
Revises: 0290_winter_rinks
"""
import sqlalchemy as sa
from alembic import op

revision = "0291_winter_subscriptions"
down_revision = "0290_winter_rinks"
branch_labels = None
depends_on = None

_NOW = sa.text("now()")


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def upgrade() -> None:
    op.create_table(
        "winter_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("radius_m", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _ts("created_at", server_default=_NOW, nullable=False),
        _ts("last_notified_at", nullable=True),
        #: dead — бот заблокирован / чат удалён; unsubscribed — «Не присылать»
        sa.Column("deactivated_reason", sa.String(16), nullable=True),
        sa.CheckConstraint("kind IN ('near', 'point')", name="ck_winter_subscriptions_kind"),
    )
    op.create_index("ix_winter_subscriptions_telegram_id", "winter_subscriptions", ["telegram_id"])
    op.create_index("ix_winter_subscriptions_active", "winter_subscriptions", ["kind", "active"])
    op.execute(
        "CREATE UNIQUE INDEX uq_winter_sub_point ON winter_subscriptions (telegram_id, arena_id) "
        "WHERE kind = 'point'"
    )
    op.execute("CREATE UNIQUE INDEX uq_winter_sub_near ON winter_subscriptions (telegram_id) WHERE kind = 'near'")

    op.create_table(
        "winter_push_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("arena_id", sa.Integer(), nullable=True),
        sa.Column("topic", sa.String(16), nullable=False, server_default="flooded"),
        _ts("sent_at", server_default=_NOW, nullable=False),
    )
    op.create_index("ix_winter_push_log_tg", "winter_push_log", ["telegram_id", "sent_at"])

    op.create_table(
        "winter_asks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("via", sa.String(8), nullable=False),
        _ts("due_at", nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        _ts("asked_at", nullable=True),
        _ts("answered_at", nullable=True),
        _ts("created_at", server_default=_NOW, nullable=False),
        sa.CheckConstraint("via IN ('route')", name="ck_winter_asks_via"),
        sa.CheckConstraint(
            "status IN ('pending', 'asked', 'answered', 'dismissed')", name="ck_winter_asks_status"
        ),
    )
    op.create_index("ix_winter_asks_due", "winter_asks", ["status", "due_at"])

    op.create_table(
        "winter_user_prefs",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
        sa.Column("no_ask", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ignored_streak", sa.SmallInteger(), nullable=False, server_default="0"),
        _ts("paused_until", nullable=True),
        _ts("last_ask_at", nullable=True),
        #: сессия «фото точки N»: принимаем фото до photo_until (TTL 30 мин)
        sa.Column("photo_arena_id", sa.Integer(), nullable=True),
        _ts("photo_until", nullable=True),
        sa.Column("photo_banned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _ts("updated_at", server_default=_NOW, nullable=False),
    )

    op.create_table(
        "winter_flood_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        _ts("flooded_at", server_default=_NOW, nullable=False),
        _ts("fanned_out_at", nullable=True),
    )
    op.create_index("ix_winter_flood_events_arena", "winter_flood_events", ["arena_id", "flooded_at"])

    op.create_table(
        "winter_notify_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "event_id", sa.BigInteger(), sa.ForeignKey("winter_flood_events.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("reason", sa.String(8), nullable=False),
        _ts("created_at", server_default=_NOW, nullable=False),
        _ts("sent_at", nullable=True),
        sa.UniqueConstraint("telegram_id", "arena_id", "event_id", name="uq_winter_notify_queue_once"),
        sa.CheckConstraint("reason IN ('point', 'near')", name="ck_winter_notify_queue_reason"),
    )
    op.create_index("ix_winter_notify_queue_pending", "winter_notify_queue", ["sent_at", "telegram_id"])


def downgrade() -> None:
    op.drop_table("winter_notify_queue")
    op.drop_table("winter_flood_events")
    op.drop_table("winter_user_prefs")
    op.drop_table("winter_asks")
    op.drop_table("winter_push_log")
    op.drop_table("winter_subscriptions")
