"""Движок статуса зимней точки: все переходы (TASK-343)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.shared import winter_status as ws

NOW = datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc)


def mk(value, source="telegram", actor="a", ago_h=0.0, kind="ice"):
    return ws.MarkIn(kind, value, ws.weight_for(source), actor, NOW - timedelta(hours=ago_h))


def state(marks, prev=None):
    return ws.compute_state(marks, NOW, prev)


def test_no_marks_defaults_to_waiting():
    assert state([]).state == ws.STATE_WAITING


def test_single_telegram_mark_not_enough():
    c = state([mk("flooded")])
    assert c.state == ws.STATE_WAITING and c.score == 1.0


def test_two_telegram_marks_flood():
    assert state([mk("flooded", actor="a"), mk("flooded", actor="b")]).state == ws.STATE_FLOODED


def test_four_site_marks_flood_but_three_do_not():
    three = [mk("flooded", "site", f"d{i}") for i in range(3)]
    four = [mk("flooded", "site", f"d{i}") for i in range(4)]
    assert state(three).state == ws.STATE_WAITING and state(three).score == 1.5
    assert state(four).state == ws.STATE_FLOODED and state(four).score == 2.0


def test_photo_alone_floods():
    assert state([mk("flooded", "photo")]).state == ws.STATE_FLOODED


def test_same_actor_counts_once():
    marks = [mk("flooded", "site", "d1", ago_h=h) for h in (0, 4, 8, 12, 16, 20)]
    c = state(marks)
    assert c.score == 0.5 and c.state == ws.STATE_WAITING


def test_photo_plus_telegram_same_person_is_not_three():
    c = state([mk("flooded", "photo", "tg:1", 1), mk("flooded", "telegram", "tg:1", 0)])
    assert c.score == 2.0  # максимум из весов того же значения, а не сумма


def test_boundary_72h_inclusive_and_beyond():
    inside = [mk("flooded", actor="a", ago_h=72), mk("flooded", actor="b", ago_h=72)]
    outside = [mk("flooded", actor="a", ago_h=72.01), mk("flooded", actor="b", ago_h=72.01)]
    assert state(inside).state == ws.STATE_FLOODED
    assert state(outside).state == ws.STATE_WAITING


def test_bad_ice_counts_as_present_with_quality():
    c = state([mk("bad", actor="a"), mk("bad", actor="b")])
    assert c.state == ws.STATE_FLOODED and c.quality == "bad"


def test_mixed_quality_majority_by_weight():
    c = state([mk("flooded", "photo", "a"), mk("bad", actor="b")])
    assert c.quality == "ok"


def test_flooded_without_marks_becomes_stale():
    assert state([], prev=ws.STATE_FLOODED).state == ws.STATE_STALE


def test_flooded_with_old_marks_only_becomes_stale():
    marks = [mk("flooded", actor="a", ago_h=80), mk("flooded", actor="b", ago_h=80)]
    assert state(marks, prev=ws.STATE_FLOODED).state == ws.STATE_STALE


def test_flooded_loses_confirmation_when_score_drops():
    marks = [mk("flooded", actor="a", ago_h=1)]  # 1 балл < 2
    assert state(marks, prev=ws.STATE_FLOODED).state == ws.STATE_STALE


def test_stale_returns_to_flooded_on_fresh_confirmation():
    marks = [mk("flooded", actor="a"), mk("flooded", actor="b")]
    assert state(marks, prev=ws.STATE_STALE).state == ws.STATE_FLOODED


def test_stale_stays_stale_without_enough_marks():
    assert state([mk("flooded")], prev=ws.STATE_STALE).state == ws.STATE_STALE


def test_waiting_without_marks_never_becomes_stale():
    assert state([], prev=ws.STATE_WAITING).state == ws.STATE_WAITING


def test_two_not_flooded_in_a_day_waiting_from_flooded():
    marks = [mk("not_flooded", actor="a", ago_h=2), mk("not_flooded", actor="b", ago_h=1)]
    assert state(marks, prev=ws.STATE_FLOODED).state == ws.STATE_WAITING


def test_one_not_flooded_does_not_change_flooded():
    marks = [mk("flooded", actor="a"), mk("flooded", actor="b"), mk("not_flooded", actor="c")]
    assert state(marks, prev=ws.STATE_FLOODED).state == ws.STATE_FLOODED


def test_not_flooded_same_actor_twice_is_one():
    marks = [mk("not_flooded", "site", "d1", 5), mk("not_flooded", "site", "d1", 1)]
    assert state(marks).not_flooded_actors == 1


def test_not_flooded_older_than_a_day_ignored():
    marks = [mk("not_flooded", actor="a", ago_h=25), mk("not_flooded", actor="b", ago_h=26)]
    assert state(marks, prev=ws.STATE_FLOODED).state == ws.STATE_STALE


def test_actor_changing_mind_uses_latest():
    marks = [mk("not_flooded", actor="a", ago_h=3), mk("flooded", actor="a", ago_h=1)]
    c = state(marks)
    assert c.not_flooded_actors == 0 and c.score == 1.0


def test_dispute_newer_not_flooded_wins():
    marks = [
        mk("flooded", actor="a", ago_h=10), mk("flooded", actor="b", ago_h=10),
        mk("not_flooded", actor="c", ago_h=2), mk("not_flooded", actor="d", ago_h=1),
    ]
    c = state(marks, prev=ws.STATE_FLOODED)
    assert c.state == ws.STATE_WAITING and c.dispute


def test_dispute_newer_flooded_wins():
    marks = [
        mk("not_flooded", actor="c", ago_h=10), mk("not_flooded", actor="d", ago_h=9),
        mk("flooded", actor="a", ago_h=2), mk("flooded", actor="b", ago_h=1),
    ]
    c = state(marks, prev=ws.STATE_WAITING)
    assert c.state == ws.STATE_FLOODED and c.dispute


def test_manual_states_are_not_overridden():
    marks = [mk("flooded", actor="a"), mk("flooded", actor="b")]
    assert state(marks, prev=ws.STATE_CLOSED).state == ws.STATE_CLOSED
    assert state(marks, prev=ws.STATE_HIDDEN).state == ws.STATE_HIDDEN
    assert not state(marks + [mk("not_flooded", actor="c"), mk("not_flooded", actor="d")], prev=ws.STATE_CLOSED).dispute


def test_future_marks_ignored():
    future = ws.MarkIn("ice", "flooded", 2.0, "a", NOW + timedelta(hours=2))
    assert state([future]).state == ws.STATE_WAITING


def test_crowd_lives_two_hours():
    assert state([mk("many", kind="crowd", ago_h=1.9)]).crowd == "many"
    assert state([mk("many", kind="crowd", ago_h=2.1)]).crowd is None


def test_crowd_majority_by_weight_then_newest():
    marks = [
        mk("few", "site", "a", 0.5, "crowd"), mk("few", "site", "b", 0.2, "crowd"),
        mk("many", "telegram", "c", 0.1, "crowd"),
    ]
    assert state(marks).crowd == "many"  # 1.0 против 1.0, побеждает свежая
    marks.append(mk("few", "telegram", "d", 1.5, "crowd"))
    assert state(marks).crowd == "few"


def test_hockey_independent_of_ice():
    c = state([mk("playing", kind="hockey", ago_h=0.5)])
    assert c.hockey == "playing" and c.state == ws.STATE_WAITING


def test_live_marks_do_not_affect_ice():
    marks = [mk("many", "photo", "a", kind="crowd"), mk("many", "photo", "b", kind="crowd")]
    assert state(marks).score == 0.0


def test_site_rate_limit_three_hours():
    assert ws.site_mark_allowed(None, NOW)
    assert not ws.site_mark_allowed(NOW - timedelta(hours=2, minutes=59), NOW)
    assert ws.site_mark_allowed(NOW - timedelta(hours=3), NOW)


def test_valid_values_and_weights():
    assert ws.is_valid_mark("ice", "bad") and not ws.is_valid_mark("ice", "many")
    assert not ws.is_valid_mark("nope", "x")
    assert ws.weight_for("site") == 0.5 and ws.weight_for("photo") == 2.0 and ws.weight_for("?") == 0.0


def test_gone_threshold():
    assert not ws.should_auto_hide(2) and ws.should_auto_hide(3)
