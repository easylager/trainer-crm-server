"""Certificates: drop "any amount" products, add background file-generation status (TASK-142)."""

from alembic import op
import sqlalchemy as sa

revision = "0208_certificate_fixed_amount"
down_revision = "0207_collective_operators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AC-001/EDGE-001: "any amount" (amount_cents IS NULL) products used to let a
    # trainer issue a certificate that silently stored amount_cents=0 — unredeemable
    # (AC-005). No new product can be created this way (app-level validation); this
    # deactivates the pre-existing ones in prod (id=3, id=8) so they can't be used
    # to issue another one.
    op.execute("UPDATE trainer_certificate_products SET is_active = false WHERE amount_cents IS NULL")

    # AC-002: certificate issuance moves PDF render / S3 upload / email off the
    # request path into a background worker; the trainer's screen polls this status.
    op.add_column(
        "certificate_instances",
        sa.Column("file_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column(
        "certificate_instances",
        sa.Column("file_error", sa.Text(), nullable=True),
    )
    # Certificates issued before this migration already have their PDF (or never
    # will) — don't queue them for background generation.
    op.execute("UPDATE certificate_instances SET file_status = 'ready' WHERE file_url IS NOT NULL")


def downgrade() -> None:
    op.drop_column("certificate_instances", "file_error")
    op.drop_column("certificate_instances", "file_status")
    # Not reversing the is_active=false backfill — reactivating "any amount"
    # products would resurrect a known bug (AC-005).
