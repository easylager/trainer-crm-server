"""TASK-237 AC-2: воронка и K на собранных вручную событиях."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.application.zovi_funnel import (
    FunnelEvent,
    compute_funnel,
    format_funnel_report,
    threshold_verdict,
)

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def ev(step: int, what: str, code: str, *, actor: str | None = None, device: str | None = None, **payload):
    body = {"code": code, **payload}
    if device:
        body["device"] = device
    return FunnelEvent(kind=f"invite_{what}", actor=actor, at=T0 + timedelta(minutes=step), payload=body)


def hand_built() -> list[FunnelEvent]:
    """Создатель X (actor ax, device dx) зовёт четверых; пятый заход — сам X.

    * R1 (ar1, dr1): открыл, «нет», «да», отправил, потом создал своё с тем же actor, другим device.
    * R2 (ar2, dr2): открыл, «да»; создал своё с тем же device, другим actor.
    * R3 (ar3, dr3): открыл; создал своё с другим actor и device, но parent_code = код, который он открыл.
    * R4 (ar4, dr4): только открыл.
    * X открывает свой же код — не получатель.
    """
    return [
        ev(0, "create", "c0000001", actor="ax", device="dx", kind="public_skate", audience="one", via="arena_card"),
        ev(1, "open", "c0000001", actor="ar1", device="dr1", src="sys", audience="one", kind="public_skate"),
        ev(2, "open", "c0000001", actor="ar2", device="dr2", src="copy", audience="one", kind="public_skate"),
        ev(4, "open", "c0000001", actor="ar3", device="dr3", src="copy", audience="one", kind="public_skate"),
        ev(3, "open", "c0000001", actor="ar4", device="dr4", audience="one", kind="public_skate"),
        ev(5, "open", "c0000001", actor="ax", device="dx2"),  # тот же actor, что у создателя
        ev(6, "open", "c0000001", actor="axx", device="dx"),  # то же устройство
        ev(7, "no_attempt", "c0000001", actor="ar1", device="dr1", act=2),
        ev(8, "no_attempt", "c0000001", actor="ar1", device="dr1", act=4),
        ev(9, "yes", "c0000001", actor="ar1", device="dr1"),
        ev(10, "yes", "c0000001", actor="ar2", device="dr2"),
        ev(11, "send_answer", "c0000001", actor="ar1", device="dr1"),
        # чужие маячки по тому же коду от создателя в счёт получателей не идут
        ev(12, "no_attempt", "c0000001", actor="ax", device="dx", act=1),
        ev(20, "create", "c1000001", actor="ar1", device="dr1b", kind="open_ice", audience="company", via="ice_list"),
        ev(21, "create", "c2000001", actor="ar2x", device="dr2", kind="public_skate", audience="one"),
        ev(22, "create", "c3000001", actor="ar3x", device="dr3x", parent_code="c0000001", audience="one"),
        # создал ДО открытия — не конверсия
        ev(-5, "create", "c9000001", actor="ar4", device="dr4", audience="one"),
    ]


def test_funnel_numbers_and_k_over_three_linking_paths() -> None:
    report = compute_funnel(hand_built())
    assert report.created == 5
    assert report.recipients == 4
    assert report.self_opens == 2
    assert report.opened_invites == 1
    assert (report.no_attempt, report.yes, report.send_answer) == (1, 2, 1)
    assert report.converted == 3
    assert report.k == 0.75
    assert report.signals_any == {"actor": 1, "device": 1, "parent": 1}
    assert report.signals_only == {"actor": 1, "device": 1, "parent": 1}
    assert report.signals_multi == 0
    assert report.max_act == {4: 1}


def test_creator_opening_own_invite_is_not_a_recipient() -> None:
    events = [
        ev(0, "create", "c0000001", actor="ax", device="dx"),
        ev(1, "open", "c0000001", actor="ax", device="dx"),
        ev(2, "create", "c0000002", actor="ax", device="dx"),
    ]
    report = compute_funnel(events)
    assert (report.recipients, report.converted, report.self_opens) == (0, 0, 1)
    assert report.k is None
    assert "нет данных" in report.verdict


def test_slices_by_src_via_kind_and_audience() -> None:
    report = compute_funnel(hand_built())
    by_src = {row.key: row for row in report.slices["src"]}
    assert (by_src["sys"].recipients, by_src["sys"].converted) == (1, 1)
    assert (by_src["copy"].recipients, by_src["copy"].converted) == (2, 2)
    assert (by_src["(нет)"].recipients, by_src["(нет)"].converted) == (1, 0)
    by_via = {row.key: row for row in report.slices["via"]}
    assert by_via["arena_card"].created == 1 and by_via["arena_card"].recipients == 4
    assert by_via["прямой /zovi"].created == 3 and by_via["прямой /zovi"].recipients == 0
    assert by_via["ice_list"].created == 1
    by_audience = {row.key: row for row in report.slices["audience"]}
    assert (by_audience["one"].created, by_audience["one"].recipients, by_audience["one"].converted) == (4, 4, 3)
    assert (by_audience["company"].created, by_audience["company"].recipients) == (1, 0)
    by_kind = {row.key: row for row in report.slices["kind"]}
    assert by_kind["public_skate"].recipients == 4 and by_kind["public_skate"].created == 2


def test_same_person_with_several_signals_is_one_converted() -> None:
    events = [
        ev(0, "create", "c0000001", actor="ax", device="dx"),
        ev(1, "open", "c0000001", actor="ar1", device="dr1"),
        ev(2, "create", "c0000002", actor="ar1", device="dr1", parent_code="c0000001"),
    ]
    report = compute_funnel(events)
    assert report.converted == 1
    assert report.signals_any == {"actor": 1, "device": 1, "parent": 1}
    assert report.signals_only == {"actor": 0, "device": 0, "parent": 0}
    assert report.signals_multi == 1


def test_without_actor_hash_device_still_links_and_warning_is_loud() -> None:
    events = [
        ev(0, "create", "c0000001", device="dx"),
        ev(1, "open", "c0000001", device="dr1"),
        ev(2, "create", "c0000002", device="dr1"),
    ]
    report = compute_funnel(events)
    assert (report.recipients, report.converted) == (1, 1)
    assert report.signals_any["actor"] == 0 and report.signals_any["device"] == 1
    assert report.actor_linking_warning and "недоступна" in report.actor_linking_warning
    lines = format_funnel_report(report, days=14, since=T0 - timedelta(days=14), until=T0 + timedelta(days=1))
    assert any("ПРЕДУПРЕЖДЕНИЕ" in line for line in lines)


def test_threshold_line_follows_readme() -> None:
    assert threshold_verdict(250, 0.12).startswith("продолжаем")
    assert threshold_verdict(150, 0.12).startswith("смотреть")
    assert threshold_verdict(500, 0.02).startswith("сворачиваем")
    assert threshold_verdict(500, 0.05).startswith("смотреть")
    assert threshold_verdict(0, None).startswith("нет данных")


def test_parent_code_credits_one_recipient_not_everyone_who_opened_the_parent() -> None:
    events = [
        ev(0, "create", "c0000001", actor="ax", device="dx"),
        ev(1, "open", "c0000001", actor="ar1", device="dr1"),
        ev(2, "open", "c0000001", actor="ar2", device="dr2"),
        ev(3, "open", "c0000001", actor="ar3", device="dr3"),
        ev(9, "create", "c0000002", actor="nobody", device="dn", parent_code="c0000001"),
    ]
    report = compute_funnel(events)
    assert report.recipients == 3
    assert report.converted == 1
    assert report.signals_any["parent"] == 1
