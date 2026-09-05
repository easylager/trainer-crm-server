"""ice_scrape_runs: per-attempt parser outcomes, TTL, success-rate views (TASK-072).

Revision ID: 0198_ice_scrape_runs
Revises: 0197_trainer_cities
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0198_ice_scrape_runs"
down_revision = "0197_trainer_cities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ice_scrape_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("ice_parser_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("slots_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("slots_dropped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("raw_ref", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ok', 'empty', 'error', 'blocked')",
            name="ck_ice_scrape_runs_status",
        ),
    )
    op.create_index(
        "ix_ice_scrape_runs_job_finished",
        "ice_scrape_runs",
        ["job_id", "finished_at"],
    )
    op.execute(
        sa.text(
            """
            CREATE VIEW ice_scrape_run_success_rates AS
            SELECT
                job_id,
                COUNT(*) FILTER (WHERE finished_at >= now() - interval '7 days') AS finished_7d,
                COUNT(*) FILTER (
                    WHERE status = 'ok' AND finished_at >= now() - interval '7 days'
                ) AS ok_7d,
                CASE
                    WHEN COUNT(*) FILTER (WHERE finished_at >= now() - interval '7 days') = 0
                    THEN NULL
                    ELSE (
                        COUNT(*) FILTER (
                            WHERE status = 'ok' AND finished_at >= now() - interval '7 days'
                        )::numeric
                        / COUNT(*) FILTER (WHERE finished_at >= now() - interval '7 days')
                    )
                END AS success_rate_7d,
                COUNT(*) FILTER (WHERE finished_at >= now() - interval '30 days') AS finished_30d,
                COUNT(*) FILTER (
                    WHERE status = 'ok' AND finished_at >= now() - interval '30 days'
                ) AS ok_30d,
                CASE
                    WHEN COUNT(*) FILTER (WHERE finished_at >= now() - interval '30 days') = 0
                    THEN NULL
                    ELSE (
                        COUNT(*) FILTER (
                            WHERE status = 'ok' AND finished_at >= now() - interval '30 days'
                        )::numeric
                        / COUNT(*) FILTER (WHERE finished_at >= now() - interval '30 days')
                    )
                END AS success_rate_30d
            FROM ice_scrape_runs
            GROUP BY job_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE VIEW ice_arenas_no_result AS
            SELECT
                j.id AS job_id,
                j.arena_id,
                r.status AS last_status,
                r.finished_at AS last_finished_at
            FROM ice_parser_jobs AS j
            JOIN LATERAL (
                SELECT status, finished_at
                FROM ice_scrape_runs
                WHERE job_id = j.id
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
            ) AS r ON true
            WHERE r.status <> 'ok'
              AND NOT EXISTS (
                SELECT 1
                FROM ice_sessions AS s
                WHERE s.arena_id = j.arena_id
                  AND s.kind IN ('public_skate', 'open_ice')
                  AND s.status = 'active'
                  AND s.starts_at_utc > now()
                  AND (s.valid_until IS NULL OR s.valid_until > now())
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS ice_arenas_no_result"))
    op.execute(sa.text("DROP VIEW IF EXISTS ice_scrape_run_success_rates"))
    op.drop_index("ix_ice_scrape_runs_job_finished", table_name="ice_scrape_runs")
    op.drop_table("ice_scrape_runs")
