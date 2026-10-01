"""Каталог как самостоятельная площадка: магазины и шеринг конкретного места (TASK-146).

``arenas.venue_type`` += ``shop``
    Ледовый магазин (розница, заточка, прокат, ремонт) — та же строка в ``arenas``,
    что и каток: город, адрес, координаты, фото, модерация уже есть. Новая таблица
    ради «карточки с тегами» дублировала бы всё это. Услуги магазина живут в
    ``arena_profiles.amenities`` (ключи — ``src/application/arena_profile.py``),
    колонка JSONB и миграции не требует.

``client_share_events.kind`` += ``place``
    «Поделиться» с карточки конкретного места (каток, зал, магазин). До этого
    шерили только тренера и «Лёд сегодня» по городу; ``arena_id`` в таблице уже есть.

Revision ID: 0208_shops_place_shares
Revises: 0207_collective_operators
"""

from alembic import op

revision = "0208_shops_place_shares"
down_revision = "0207_collective_operators"
branch_labels = None
depends_on = None

# Держать в синхроне с src/shared/venue_types.py (VENUE_TYPE_KEYS).
_VENUE_TYPES_NEW = "('ice', 'gym', 'choreo', 'pool', 'outdoor', 'other', 'shop')"
_VENUE_TYPES_OLD = "('ice', 'gym', 'choreo', 'pool', 'outdoor', 'other')"

# Держать в синхроне с src/infrastructure/db/models.py (CLIENT_SHARE_KINDS).
_SHARE_KINDS_NEW = "('ice_city_day', 'trainer', 'place')"
_SHARE_KINDS_OLD = "('ice_city_day', 'trainer')"


def upgrade() -> None:
    op.drop_constraint("ck_arenas_venue_type", "arenas", type_="check")
    op.create_check_constraint("ck_arenas_venue_type", "arenas", f"venue_type IN {_VENUE_TYPES_NEW}")
    op.drop_constraint("ck_client_share_events_kind", "client_share_events", type_="check")
    op.create_check_constraint("ck_client_share_events_kind", "client_share_events", f"kind IN {_SHARE_KINDS_NEW}")


def downgrade() -> None:
    # Магазины не превращаем в катки молча: откат упадёт на CHECK, пока они есть.
    # Это честнее, чем тихо переписать тип и показать магазин в ленте «где покататься».
    op.drop_constraint("ck_client_share_events_kind", "client_share_events", type_="check")
    op.execute("DELETE FROM client_share_events WHERE kind = 'place'")
    op.create_check_constraint("ck_client_share_events_kind", "client_share_events", f"kind IN {_SHARE_KINDS_OLD}")
    op.drop_constraint("ck_arenas_venue_type", "arenas", type_="check")
    op.create_check_constraint("ck_arenas_venue_type", "arenas", f"venue_type IN {_VENUE_TYPES_OLD}")
