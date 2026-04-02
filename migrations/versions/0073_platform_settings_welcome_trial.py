"""platform_settings (welcome trial days) + backfill trial tier analytics.

Revision ID: 0073_platform_settings_welcom
Revises: 0072_client_completion_push
"""
from alembic import op
import sqlalchemy as sa


revision = "0073_platform_settings_welcom"
down_revision = "0072_client_completion_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value_int", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.execute(
        """
        INSERT INTO platform_settings (key, value_int)
        VALUES ('welcome_trial_period_days', 21)
        """
    )
    # Legacy rows: trial without tier — grant max tier for remaining trial/active segments
    op.execute(
        """
        UPDATE trainer_subscriptions AS ts
        SET tier = 'analytics'
        FROM subscription_plans sp
        WHERE ts.plan_id = sp.id
          AND sp.is_trial = true
          AND ts.tier IS NULL
          AND ts.status IN ('trial', 'active')
          AND ts.expires_at > CURRENT_TIMESTAMP
        """
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
