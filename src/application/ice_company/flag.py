"""Рубильник «Компания на лёд»: ICE_COMPANY_ENABLED.

Выкл — создать нельзя, кнопки нет. Уже созданные ссылки ``/k/{code}`` открываются.
"""

from __future__ import annotations

from src.shared.config import Settings


def feature_enabled(settings: Settings | None = None) -> bool:
    return bool((settings or Settings()).ice_company_enabled)
