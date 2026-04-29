"""Unit tests: VK Mini Apps launch-params signature (MAX / VK WebView)."""
from __future__ import annotations

import pytest

from src.api.miniapp_auth.types import MiniAppPlatform
from src.api.miniapp_auth.vk_launch_params import verify_vk_miniapp_launch_principal
from src.shared.telegram_webapp import InitDataAuthError


def test_vk_official_example_validates() -> None:
    raw = (
        "vk_user_id=494075&vk_app_id=6736218&vk_is_app_user=1&vk_are_notifications_enabled=1"
        "&vk_language=ru&vk_access_token_settings=&vk_platform=android"
        "&sign=htQFduJpLxz7ribXRZpDFUH-XEUhC9rBPTJkjUFEkRA"
    )
    secret = "wvl68m4dR1UpLrVRli"
    p = verify_vk_miniapp_launch_principal(raw, secret)
    assert p.platform == MiniAppPlatform.MAX
    assert p.user_id == 494075


def test_vk_leading_question_mark_tolerated() -> None:
    raw = (
        "?vk_user_id=494075&vk_app_id=6736218&vk_is_app_user=1&vk_are_notifications_enabled=1"
        "&vk_language=ru&vk_access_token_settings=&vk_platform=android"
        "&sign=htQFduJpLxz7ribXRZpDFUH-XEUhC9rBPTJkjUFEkRA"
    )
    secret = "wvl68m4dR1UpLrVRli"
    p = verify_vk_miniapp_launch_principal(raw, secret)
    assert p.user_id == 494075


def test_vk_wrong_secret_fails() -> None:
    raw = "vk_user_id=1&vk_app_id=1&sign=nope"
    with pytest.raises(InitDataAuthError):
        verify_vk_miniapp_launch_principal(raw, "wrong-secret")
