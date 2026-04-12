"""Active trial subscriptions: full modules (online, analytics, groups).

Revision ID: 0093_trial_full_modules_backfill
Revises: 0092_subscription_modules
"""
from alembic import op

revision = "0093_trial_full_modules_backfill"
down_revision = "0092_subscription_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE trainer_subscriptions AS ts
        SET
          tier = 'crm',
          modules = jsonb_build_object('online', true, 'analytics', true, 'groups', true)
        FROM subscription_plans sp
        WHERE ts.plan_id = sp.id
          AND sp.is_trial = true
          AND ts.status IN ('trial', 'active')
          AND ts.expires_at > NOW()
    """)


def downgrade() -> None:
    # Irreversible: previous module flags per row are not stored.
    pass
