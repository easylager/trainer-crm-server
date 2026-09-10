from __future__ import annotations

from fastapi import HTTPException

from src.api.miniapp_auth import deps
from src.shared.webapp_http_messages import (
    MINIAPP_ADMIN_NOT_CONFIGURED_DETAIL_RU,
    MINIAPP_ADMIN_PLATFORM_NOT_SUPPORTED_DETAIL_RU,
    MINIAPP_CLIENT_NOT_CONFIGURED_DETAIL_RU,
    MINIAPP_NOT_ADMIN_DETAIL_RU,
    MINIAPP_PLATFORM_NOT_SUPPORTED_DETAIL_RU,
    MINIAPP_TRAINER_NOT_CONFIGURED_DETAIL_RU,
    MINIAPP_VK_NOT_CONFIGURED_DETAIL_RU,
)


def test_unsupported_miniapp_platform_uses_safe_russian_detail() -> None:
    try:
        deps.reject_unsupported_miniapp_platform_normalized("unknown")
    except HTTPException as exc:
        assert exc.status_code == 501
        assert exc.detail == MINIAPP_PLATFORM_NOT_SUPPORTED_DETAIL_RU
        assert "Mini App" not in exc.detail
        assert "platform" not in exc.detail
    else:
        raise AssertionError("unsupported platform must raise HTTPException")


def test_unconfigured_miniapps_have_safe_russian_details() -> None:
    assert "VK" not in MINIAPP_VK_NOT_CONFIGURED_DETAIL_RU
    assert "Trainer" not in MINIAPP_TRAINER_NOT_CONFIGURED_DETAIL_RU
    assert "Client" not in MINIAPP_CLIENT_NOT_CONFIGURED_DETAIL_RU
    assert "Admin" not in MINIAPP_ADMIN_NOT_CONFIGURED_DETAIL_RU
    assert "Admin" not in MINIAPP_ADMIN_PLATFORM_NOT_SUPPORTED_DETAIL_RU
    assert "admin" not in MINIAPP_NOT_ADMIN_DETAIL_RU
    assert all(
        detail == detail.strip()
        for detail in (
            MINIAPP_VK_NOT_CONFIGURED_DETAIL_RU,
            MINIAPP_TRAINER_NOT_CONFIGURED_DETAIL_RU,
            MINIAPP_CLIENT_NOT_CONFIGURED_DETAIL_RU,
        )
    )
