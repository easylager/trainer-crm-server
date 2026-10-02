"""Состояние источника льда на ice_parser_jobs: свежесть и алерты по арене (TASK-146).

Одна строка задания = один источник арены, поэтому состояние живёт прямо на ней:
- last_ok_at / last_ok_slot_count — когда расписание последний раз прочитано успешно
  и сколько сеансов в нём было (основа флага schedule_stale в публичном API);
- failing_since / failure_streak / last_error_* — текущая серия сбоев (бэкофф
  планировщика и текст алерта «что сломалось и с какого времени»);
- alert_state / alert_sent_at — дедупликация пушей в админ-бот: алерт на переходе
  в сбой, напоминание не чаще раза в несколько часов, «восстановлено» на выходе.

Revision ID: 0211_ice_source_state
Revises: 0210_catalog_entry_clicks
"""

import sqlalchemy as sa
from alembic import op

revision = "0211_ice_source_state"
down_revision = "0210_catalog_entry_clicks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ice_parser_jobs", sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ice_parser_jobs", sa.Column("last_ok_slot_count", sa.Integer(), nullable=True))
    op.add_column("ice_parser_jobs", sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ice_parser_jobs",
        sa.Column("failure_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("ice_parser_jobs", sa.Column("last_error_code", sa.String(64), nullable=True))
    op.add_column("ice_parser_jobs", sa.Column("last_error_summary", sa.Text(), nullable=True))
    op.add_column(
        "ice_parser_jobs",
        sa.Column("alert_state", sa.String(16), nullable=False, server_default="ok"),
    )
    op.add_column("ice_parser_jobs", sa.Column("alert_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_ice_parser_jobs_alert_state", "ice_parser_jobs", "alert_state IN ('ok', 'failing')"
    )
    # Бэкфилл из истории прогонов: без него каждая арена после деплоя выглядела бы
    # «ни разу не читанной» и флаг устаревания загорелся бы на всём каталоге сразу.
    op.execute(
        """
        UPDATE ice_parser_jobs AS j
        SET last_ok_at = ok.finished_at,
            last_ok_slot_count = ok.slots_found
        FROM (
            SELECT DISTINCT ON (job_id) job_id, finished_at, slots_found
            FROM ice_scrape_runs
            WHERE status = 'ok'
            ORDER BY job_id, finished_at DESC, id DESC
        ) AS ok
        WHERE ok.job_id = j.id
        """
    )
    # Текущая серия сбоев: error/blocked-прогоны после последнего ok.
    op.execute(
        """
        UPDATE ice_parser_jobs AS j
        SET failing_since = f.first_fail,
            failure_streak = f.n,
            last_error_code = f.last_code,
            last_error_summary = f.last_summary
        FROM (
            SELECT r.job_id,
                   MIN(r.finished_at) AS first_fail,
                   COUNT(*)::int AS n,
                   (ARRAY_AGG(r.error_code ORDER BY r.finished_at DESC, r.id DESC))[1] AS last_code,
                   (ARRAY_AGG(r.error_summary ORDER BY r.finished_at DESC, r.id DESC))[1] AS last_summary
            FROM ice_scrape_runs AS r
            JOIN ice_parser_jobs AS jj ON jj.id = r.job_id
            WHERE r.status IN ('error', 'blocked')
              AND (jj.last_ok_at IS NULL OR r.finished_at > jj.last_ok_at)
            GROUP BY r.job_id
        ) AS f
        WHERE f.job_id = j.id
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_ice_parser_jobs_alert_state", "ice_parser_jobs", type_="check")
    for column in (
        "alert_sent_at",
        "alert_state",
        "last_error_summary",
        "last_error_code",
        "failure_streak",
        "failing_since",
        "last_ok_slot_count",
        "last_ok_at",
    ):
        op.drop_column("ice_parser_jobs", column)
