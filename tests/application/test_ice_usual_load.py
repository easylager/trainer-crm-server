"""TASK-452: чистая blend-логика «обычно» — prior, вытеснение, корзины, сетка."""

from __future__ import annotations

from datetime import date, time

from src.application import ice_usual_load as iul
from src.application.session_load import (
    LEVEL_BUSY,
    LEVEL_CALM,
    LEVEL_MEDIUM,
    LoadRule,
    SessionLoadContext,
)


def _rule(day_group: str, starts_from: time, starts_before: time | None, level: str, **kw) -> LoadRule:
    return LoadRule(
        id=kw.get("id", 1),
        scope=kw.get("scope", "all"),
        character=kw.get("character"),
        arena_id=kw.get("arena_id"),
        day_group=day_group,
        starts_from=starts_from,
        starts_before=starts_before,
        level=level,
        source=kw.get("source", "admin"),
    )


def _ctx(
    cells: dict | None = None,
    rules: tuple[LoadRule, ...] = (),
    character: dict | None = None,
) -> iul.UsualLoadContext:
    cells = cells or {}
    dts: dict = {}
    totals: dict = {}
    for (arena, wd, b), (s, n) in cells.items():
        dk = (arena, b, iul.daytype_of(wd))
        ps, pn = dts.get(dk, (0, 0))
        dts[dk] = (ps + s, pn + n)
        totals[arena] = totals.get(arena, 0) + n
    return iul.UsualLoadContext(
        cells=cells, dts=dts, totals=totals,
        load=SessionLoadContext(rules=rules, character_by_arena=character or {}),
    )


class TestBuckets:
    def test_boundaries(self):
        assert iul.bucket_for_hour(6) == 0
        assert iul.bucket_for_hour(10) == 0
        assert iul.bucket_for_hour(11) == 0
        assert iul.bucket_for_hour(12) == 1
        assert iul.bucket_for_hour(16) == 1
        assert iul.bucket_for_hour(17) == 2
        assert iul.bucket_for_hour(19) == 2
        assert iul.bucket_for_hour(20) == 3
        assert iul.bucket_for_hour(23) == 3
        assert iul.bucket_for_hour(0) == 3
        assert iul.bucket_for_hour(5) == 3

    def test_labels(self):
        assert iul.BUCKET_LABEL_HOURS == (10, 14, 18, 20)


class TestBlendValue:
    def test_no_data_no_prior_is_none(self):
        assert iul.blend_value(None, 0, 0, 0, 0) is None

    def test_zero_checkins_returns_prior(self):
        assert iul.blend_value(3, 0, 0, 0, 0) == 3
        assert iul.blend_value(1, 0, 0, 0, 0) == 1

    def test_checkins_push_prior_out(self):
        # prior «свободно» (1) весом 4 отметки + 6 «людно» (3): среднее > 2.33 → людно.
        v = iul.blend_value(1, 18, 6, 18, 6)
        assert v is not None and v > 2.33
        assert iul.round_level(v) == 3

    def test_few_checkins_prior_holds(self):
        # 1 «людно» против prior «свободно»×4: (4+3)/(4+1+0.5) ≈ 1.27 → свободно.
        v = iul.blend_value(1, 3, 1, 3, 1)
        assert v is not None and iul.round_level(v) == 1

    def test_daytype_pulls_empty_cell(self):
        # Ячейки нет, prior нет — но 8 «людно» в этой корзине по будням.
        v = iul.blend_value(None, 0, 0, 24, 8)
        assert v is not None and iul.round_level(v) == 3

    def test_rounding(self):
        assert iul.round_level(1.0) == 1
        assert iul.round_level(1.66) == 1
        assert iul.round_level(1.67) == 2
        assert iul.round_level(2.32) == 2
        assert iul.round_level(2.33) == 3
        assert iul.round_level(3.0) == 3


