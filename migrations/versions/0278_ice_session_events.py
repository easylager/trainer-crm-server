"""Журнал изменений слотов льда: кто, когда и что добавил или убрал.

Триггер на ``ice_sessions`` ловит любую запись (парсер, админка, скрипты), поэтому журнал
не зависит от того, что кто-то забыл вызвать логирование в новом пути записи.

В журнал попадают только слоты, которые ещё не закончились: чистка прошедших
(``expired``, TTL) шума не создаёт. Обновление цены или ``observed_at`` событием не считается.

Источник: тег из ``SET LOCAL app.change_source`` (его ставит ручное удаление и правка в админке),
иначе по самой строке: ``admin`` → manual, ``schedule_basis='photo'`` → screenshot,
``run:*`` → parser, остальное (``little:``, ``big:``, пусто) → script.

Revision ID: 0278_ice_session_events
Revises: 0277_arena_schedule_inbox
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0278_ice_session_events"
down_revision = "0277_arena_schedule_inbox"
branch_labels = None
depends_on = None

_FUNCTION = """
CREATE OR REPLACE FUNCTION ice_sessions_log_event() RETURNS trigger AS $$
DECLARE
    ref ice_sessions%ROWTYPE;
    ev text;
    src text;
    tag text := NULLIF(current_setting('app.change_source', true), '');
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status = 'active' AND NEW.ends_at_utc > now() THEN ev := 'added'; ref := NEW; END IF;
    ELSIF TG_OP = 'DELETE' THEN
        IF OLD.status = 'active' AND OLD.ends_at_utc > now() THEN ev := 'removed'; ref := OLD; END IF;
    ELSE
        IF OLD.status = 'active' AND NEW.status <> 'active' AND OLD.ends_at_utc > now() THEN
            ev := 'removed'; ref := OLD;
        ELSIF OLD.status <> 'active' AND NEW.status = 'active' AND NEW.ends_at_utc > now() THEN
            ev := 'added'; ref := NEW;
        ELSIF OLD.status = 'active' AND NEW.status = 'active' AND NEW.ends_at_utc > now()
              AND (OLD.starts_at_utc <> NEW.starts_at_utc OR OLD.ends_at_utc <> NEW.ends_at_utc
                   OR OLD.kind <> NEW.kind) THEN
            ev := 'changed'; ref := NEW;
        END IF;
    END IF;
    IF ev IS NULL THEN
        RETURN NULL;
    END IF;
    src := COALESCE(
        tag,
        CASE
            WHEN ref.source_id = 'admin' THEN 'manual'
            WHEN ref.schedule_basis = 'photo' THEN 'screenshot'
            WHEN ref.source_id LIKE 'run:%' THEN 'parser'
            ELSE 'script'
        END
    );
    INSERT INTO ice_session_events
        (arena_id, event, kind, local_date, starts_at_local, ends_at_local, starts_at_utc, source)
    VALUES
        (ref.arena_id, ev, ref.kind, ref.local_date, ref.starts_at_local, ref.ends_at_local,
         ref.starts_at_utc, src);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "ice_session_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("event", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("starts_at_local", sa.Time(), nullable=False),
        sa.Column("ends_at_local", sa.Time(), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.CheckConstraint("event IN ('added', 'removed', 'changed')", name="ck_ice_session_events_event"),
        sa.CheckConstraint(
            "source IN ('parser', 'manual', 'screenshot', 'script')", name="ck_ice_session_events_source"
        ),
    )
    op.create_index("ix_ice_session_events_arena_time", "ice_session_events", ["arena_id", sa.text("occurred_at DESC")])
    op.create_index("ix_ice_session_events_time", "ice_session_events", [sa.text("occurred_at DESC")])
    op.execute(_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_ice_sessions_log_event AFTER INSERT OR UPDATE OR DELETE ON ice_sessions "
        "FOR EACH ROW EXECUTE FUNCTION ice_sessions_log_event()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ice_sessions_log_event ON ice_sessions")
    op.execute("DROP FUNCTION IF EXISTS ice_sessions_log_event()")
    op.drop_index("ix_ice_session_events_time", table_name="ice_session_events")
    op.drop_index("ix_ice_session_events_arena_time", table_name="ice_session_events")
    op.drop_table("ice_session_events")
