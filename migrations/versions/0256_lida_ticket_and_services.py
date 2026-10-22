"""Lida ice palace: box-office rule and the prices that do not fit a session.

The public-skate slot keeps adult 9 / child 7 / adult rental 6. Child rental,
sharpening, and the 12-visit pass live on the place page. Tickets are sold
at the desk, including two days ahead; there is no online checkout.

Revision ID: 0256_lida_ticket_and_services
Revises: 0255_vitebsk_rental_and_site
"""

from __future__ import annotations

from alembic import op

revision = "0256_lida_ticket_and_services"
down_revision = "0255_vitebsk_rental_and_site"
branch_labels = None
depends_on = None

_TICKET = (
    "Билеты только в кассе дворца, ул. Качана, 31: в день катания с 12:30 до 21:00 "
    "и за два дня вперёд. Раньше не продают. Онлайн-кассы пока нет."
)
_NOTE = (
    "Сеанс массового катания длится 45 минут. "
    "В расписании билет без коньков: взрослый 9 BYN, детский 7 BYN."
)


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE arena_profiles
        SET opening_hours = COALESCE(opening_hours, '{{}}'::jsonb) || jsonb_build_object(
                'kassa', jsonb_build_object('open', '12:30', 'close', '21:00'),
                'ticket_note', '{_TICKET}',
                'rental_title', 'Услуги и цены',
                'rental_note', '{_NOTE}',
                'rental_catalog', jsonb_build_array(
                    jsonb_build_object('label', 'Прокат коньков, взрослый', 'price', '6 BYN'),
                    jsonb_build_object('label', 'Прокат коньков, детский до 16 лет', 'price', '5 BYN'),
                    jsonb_build_object('label', 'Заточка для катания', 'price', '12 BYN за пару'),
                    jsonb_build_object('label', 'Заточка с мелким ремонтом', 'price', '15 BYN за пару'),
                    jsonb_build_object('label', 'Заточка для учащихся школы', 'price', 'бесплатно'),
                    jsonb_build_object(
                        'label', 'Абонемент 12 посещений, взрослый, без коньков',
                        'price', '94,50 BYN'
                    ),
                    jsonb_build_object(
                        'label', 'Абонемент 12 посещений, детский до 16 лет, без коньков',
                        'price', '73,50 BYN'
                    )
                )
            )
        WHERE arena_id = 37
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE arena_profiles
        SET opening_hours = opening_hours
            - 'kassa' - 'ticket_note' - 'rental_title' - 'rental_note' - 'rental_catalog'
        WHERE arena_id = 37
        """
    )
