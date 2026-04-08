"""
Referral program: B2B trainer-to-trainer attribution and credit ledger.

- trainer_referrals: attribution link (referrer → referred trainer)
- trainer_referral_credits: ledger of credit movements (accrual / redemption / admin adjustment)
- trainers.referral_code: stable short code for deep links (nullable, unique)

Revision ID: 0078
Revises: 0077_trainer_client_dossier
"""
from alembic import op
import sqlalchemy as sa


revision = "0078"
down_revision = "0077_trainer_client_dossier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Stable referral code on trainer (short, unique, for deep links)
    op.add_column(
        "trainers",
        sa.Column("referral_code", sa.String(16), nullable=True, unique=True),
    )
    op.create_index("ix_trainers_referral_code", "trainers", ["referral_code"], unique=True)

    # Attribution: who referred whom
    op.create_table(
        "trainer_referrals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "referrer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "referred_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,  # one referrer per trainer
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Attribution window: if referred trainer pays within N days of created_at, credit is granted
        sa.Column("attribution_expires_at", sa.DateTime(timezone=True), nullable=False),
        # Denormalized: set when first qualifying payment triggers credit
        sa.Column("credit_granted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Credit ledger: accrual (positive), redemption (negative), admin adjustments
    op.create_table(
        "trainer_referral_credits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Amount in subscription-days (positive = accrual, negative = redemption)
        sa.Column("amount_days", sa.Integer(), nullable=False),
        # Reason: 'referral_accrual', 'subscription_redemption', 'admin_adjustment', 'expiry'
        sa.Column("reason", sa.String(64), nullable=False),
        # Optional link to referral row (for accruals)
        sa.Column(
            "referral_id",
            sa.Integer(),
            sa.ForeignKey("trainer_referrals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Optional link to subscription row (for redemptions)
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("trainer_subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),  # telegram_id of admin if manual
    )


def downgrade() -> None:
    op.drop_table("trainer_referral_credits")
    op.drop_table("trainer_referrals")
    op.drop_index("ix_trainers_referral_code", table_name="trainers")
    op.drop_column("trainers", "referral_code")
