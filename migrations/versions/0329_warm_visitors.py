"""Прогрев разовых посетителей: учёт сообщений, «не присылать», события предложения подписки (TASK-428).

Revision ID: 0329_warm_visitors
Revises: 0328_kk_notify_kinds
Create Date: 2026-11-17

Только добавления:

* ``warm_notices`` — «занято» и итог каждого сообщения прогрева (строка ставится до вызова Telegram). Ключ —
  человек (``telegram_id``), повод и ``ref`` (``once`` — один раз за всё время, ``d2026-11-20`` — раз в сутки,
  ``w2026-W47`` — раз в неделю). Внешнего ключа на клиента нет: учёт не должен исчезать вслед за клиентом,
  иначе пропала бы защита от повтора. Кроме ``telegram_id`` и катка личного здесь нет.
* ``warm_prefs`` — «Не присылать» (действует на все поводы прогрева сразу) и блокировка бота, замеченная
  при отправке прогрева.
* CHECK на ``catalog_consumer_events.kind`` расширен событиями воронки предложения подписки:
  ``watch_offer_shown``, ``watch_offer_click``, ``watch_offer_closed``, ``watch_offer_subscribed``.

Откат намеренно НЕ теряет данные: таблицы остаются (повторный накат их не пересоздаёт: ``IF NOT EXISTS``),
строки новых событий не удаляются, прежний CHECK возвращается как ``NOT VALID`` — старый код новые виды вставить
не сможет, а уже лежащие строки не мешают. Повторный накат пересоздаёт CHECK и проверяет все строки.
"""

from __future__ import annotations

from alembic import op

revision = "0329_warm_visitors"
down_revision = "0328_kk_notify_kinds"
branch_labels = None
depends_on = None

_OLD_KINDS = (
    "'public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry', "
    "'public_contact_click', 'invite_create', 'invite_open', 'invite_no_attempt', "
    "'invite_yes', 'invite_send_answer', 'company_created', 'card_shared', "
    "'company_response', 'company_confirmed', 'repeat_clicked', 'reminder_sent', "
    "'company_unsubscribed', 'bot_blocked', 'company_attended', 'outbound_429', "
    "'me_open', 'me_name_set', 'me_home_arena_set'"
)
_NEW_ONLY = "'watch_offer_shown', 'watch_offer_click', 'watch_offer_closed', 'watch_offer_subscribed'"
_TABLE = "catalog_consumer_events"
_CK = "ck_catalog_consumer_events_kind"
WARM_KINDS = ("warm_welcome", "warm_today", "warm_week", "warm_nudge")


def upgrade() -> None:
    kinds = ", ".join(f"'{k}'" for k in WARM_KINDS)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS warm_notices (
            telegram_id BIGINT NOT NULL,
            kind VARCHAR(16) NOT NULL,
            ref VARCHAR(32) NOT NULL,
            arena_id INTEGER NULL,
            sent_at TIMESTAMPTZ NULL,
            failed BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (telegram_id, kind, ref),
            CONSTRAINT ck_warm_notices_kind CHECK (kind IN ({kinds}))
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_warm_notices_person_sent ON warm_notices (telegram_id, sent_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_warm_notices_sent ON warm_notices (sent_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS warm_prefs (
            telegram_id BIGINT PRIMARY KEY,
            opted_out_at TIMESTAMPTZ NULL,
            bot_blocked_at TIMESTAMPTZ NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
    # Общий бюджет считает и напоминания колокольчика: по подписке быстро найти доставки.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_ice_watch_deliveries_watch_at "
        "ON client_ice_watch_deliveries (watch_id, attempted_at)"
    )
    op.drop_constraint(_CK, _TABLE, type_="check")
    op.execute(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CK} CHECK (kind IN ({_OLD_KINDS}, {_NEW_ONLY})) NOT VALID")
    op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {_CK}")


def downgrade() -> None:
    # Данные не трогаем (см. докстринг): таблицы и строки новых событий остаются, CHECK — мягкий.
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CK} CHECK (kind IN ({_OLD_KINDS})) NOT VALID")
