"""TASK-426 срез 1: недельный отчёт админу — сбор, пороги аномалий, текст по правилам текстов, раз в неделю."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from kk_notify_helpers import KATYA, LESHA, SASHA, at, make_factory, seed_notice, seed_pick, seed_player
from sqlalchemy import text

from src.application import kk_notify_report as report
from src.application.kk_notify_report import ReportData, Thresholds, detect_anomalies, render_report

TH = Thresholds()
MONDAY = at(10, 0, day=16)  # понедельник 16 ноября 2026
# окно отчёта — 9–15 ноября


def data(**kw) -> ReportData:
    base = dict(week_start=at(0, day=9), week_end=at(0, day=16))
    base.update(kw)
    return ReportData(**base)


# ---------- когда ----------


def test_report_due_only_from_monday_ten() -> None:
    assert not report.report_due(at(9, 59, day=16))
    assert report.report_due(at(10, 0, day=16))
    assert report.report_due(at(23, 0, day=18))  # догоняем в течение недели
    assert not report.report_due(at(9, 59, day=23))  # следующая неделя ещё не началась в 10:00


def test_week_window_is_previous_seven_minsk_days() -> None:
    start, end = report.week_window(at(11, day=18))
    assert (start, end) == (at(0, day=9), at(0, day=16))
    assert report.period_label(at(11, day=18)) == "2026-W47"
    assert report.period_label(at(11, day=1, month=12)) == "2026-W49"


# ---------- пороги аномалий (одно место: Thresholds) ----------


def test_no_anomalies_on_quiet_week() -> None:
    assert (
        detect_anomalies(
            data(sent={"result": 20}, failed={"result": 1}, phases_prev={"active": 10}, phases_now={"active": 9}), TH
        )
        == []
    )


def test_stall_needs_previous_week_volume() -> None:
    assert detect_anomalies(data(sent_prev_total=5, matches_in_week=3), TH)  # было 5, стало 0 — встала
    assert detect_anomalies(data(sent_prev_total=4, matches_in_week=3), TH) == []  # на малой базе не тревожим
    assert detect_anomalies(data(sent_prev_total=50, sent={"result": 1}, matches_in_week=3), TH) == []
    assert detect_anomalies(data(sent_prev_total=50, matches_in_week=0), TH) == []  # межсезонье: матчей не было


def test_failure_share_threshold_and_min_sample() -> None:
    over = data(sent={"result": 7}, failed={"result": 3})  # 3 из 10 = 30 % > 20 %
    assert any("Не дошло 3 из 10" in a for a in detect_anomalies(over, TH))
    exactly = data(sent={"result": 8}, failed={"result": 2})  # ровно 20 % — не выше порога
    assert detect_anomalies(exactly, TH) == []
    tiny = data(sent={"result": 1}, failed={"result": 2})  # 3 отправки — доли не судим
    assert detect_anomalies(tiny, TH) == []


def test_active_drop_threshold_and_min_base() -> None:
    assert any(
        "Активных было 12, стало 8" in a
        for a in detect_anomalies(data(phases_prev={"active": 12}, phases_now={"active": 8}), TH)
    )
    assert detect_anomalies(data(phases_prev={"active": 12}, phases_now={"active": 9}), TH) == []  # минус четверть
    assert detect_anomalies(data(phases_prev={"active": 5}, phases_now={"active": 0}), TH) == []  # база мала


def test_thresholds_are_configurable_without_release(monkeypatch) -> None:
    monkeypatch.setenv("KK_REPORT_FAIL_SHARE", "0.5")
    monkeypatch.setenv("KK_REPORT_FAIL_MIN_SAMPLE", "4")
    th = Thresholds.from_settings()
    assert (th.fail_share, th.fail_min_sample) == (0.5, 4)
    assert detect_anomalies(data(sent={"result": 7}, failed={"result": 3}), th) == []


# ---------- текст ----------

EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")


def sample_texts() -> list[str]:
    full = data(
        phases_now={"active": 12, "cooling": 4, "lost": 5, "new": 1, "off": 1},
        phases_prev={"active": 13},
        left=2,
        returned=1,
        sent={"result": 105, "nomove": 8},
        failed={"result": 3},
        sent_prev_total=100,
        blocked_players=1,
        invites={"nomove": (8, 5), "mfinal": (0, 0)},
    )
    bad = data(
        sent_prev_total=9,
        phases_prev={"active": 12},
        phases_now={"active": 4},
        sent={"result": 5},
        failed={"result": 9},
    )
    empty = data()
    return [render_report(full, TH), render_report(bad, TH), render_report(empty, TH)]


def test_text_obeys_text_rules() -> None:
    for body in sample_texts():
        assert "!" not in body
        assert not EMOJI.search(body)
        assert '"' not in body and " ," not in body and "  " not in body
        assert not re.search(r"\d{4}-\d{2}-\d{2}", body)
        assert "BYN" not in body and "р." not in body
        assert not re.search(r"\d %", body)  # перед знаком процента — неразрывный пробел
        assert not re.search(r"[A-Za-z]{3,}", re.sub(r"</?b>", "", body)), body  # без англицизмов и внутренних кодов
        for word in ("срез", "ретеншн", "фаза", "скучаем", "не упусти"):
            assert word not in body.lower()


def test_text_content_and_typography() -> None:
    full, bad, empty = sample_texts()
    assert full.startswith("<b>«КТО КОГО»: неделя 9–15 ноября</b>")
    assert "Игроков 23: активных 12, остывают 4, отвалились 5, без хода 1, выключили 1." in full
    assert "Отвалились за неделю: 2. Вернулись: 1." in full
    assert "Отправлено 113: итогов хода 105, «нет хода» 8." in full
    assert "Не дошло: 3 из 116 (3 %)." in full
    assert "— «нет хода»: 5 из 8 (63 %)" in full
    assert "— «тебя обошли»: не было сообщений" in full
    assert "Отклонений от порогов нет." in full and "Что не так" not in full
    assert "<b>Что не так</b>" in bad and bad.index("Что не так") < bad.index("Игроков")
    assert "Отправлено: ничего." in empty


def test_range_across_months() -> None:
    assert report._range(at(0, day=26, month=10), at(0, day=2, month=11)) == "26 октября – 1 ноября"


# ---------- сбор из базы ----------


@pytest.mark.asyncio
async def test_collect_phases_movement_and_sends(db_session) -> None:
    start, end = at(0, day=9), at(0, day=16)
    reg = at(10, day=1)
    # Саша: ходил 2 ноября (на 9-е остывал), 14-го вернулся — «вернулся»
    await seed_player(db_session, SASHA, registered=reg)
    await seed_pick(db_session, SASHA, at(10, day=2))
    await seed_pick(db_session, SASHA, at(10, day=14))
    # Катя: ходила 8 ноября (на 9-е активна), к 16-му ей 8 суток — остывает, ещё не отвалилась
    await seed_player(db_session, KATYA, registered=reg)
    await seed_pick(db_session, KATYA, at(10, day=8))
    # Лёша заблокировал бота 12-го: в обеих неделях «выключен», в движении не участвует
    await seed_player(db_session, LESHA, registered=reg, blocked_at=at(5, day=12))
    await seed_pick(db_session, LESHA, at(10, day=3))

    await seed_notice(db_session, SASHA, "result", at(14, day=11))
    await seed_notice(db_session, SASHA, "nomove", at(14, day=12))
    await seed_notice(db_session, KATYA, "result", at(14, day=10), failed=False)
    await seed_notice(db_session, KATYA, "result", None, failed=True, created_at=at(14, day=13))
    await seed_notice(db_session, KATYA, "result", at(14, day=3))  # прошлая неделя
    await seed_notice(db_session, KATYA, "result", at(14, day=17))  # после окна
    # приглашение с ходом за сутки: nomove Саше 12-го в 14:00, ход 12-го в 16:00
    await seed_pick(db_session, SASHA, at(16, day=12))

    got = await report.collect(db_session, now=MONDAY)
    assert (got.week_start, got.week_end) == (start, end)
    assert got.phases_now == {"active": 1, "cooling": 1, "off": 1}  # Саша; Катя 8 суток; Лёша заблокирован
    assert got.phases_prev == {"cooling": 1, "active": 1, "off": 1}  # Саша 9-го: с хода 2 ноября ровно 7 суток
    assert got.sent == {"result": 2, "nomove": 1}
    assert got.failed == {"result": 1}
    assert got.sent_prev_total == 1
    assert got.blocked_players == 1
    assert got.invites["nomove"] == (1, 1)
    assert got.returned == 1 and got.left == 0  # Саша остывал и вернулся


@pytest.mark.asyncio
async def test_collect_counts_left_and_returned(db_session) -> None:
    reg = at(10, day=1)
    await seed_player(db_session, SASHA, registered=reg)  # на 9-е: 7 суток с хода 2 ноября -> остывает; 14-го вернулся
    await seed_pick(db_session, SASHA, at(10, day=2))
    await seed_pick(db_session, SASHA, at(10, day=14))
    await seed_player(db_session, KATYA, registered=reg)  # на 9-е 7 суток — остывает; на 16-е 14 суток — отвалилась
    await seed_pick(db_session, KATYA, at(10, day=2))
    got = await report.collect(db_session, now=MONDAY)
    assert got.returned == 1 and got.left == 1


# ---------- раз в неделю ----------


class Admin:
    def __init__(self, answer=True) -> None:
        self.answer = answer
        self.messages: list[str] = []

    async def __call__(self, body: str):
        self.messages.append(body)
        return self.answer


@pytest.mark.asyncio
async def test_weekly_report_goes_out_once(db_session) -> None:
    factory = make_factory(db_session)
    admin = Admin()
    assert await report.send_weekly_report_if_due(factory, now=at(9, 59, day=16), send=admin) == "not_due"
    assert await report.send_weekly_report_if_due(factory, now=MONDAY, send=admin) == "sent"
    assert (
        await report.send_weekly_report_if_due(factory, now=MONDAY + timedelta(minutes=2), send=admin)
        == "claimed_elsewhere"
    )
    assert await report.send_weekly_report_if_due(factory, now=at(18, day=17), send=admin) == "claimed_elsewhere"
    assert len(admin.messages) == 1
    # следующая неделя — новый отчёт
    assert await report.send_weekly_report_if_due(factory, now=at(10, day=23), send=admin) == "sent"
    assert len(admin.messages) == 2


@pytest.mark.asyncio
async def test_weekly_report_failed_delivery_retries_with_limit(db_session) -> None:
    factory = make_factory(db_session)
    admin = Admin(answer=False)
    results = []
    now = MONDAY
    for _ in range(5):
        results.append(await report.send_weekly_report_if_due(factory, now=now, send=admin))
        now += timedelta(minutes=11)
    assert results == ["retry", "retry", "retry", "claimed_elsewhere", "claimed_elsewhere"]
    assert len(admin.messages) == 3


@pytest.mark.asyncio
async def test_weekly_report_not_resent_inside_claim_window(db_session) -> None:
    factory = make_factory(db_session)
    admin = Admin(answer=False)
    await report.send_weekly_report_if_due(factory, now=MONDAY, send=admin)
    assert (
        await report.send_weekly_report_if_due(factory, now=MONDAY + timedelta(minutes=3), send=admin)
        == "claimed_elsewhere"
    )


@pytest.mark.asyncio
async def test_weekly_report_unconfigured_admin_bot_is_done(db_session) -> None:
    """``None`` — бот админа не настроен, текст в логе: повторять каждые десять минут незачем."""
    factory = make_factory(db_session)
    admin = Admin(answer=None)
    assert await report.send_weekly_report_if_due(factory, now=MONDAY, send=admin) == "sent"
    assert (
        await report.send_weekly_report_if_due(factory, now=MONDAY + timedelta(hours=1), send=admin)
        == "claimed_elsewhere"
    )
    [row] = (await db_session.execute(text("SELECT done_at FROM kk_notify_runs"))).all()
    assert row.done_at is not None
