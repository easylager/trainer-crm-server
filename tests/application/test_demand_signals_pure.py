"""
Pure-function tests for demand signals: dedup hash policy + recap dataclass invariants.
No DB, no async — runs as plain pytest unit suite.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.application.demand_signals_use_cases import (
    RECAP_WINDOW_7D,
    RECAP_WINDOW_14D,
    RECAP_WINDOW_30D,
    SUPPORTED_RECAP_WINDOWS,
    SignalsRecap,
    compute_dedup_hash,
)


_FROZEN_T = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
_NEXT_DAY = datetime(2026, 4, 27, 0, 0, tzinfo=timezone.utc)


class TestComputeDedupHash:
    """Hash policy: same (ip, ua, trainer, day) → same hash; any change → different."""

    def test_returns_64_char_hex(self) -> None:
        h = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Mozilla", trainer_id=42, when=_FROZEN_T)
        assert h is not None
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_stable_within_same_day(self) -> None:
        a = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Mozilla", trainer_id=42, when=_FROZEN_T)
        b = compute_dedup_hash(
            client_ip="1.2.3.4",
            user_agent="Mozilla",
            trainer_id=42,
            when=_FROZEN_T.replace(hour=23, minute=59),
        )
        assert a == b

    def test_changes_across_days(self) -> None:
        a = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Mozilla", trainer_id=42, when=_FROZEN_T)
        b = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Mozilla", trainer_id=42, when=_NEXT_DAY)
        assert a != b

    def test_changes_per_trainer(self) -> None:
        a = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Mozilla", trainer_id=42, when=_FROZEN_T)
        b = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Mozilla", trainer_id=43, when=_FROZEN_T)
        assert a != b

    def test_changes_per_ip(self) -> None:
        a = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Mozilla", trainer_id=1, when=_FROZEN_T)
        b = compute_dedup_hash(client_ip="1.2.3.5", user_agent="Mozilla", trainer_id=1, when=_FROZEN_T)
        assert a != b

    def test_changes_per_user_agent(self) -> None:
        a = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Mozilla", trainer_id=1, when=_FROZEN_T)
        b = compute_dedup_hash(client_ip="1.2.3.4", user_agent="Chrome", trainer_id=1, when=_FROZEN_T)
        assert a != b

    def test_returns_none_when_both_identifiers_missing(self) -> None:
        # No fingerprint → cannot dedupe; over-count is safer than silently dropping signal.
        assert compute_dedup_hash(client_ip=None, user_agent=None, trainer_id=1, when=_FROZEN_T) is None
        assert compute_dedup_hash(client_ip="", user_agent="", trainer_id=1, when=_FROZEN_T) is None

    def test_returns_hash_when_only_one_identifier_present(self) -> None:
        only_ip = compute_dedup_hash(client_ip="1.2.3.4", user_agent=None, trainer_id=1, when=_FROZEN_T)
        only_ua = compute_dedup_hash(client_ip=None, user_agent="Mozilla", trainer_id=1, when=_FROZEN_T)
        assert only_ip is not None
        assert only_ua is not None
        assert only_ip != only_ua


class TestSignalsRecap:
    """Recap value object: derived flags and serialization."""

    def _build(
        self,
        *,
        views: int = 0,
        clicks: int = 0,
        blocked: int = 0,
        window: int = RECAP_WINDOW_14D,
    ) -> SignalsRecap:
        return SignalsRecap(
            trainer_id=1,
            window_days=window,
            since=_FROZEN_T,
            until=_FROZEN_T,
            profile_views=views,
            contact_clicks=clicks,
            booking_attempts_blocked=blocked,
        )

    def test_has_any_demand_false_on_empty(self) -> None:
        assert self._build().has_any_demand is False

    @pytest.mark.parametrize("field", ["views", "clicks", "blocked"])
    def test_has_any_demand_true_when_any_signal_present(self, field: str) -> None:
        recap = self._build(**{field: 1})
        assert recap.has_any_demand is True

    def test_as_dict_contains_all_fields(self) -> None:
        recap = self._build(views=5, clicks=2, blocked=1)
        d = recap.as_dict()
        assert d["trainer_id"] == 1
        assert d["profile_views"] == 5
        assert d["contact_clicks"] == 2
        assert d["booking_attempts_blocked"] == 1
        assert d["has_any_demand"] is True
        assert d["window_days"] == RECAP_WINDOW_14D
        # ISO format for both window edges:
        assert d["since"].endswith("+00:00")
        assert d["until"].endswith("+00:00")


class TestRecapWindows:
    """Sanity check on supported windows tuple — guards against accidental enum drift."""

    def test_supported_windows_contains_standard_set(self) -> None:
        assert RECAP_WINDOW_7D in SUPPORTED_RECAP_WINDOWS
        assert RECAP_WINDOW_14D in SUPPORTED_RECAP_WINDOWS
        assert RECAP_WINDOW_30D in SUPPORTED_RECAP_WINDOWS

    def test_supported_windows_are_sorted_ascending(self) -> None:
        assert list(SUPPORTED_RECAP_WINDOWS) == sorted(SUPPORTED_RECAP_WINDOWS)
