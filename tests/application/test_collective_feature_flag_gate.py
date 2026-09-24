"""Рубильник студийной надстройки обязан гасить её целиком.

`TRAINER_COLLECTIVE_ENABLED` выключен на проде, пока идут пилоты. Но гасил он
только `collective_payload` в bootstrap хаба, а чеклист онбординга отдавал
`capabilities` всегда. Шелл читает их запасным путём (`organizationCapabilities()`
в mini-app-trainer-shell.js), поэтому у владельца студии вкладка «Центр»
появлялась в тренерском боте даже при выключенной фиче: рубильник существовал,
но мимо одной из двух дорог.

Здесь проверяется именно это свойство, а не устройство самих возможностей.
"""
import pytest
from unittest.mock import patch

from src.application.trainer_onboarding_checklist import _capabilities_for_trainer

pytestmark = pytest.mark.collective

_CENTER_OWNER = type(
    "M",
    (),
    {
        "organization_format": "center_hybrid",
        "schedule_mode": "studio_central",
        "role": "owner",
    },
)()


async def _caps(*, enabled: bool, memberships: list) -> dict:
    with patch(
        "src.application.trainer_onboarding_checklist.list_active_collective_memberships",
        return_value=memberships,
    ), patch("src.shared.config.Settings") as settings:
        settings.return_value.trainer_collective_enabled = enabled
        return await _capabilities_for_trainer(None, 1, "full_trainer")


class TestCollectiveFeatureFlagGate:
    @pytest.mark.asyncio
    async def test_flag_off_hides_center_grid_even_for_a_studio_owner(self) -> None:
        """Главное свойство: выключенная фича не пускает «Центр» в тренерский бот."""
        caps = await _caps(enabled=False, memberships=[_CENTER_OWNER])
        assert caps["show_center_grid"] is False

    @pytest.mark.asyncio
    async def test_flag_off_keeps_the_personal_trainer_shell_intact(self) -> None:
        """Гасим надстройку, а не тренера: личный кабинет остаётся на месте."""
        caps = await _caps(enabled=False, memberships=[_CENTER_OWNER])
        assert caps["show_personal_crm"] is True

    @pytest.mark.asyncio
    async def test_flag_on_restores_center_grid_for_the_owner(self) -> None:
        """Фича не удалена — членство в БД цело и оживает при включении флага."""
        caps = await _caps(enabled=True, memberships=[_CENTER_OWNER])
        assert caps["show_center_grid"] is True

    @pytest.mark.asyncio
    async def test_solo_trainer_is_unaffected_either_way(self) -> None:
        """Тренер без коллектива не должен замечать ни флага, ни его починки."""
        off = await _caps(enabled=False, memberships=[])
        on = await _caps(enabled=True, memberships=[])
        assert off["show_center_grid"] is False
        assert on["show_center_grid"] is False
        assert off == on
