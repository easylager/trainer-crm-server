"""
Pure-function tests for lifecycle_use_cases: stage→capability matrix and the derivation rules.

The capability matrix is a contract that the rest of the system depends on (UI, recovery
nudges, paywalls). These tests make every cell explicit so future regressions are loud.
"""
from __future__ import annotations

import pytest

from src.application.lifecycle_use_cases import (
    Capability,
    LifecycleStage,
    LifecycleSnapshot,
    _derive_stage,
    stage_allows,
    stage_capabilities,
)
from src.infrastructure.db.models import (
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_CONTRACT,
    TRAINER_STATUS_PENDING_PAYMENT,
    TRAINER_STATUS_PENDING_PROFILE,
)


# --- Capability matrix ---


_EXPECTED_MATRIX: dict[LifecycleStage, set[Capability]] = {
    LifecycleStage.ONBOARDING: set(),
    LifecycleStage.ACTIVE: {
        Capability.CATALOG_VISIBILITY,
        Capability.RECEIVE_LEADS,
        Capability.READ_OPERATIONS,
        Capability.CRM_BASE,
        Capability.ONLINE_BOOKING,
        Capability.ANALYTICS,
        Capability.GROUPS,
    },
    LifecycleStage.LEAD_MODE: {
        Capability.CATALOG_VISIBILITY,
        Capability.RECEIVE_LEADS,
        Capability.READ_OPERATIONS,
    },
    LifecycleStage.CHURNED: set(),
}


@pytest.mark.parametrize("stage", list(LifecycleStage))
@pytest.mark.parametrize("capability", list(Capability))
def test_stage_allows_matches_expected_matrix(
    stage: LifecycleStage, capability: Capability
) -> None:
    """Every (stage, capability) cell must agree with the documented contract."""
    expected = capability in _EXPECTED_MATRIX[stage]
    assert stage_allows(stage, capability) is expected, (
        f"{stage.value} × {capability.value} expected={expected}"
    )


def test_stage_capabilities_matches_matrix() -> None:
    for stage, expected in _EXPECTED_MATRIX.items():
        assert set(stage_capabilities(stage)) == expected


def test_lead_mode_does_not_allow_any_paid_module() -> None:
    """The whole point of Lead Mode: presence stays, control is paywalled."""
    paid = {Capability.CRM_BASE, Capability.ONLINE_BOOKING, Capability.ANALYTICS, Capability.GROUPS}
    for cap in paid:
        assert stage_allows(LifecycleStage.LEAD_MODE, cap) is False


def test_lead_mode_keeps_marketplace_presence() -> None:
    """Catalog visibility, leads, read-only ops — these must survive Lead Mode."""
    presence = {
        Capability.CATALOG_VISIBILITY,
        Capability.RECEIVE_LEADS,
        Capability.READ_OPERATIONS,
    }
    for cap in presence:
        assert stage_allows(LifecycleStage.LEAD_MODE, cap) is True


def test_churned_blocks_everything() -> None:
    for cap in Capability:
        assert stage_allows(LifecycleStage.CHURNED, cap) is False


def test_onboarding_blocks_everything() -> None:
    """Onboarding trainers shouldn't get operational rights until they finish setup."""
    for cap in Capability:
        assert stage_allows(LifecycleStage.ONBOARDING, cap) is False


# --- Stage derivation rules ---


class TestDeriveStage:
    """Pure mapping from (status, is_catalog_visible, has_active_sub) → LifecycleStage."""

    @pytest.mark.parametrize(
        "status",
        [
            TRAINER_STATUS_PENDING_PROFILE,
            TRAINER_STATUS_PENDING_CONTRACT,
            TRAINER_STATUS_PENDING_PAYMENT,
        ],
    )
    def test_pending_statuses_yield_onboarding(self, status: str) -> None:
        assert (
            _derive_stage(trainer_status=status, is_catalog_visible=True, has_active_sub=False)
            == LifecycleStage.ONBOARDING
        )

    def test_active_with_subscription_is_active(self) -> None:
        assert (
            _derive_stage(
                trainer_status=TRAINER_STATUS_ACTIVE,
                is_catalog_visible=True,
                has_active_sub=True,
            )
            == LifecycleStage.ACTIVE
        )

    def test_active_with_subscription_stays_active_when_hidden(self) -> None:
        # Hiding catalog ≠ giving up control — paid trainer remains ACTIVE.
        assert (
            _derive_stage(
                trainer_status=TRAINER_STATUS_ACTIVE,
                is_catalog_visible=False,
                has_active_sub=True,
            )
            == LifecycleStage.ACTIVE
        )

    def test_active_no_sub_visible_is_lead_mode(self) -> None:
        assert (
            _derive_stage(
                trainer_status=TRAINER_STATUS_ACTIVE,
                is_catalog_visible=True,
                has_active_sub=False,
            )
            == LifecycleStage.LEAD_MODE
        )

    def test_active_no_sub_hidden_is_churned(self) -> None:
        # No subscription AND no catalog visibility → no supply, no monetization → churned.
        assert (
            _derive_stage(
                trainer_status=TRAINER_STATUS_ACTIVE,
                is_catalog_visible=False,
                has_active_sub=False,
            )
            == LifecycleStage.CHURNED
        )

    def test_deactivated_is_churned(self) -> None:
        for has_sub in (True, False):
            for visible in (True, False):
                assert (
                    _derive_stage(
                        trainer_status=TRAINER_STATUS_DEACTIVATED,
                        is_catalog_visible=visible,
                        has_active_sub=has_sub,
                    )
                    == LifecycleStage.CHURNED
                )

    def test_missing_trainer_is_churned(self) -> None:
        # Defensive default — used when the trainer row was deleted mid-request.
        assert (
            _derive_stage(trainer_status=None, is_catalog_visible=False, has_active_sub=False)
            == LifecycleStage.CHURNED
        )

    def test_unknown_status_is_churned(self) -> None:
        assert (
            _derive_stage(
                trainer_status="future_unknown_status",
                is_catalog_visible=True,
                has_active_sub=True,
            )
            == LifecycleStage.CHURNED
        )


# --- LifecycleSnapshot dataclass ---


class TestLifecycleSnapshot:
    def _build(self, stage: LifecycleStage = LifecycleStage.LEAD_MODE) -> LifecycleSnapshot:
        return LifecycleSnapshot(
            trainer_id=1,
            stage=stage,
            trainer_status=TRAINER_STATUS_ACTIVE,
            has_active_subscription=False,
            is_catalog_visible=True,
            last_subscription_expires_at=None,
        )

    def test_is_lead_mode_flag(self) -> None:
        assert self._build(LifecycleStage.LEAD_MODE).is_lead_mode is True
        assert self._build(LifecycleStage.ACTIVE).is_lead_mode is False

    def test_is_active_flag(self) -> None:
        assert self._build(LifecycleStage.ACTIVE).is_active is True
        assert self._build(LifecycleStage.LEAD_MODE).is_active is False

    def test_as_dict_serialises_all_fields(self) -> None:
        snap = self._build()
        d = snap.as_dict()
        assert d["trainer_id"] == 1
        assert d["stage"] == LifecycleStage.LEAD_MODE.value
        assert d["is_lead_mode"] is True
        assert d["is_active"] is False
        assert d["has_active_subscription"] is False
        assert d["is_catalog_visible"] is True
        assert d["last_subscription_expires_at"] is None
