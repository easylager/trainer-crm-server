"""Generic single-database configuration."""

from alembic import op
import sqlalchemy as sa


${message}

revision = ${repr(up_revision_id)}
down_revision = ${repr(down_revision_id)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

