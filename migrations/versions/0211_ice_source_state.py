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
    # История прогонов не хранит число показанных сеансов на момент empty. Поэтому
    # используем видимые сейчас сеансы парсера как proxy: empty — сбой, только если
    # сеансы остаются на витрине при миграции; иначе empty сбрасывает серию. Это не
    # точное восстановление исторического состояния, зато не объявляет empty с
    # пустой текущей витриной сбоем без доказательств.
    op.execute(
        """
        WITH visible_sessions AS (
            SELECT s.arena_id, COUNT(*)::int AS shown_sessions
            FROM ice_sessions AS s
            WHERE s.status = 'active'
              AND s.kind IN ('public_skate', 'open_ice')
              AND s.starts_at_utc > now()
              AND (s.valid_until IS NULL OR s.valid_until >= now())
              AND (s.source_id IS NULL OR s.source_id NOT LIKE 'etalon_%')
              AND (s.source_id IS NULL OR s.source_id <> 'admin')
            GROUP BY s.arena_id
        ),
        classified_runs AS (
            SELECT r.job_id,
                   r.finished_at,
                   r.id,
                   r.status,
                   r.error_code,
                   r.error_summary,
                   COALESCE(v.shown_sessions, 0) AS shown_sessions,
                   CASE
                       WHEN r.status IN ('error', 'blocked') THEN true
                       WHEN r.status = 'empty' AND COALESCE(v.shown_sessions, 0) > 0 THEN true
                       ELSE false
                   END AS is_failure
            FROM ice_scrape_runs AS r
            JOIN ice_parser_jobs AS jj ON jj.id = r.job_id
            LEFT JOIN visible_sessions AS v ON v.arena_id = jj.arena_id
        ),
        last_reset AS (
            SELECT DISTINCT ON (job_id) job_id, finished_at, id
            FROM classified_runs
            WHERE NOT is_failure
            ORDER BY job_id, finished_at DESC, id DESC
        ),
        failures_since_reset AS (
            SELECT run.*
            FROM classified_runs AS run
            LEFT JOIN last_reset AS reset ON reset.job_id = run.job_id
            WHERE run.is_failure
              AND (
                  reset.job_id IS NULL
                  OR (run.finished_at, run.id) > (reset.finished_at, reset.id)
              )
        ),
        f AS (
            SELECT job_id,
                   MIN(finished_at) AS first_fail,
                   COUNT(*)::int AS n,
                   (ARRAY_AGG(
                       CASE
                           WHEN status = 'empty' THEN 'empty_after_slots'
                           ELSE COALESCE(error_code, status)
                       END
                       ORDER BY finished_at DESC, id DESC
                   ))[1] AS last_code,
                   (ARRAY_AGG(
                       CASE
                           WHEN status = 'empty' THEN
                               'источник вернул 0 сеансов; сейчас показано '
                               || shown_sessions::text || ' сеансов'
                           ELSE error_summary
                       END
                       ORDER BY finished_at DESC, id DESC
                   ))[1] AS last_summary
            FROM failures_since_reset
            GROUP BY job_id
        )
        UPDATE ice_parser_jobs AS j
        SET failing_since = f.first_fail,
            failure_streak = f.n,
            last_error_code = f.last_code,
            last_error_summary = f.last_summary
        FROM f
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
