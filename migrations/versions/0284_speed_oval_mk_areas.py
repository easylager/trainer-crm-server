"""Конькобежный стадион (arena 115): площадка массового катания в ``hall`` и «Прокат и услуги».

1. Старые сеансы держали площадку в ``session_label`` («Массовое катание на хоккейной площадке»,
   «… на конькобежной дорожке»): переносим в ``hall`` («Хоккейная площадка» / «Конькобежная дорожка»),
   заголовок обнуляем — все три вида массового (дорожка, хоккейная площадка, дискотека) одной группой.
2. ``visit_info.services``: прокат коньков (цена — из сеансов), заточка, прокат детского тренажёра
   («Пингвин») 6,00 BYN за сеанс, прокат защитной экипировки и шлема 5,00 BYN за час (цены — владелец,
   2026-10-31). Пишем, только если у стадиона ещё нет своего списка услуг из админки.

Revision ID: 0284_speed_oval_mk_areas
Revises: 0283_ice_session_hall_tiers
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0284_speed_oval_mk_areas"
down_revision = "0283_ice_session_hall_tiers"
branch_labels = None
depends_on = None

ARENA_ID = 115

SERVICES = [
    {"kind": "rental", "label": "Прокат коньков", "price": "", "note": "цена в кассе"},
    {"kind": "sharpening", "label": "Заточка", "price": "", "note": "цена в кассе"},
    {"kind": "aid", "label": "Прокат детского тренажёра («Пингвин»)", "price": "6,00 BYN", "note": "за сеанс"},
    {"kind": "protection", "label": "Прокат защитной экипировки и шлема", "price": "5,00 BYN", "note": "за час"},
]

_AREA_SQL = """
UPDATE ice_sessions SET
    hall = CASE
        WHEN session_label ILIKE '%дискотек%' AND session_label ILIKE '%хоккейн%'
            THEN 'Хоккейная площадка · дискотека на льду'
        WHEN session_label ILIKE '%дискотек%' THEN 'Дискотека на льду'
        WHEN session_label ILIKE '%хоккейн%' THEN 'Хоккейная площадка'
        ELSE 'Конькобежная дорожка'
    END,
    session_label = NULL
WHERE arena_id = :a AND kind = 'public_skate' AND hall IS NULL
  AND session_label ILIKE 'массовое катание%'
  AND (session_label ILIKE '%хоккейн%' OR session_label ILIKE '%дорожк%'
       OR session_label ILIKE '%конькобежн%' OR session_label ILIKE '%дискотек%')
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(_AREA_SQL), {"a": ARENA_ID})
    bind.execute(
        sa.text(
            "UPDATE arena_profiles SET visit_info = COALESCE(visit_info, '{}'::jsonb) "
            "|| jsonb_build_object('services', CAST(:s AS jsonb)) "
            "WHERE arena_id = :a AND NOT (COALESCE(visit_info, '{}'::jsonb) ? 'services')"
        ),
        {"s": json.dumps(SERVICES, ensure_ascii=False), "a": ARENA_ID},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE arena_profiles SET visit_info = visit_info - 'services' "
            "WHERE arena_id = :a AND visit_info->'services' = CAST(:s AS jsonb)"
        ),
        {"s": json.dumps(SERVICES, ensure_ascii=False), "a": ARENA_ID},
    )
    # hall у сеансов не откатываем: следующий прогон парсера всё равно перепишет строки.