class TestUsualLevel:
    def test_prior_when_no_checkins(self):
        rules = (_rule("mon_thu", time(0, 0), None, LEVEL_BUSY),)
        ctx = _ctx(rules=rules)
        # Понедельник 18:00 → корзина «18», правило busy → 3.
        assert iul.usual_level(ctx, arena_id=7, weekday=0, starts_at_local="18:00") == 3

    def test_none_when_nothing(self):
        ctx = _ctx()
        assert iul.usual_level(ctx, arena_id=7, weekday=0, starts_at_local="18:00") is None

    def test_checkins_blend_with_prior(self):
        rules = (_rule("sat", time(0, 0), None, LEVEL_CALM),)
        # суббота (wd=5), корзина «18» (b=2): 5 «людно» ещё не ломают prior (≈2.30→2),
        # 6 «людно» вытесняют «свободно» (≈2.38→3).
        ctx5 = _ctx(cells={(7, 5, 2): (15, 5)}, rules=rules)
        assert iul.usual_level(ctx5, arena_id=7, weekday=5, starts_at_local="18:30") == 2
        ctx6 = _ctx(cells={(7, 5, 2): (18, 6)}, rules=rules)
        assert iul.usual_level(ctx6, arena_id=7, weekday=5, starts_at_local="18:30") == 3

    def test_neighbor_daytype_helps_sparse_cell(self):
        # Отметок в ячейке нет; в другие будни этой корзины — «людно»; правила нет.
        ctx = _ctx(cells={(7, 1, 2): (9, 3), (7, 2, 2): (9, 3)})
        assert iul.usual_level(ctx, arena_id=7, weekday=0, starts_at_local="18:00") == 3

    def test_character_shifts_prior(self):
        # Правило «все» busy, но каток quiet → prior medium, не busy.
        rules = (_rule("mon_thu", time(0, 0), None, LEVEL_BUSY),)
        ctx = _ctx(rules=rules, character={7: "quiet"})
        assert iul.usual_level(ctx, arena_id=7, weekday=0, starts_at_local="18:00") == 2

    def test_kind_gate(self):
        rules = (_rule("mon_thu", time(0, 0), None, LEVEL_BUSY),)
        ctx = _ctx(rules=rules)
        mon = date(2026, 11, 23)  # понедельник
        assert iul.usual_for_session(
            ctx, arena_id=7, kind="public_skate", local_date=mon, starts_at_local="18:00"
        ) == {"key": "busy", "word": "людно"}
        # family_skate в TYPICAL_LOAD_SESSION_KINDS не входит — как у typical_load_fields.
        assert iul.usual_for_session(
            ctx, arena_id=7, kind="family_skate", local_date=mon, starts_at_local="18:00"
        ) is None
        assert iul.usual_for_session(
            ctx, arena_id=7, kind="rental", local_date=mon, starts_at_local="18:00"
        ) is None


class TestArenaGrid:
    def test_grid_hidden_without_anything(self):
        assert iul.arena_usual_grid(_ctx(), 7) is None

    def test_grid_from_rules_only(self):
        rules = (
            _rule("mon_thu", time(0, 0), None, LEVEL_CALM),
            _rule("fri", time(0, 0), None, LEVEL_MEDIUM),
            _rule("sat", time(11, 0), time(20, 0), LEVEL_BUSY),
            _rule("sun", time(0, 0), None, LEVEL_MEDIUM),
        )
        g = iul.arena_usual_grid(_ctx(rules=rules), 7)
        assert g is not None and g["total"] == 0
        assert g["buckets"] == [10, 14, 18, 20]
        # пн–чт спокойны во всех корзинах, сб днём/вечером людно.
        assert all(g["cells"][b][wd] == 1 for b in range(4) for wd in range(4))
        assert g["cells"][1][5] == 3 and g["cells"][2][5] == 3
        assert g["best"] == "Свободнее всего — будни в 10:00, 14:00 и 18:00"

    def test_low_data_cells_none(self):
        # Правило только на субботу, отметок нет → будни/вс «мало данных».
        g = iul.arena_usual_grid(_ctx(rules=(_rule("sat", time(0, 0), None, LEVEL_BUSY),)), 7)
        assert g is not None
        assert g["cells"][0][0] is None  # пн 10:00 — ни отметок, ни правила
        assert g["cells"][1][5] == 3
        # Единственные известные ячейки людные — «свободнее» предлагать нечего.
        assert g["best"] is None

    def test_total_and_best_from_checkins(self):
        # Свободно в будни утром (b=0), людно вечером.
        cells = {}
        for wd in range(5):
            cells[(9, wd, 0)] = (1 * 5, 5)  # 5 отметок «свободно»
            cells[(9, wd, 2)] = (3 * 5, 5)
        g = iul.arena_usual_grid(_ctx(cells=cells), 9)
        assert g is not None and g["total"] == 50
        assert g["cells"][0][0] == 1 and g["cells"][2][0] == 3
        assert g["best"] == "Свободнее всего — будни в 10:00"
        # Выходные без данных и правил — «мало данных».
        assert g["cells"][0][5] is None

    def test_best_single_day(self):
        # Одна отметка в среду тянет все будни той же корзины (полувес типа дня).
        g = iul.arena_usual_grid(_ctx(cells={(9, 2, 3): (2, 2)}), 9)
        assert g is not None
        assert g["best"] == "Свободнее всего — будни в 20:00"

    def test_best_weekend(self):
        cells = {(9, 5, 2): (3, 3), (9, 6, 2): (3, 3)}
        g = iul.arena_usual_grid(_ctx(cells=cells), 9)
        assert g is not None
        assert g["best"] == "Свободнее всего — выходные в 18:00"
