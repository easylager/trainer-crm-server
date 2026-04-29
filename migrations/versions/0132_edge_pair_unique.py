"""Deduplicate client_trainer_edges; one row per (client, trainer).

PostgreSQL UNIQUE on (tid, trainer, ctx_type, ctx_id) treats NULL <> NULL,
so inserts with NULL contexts created duplicate pairs. Replace with UNIQUE(tid, trainer).
Revision id <= 32 chars (alembic_version.version_num).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0132_edge_pair_unique"
down_revision = "0131_client_trainer_edges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("""
WITH per_pair AS (
  SELECT
      telegram_id,
      trainer_id,
      BOOL_OR(is_saved)::boolean AS is_saved,
      BOOL_OR(is_primary)::boolean AS is_primary,
      MAX(completed_count)::integer AS completed_count,
      MAX(saved_at) AS saved_at,
      MAX(last_booking_at) AS last_booking_at,
      MAX(last_completed_at) AS last_completed_at,
      MAX(last_interaction_at) AS last_interaction_at,
      MIN(created_at) AS created_at
  FROM client_trainer_edges
  GROUP BY telegram_id, trainer_id
  HAVING COUNT(*) > 1
),
keeper AS (
  SELECT MIN(id) AS id, telegram_id, trainer_id
  FROM client_trainer_edges
  GROUP BY telegram_id, trainer_id
)
UPDATE client_trainer_edges e
SET
  is_saved = p.is_saved,
  is_primary = p.is_primary,
  completed_count = p.completed_count,
  saved_at = p.saved_at,
  last_booking_at = p.last_booking_at,
  last_completed_at = p.last_completed_at,
  last_interaction_at = p.last_interaction_at,
  created_at = p.created_at,
  context_type = NULL,
  context_id = NULL
FROM per_pair p
JOIN keeper k ON k.telegram_id = p.telegram_id AND k.trainer_id = p.trainer_id
WHERE e.id = k.id
    """))

    conn.execute(sa.text("""
DELETE FROM client_trainer_edges AS e
USING (
  SELECT id, ROW_NUMBER() OVER (
      PARTITION BY telegram_id, trainer_id ORDER BY id ASC
  ) AS rn
  FROM client_trainer_edges
) AS dup
WHERE e.id = dup.id AND dup.rn > 1
    """))

    op.drop_constraint("uq_client_trainer_context", "client_trainer_edges", type_="unique")
    op.create_unique_constraint(
        "uq_client_trainer_pair",
        "client_trainer_edges",
        ["telegram_id", "trainer_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_client_trainer_pair", "client_trainer_edges", type_="unique")
    op.create_unique_constraint(
        "uq_client_trainer_context",
        "client_trainer_edges",
        ["telegram_id", "trainer_id", "context_type", "context_id"],
    )
