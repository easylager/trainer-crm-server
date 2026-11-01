"""Движок статуса сезонной точки (TASK-343): отметки людей -> состояние льда.

Чистые функции без БД. Правила (решение владельца 01.11):

* вес отметки: сайт без входа 0,5; Telegram / Mini App 1; фото со льдом 2;
* «залит» подтверждён при >= 2 баллах за 72 ч;
* 2 разных человека «не залит» за 24 ч -> «ждём заливку»;
* залит, а за 72 ч подтверждений меньше порога -> «давно не отмечали»;
* загрузка (людей) и хоккей живут 2 ч;
* один человек считается один раз: берём его последнюю отметку в окне.

``closed`` и ``hidden`` ставит человек (админ, автоскрытие); движок их не снимает.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# --- состояния посезонной записи -------------------------------------------------
STATE_WAITING = "waiting"  # ждём заливку (по умолчанию)
STATE_FLOODED = "flooded"
STATE_STALE = "stale"  # давно не отмечали
STATE_CLOSED = "closed"
STATE_HIDDEN = "hidden"
STATES = (STATE_WAITING, STATE_FLOODED, STATE_STALE, STATE_CLOSED, STATE_HIDDEN)
MANUAL_STATES = frozenset({STATE_CLOSED, STATE_HIDDEN})

# --- виды отметок ----------------------------------------------------------------
KIND_ICE, KIND_CROWD, KIND_HOCKEY = "ice", "crowd", "hockey"
KINDS = (KIND_ICE, KIND_CROWD, KIND_HOCKEY)
VALUES: dict[str, tuple[str, ...]] = {
    KIND_ICE: ("flooded", "bad", "not_flooded"),
    KIND_CROWD: ("few", "normal", "many"),
    KIND_HOCKEY: ("playing", "free"),
}
ICE_PRESENT = frozenset({"flooded", "bad"})

# --- источники и веса ------------------------------------------------------------
SOURCE_SITE, SOURCE_TELEGRAM, SOURCE_MINIAPP, SOURCE_PHOTO = "site", "telegram", "miniapp", "photo"
SOURCES = (SOURCE_SITE, SOURCE_TELEGRAM, SOURCE_MINIAPP, SOURCE_PHOTO)
WEIGHTS: dict[str, float] = {
    SOURCE_SITE: 0.5,
    SOURCE_TELEGRAM: 1.0,
    SOURCE_MINIAPP: 1.0,
    SOURCE_PHOTO: 2.0,
}

FLOODED_THRESHOLD = 2.0
FLOODED_WINDOW = timedelta(hours=72)
NOT_FLOODED_WINDOW = timedelta(hours=24)
NOT_FLOODED_ACTORS = 2
LIVE_WINDOW = timedelta(hours=2)  # людей / хоккей
SITE_REPEAT_LIMIT = timedelta(hours=3)  # 1 отметка с устройства на точку
_FUTURE_SKEW = timedelta(minutes=5)

GONE_SIGNALS = 3
GONE_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class MarkIn:
    kind: str
    value: str
    weight: float
    actor: str
    at: datetime


@dataclass(frozen=True)
class Computed:
    state: str
    quality: str | None  # "bad" — лёд есть, но плохой
    score: float  # баллы «лёд есть» за 72 ч
    not_flooded_actors: int
    dispute: bool  # оба порога сработали одновременно
    last_ice_at: datetime | None
    crowd: str | None
    hockey: str | None
    crowd_at: datetime | None = None
    hockey_at: datetime | None = None


def is_valid_mark(kind: str, value: str) -> bool:
    return value in VALUES.get(kind, ())


def weight_for(source: str) -> float:
    return WEIGHTS.get(source, 0.0)


def site_mark_allowed(last_same_actor_at: datetime | None, now: datetime) -> bool:
    """Лимит сайта: 1 отметка с устройства на точку в 3 ч."""
    return last_same_actor_at is None or now - last_same_actor_at >= SITE_REPEAT_LIMIT


def _latest_per_actor(marks: list[MarkIn], kind: str, since: datetime, now: datetime) -> list[MarkIn]:
    """Последняя отметка каждого человека в окне; вес = максимум среди его отметок с тем же значением."""
    best: dict[str, MarkIn] = {}
    weights: dict[tuple[str, str], float] = {}
    for m in marks:
        if m.kind != kind or m.at < since or m.at > now + _FUTURE_SKEW:
            continue
        key = (m.actor, m.value)
        weights[key] = max(weights.get(key, 0.0), m.weight)
        cur = best.get(m.actor)
        if cur is None or m.at >= cur.at:
            best[m.actor] = m
    return [
        MarkIn(m.kind, m.value, weights[(m.actor, m.value)], m.actor, m.at) for m in best.values()
    ]


def _live_value(marks: list[MarkIn], kind: str, now: datetime) -> tuple[str | None, datetime | None]:
    live = _latest_per_actor(marks, kind, now - LIVE_WINDOW, now)
    if not live:
        return None, None
    totals: dict[str, float] = {}
    newest: dict[str, datetime] = {}
    for m in live:
        totals[m.value] = totals.get(m.value, 0.0) + m.weight
        newest[m.value] = max(newest.get(m.value, m.at), m.at)
    top = max(totals, key=lambda v: (totals[v], newest[v]))
    return top, newest[top]


def compute_state(marks: list[MarkIn], now: datetime, prev_state: str | None) -> Computed:
    prev = prev_state or STATE_WAITING
    ice = _latest_per_actor(marks, KIND_ICE, now - FLOODED_WINDOW, now)
    present = [m for m in ice if m.value in ICE_PRESENT]
    score = round(sum(m.weight for m in present), 3)
    not_flooded = [
        m for m in ice if m.value == "not_flooded" and m.at >= now - NOT_FLOODED_WINDOW
    ]
    nf_actors = len({m.actor for m in not_flooded})
    nf_hit = nf_actors >= NOT_FLOODED_ACTORS
    fl_hit = score >= FLOODED_THRESHOLD
    newest_present = max((m.at for m in present), default=None)
    newest_nf = max((m.at for m in not_flooded), default=None)
    last_ice_at = max((m.at for m in ice), default=None)
    dispute = nf_hit and fl_hit

    crowd, crowd_at = _live_value(marks, KIND_CROWD, now)
    hockey, hockey_at = _live_value(marks, KIND_HOCKEY, now)

    if prev in MANUAL_STATES:
        state = prev
    elif nf_hit and fl_hit:
        state = STATE_WAITING if (newest_nf or now) > (newest_present or now) else STATE_FLOODED
    elif nf_hit:
        state = STATE_WAITING
    elif fl_hit:
        state = STATE_FLOODED
    elif prev in (STATE_FLOODED, STATE_STALE):
        state = STATE_STALE
    else:
        state = STATE_WAITING

    quality = None
    if state == STATE_FLOODED:
        bad = sum(m.weight for m in present if m.value == "bad")
        ok = sum(m.weight for m in present if m.value == "flooded")
        quality = "bad" if bad > ok else "ok"
    return Computed(
        state=state,
        quality=quality,
        score=score,
        not_flooded_actors=nf_actors,
        dispute=dispute and state not in MANUAL_STATES,
        last_ice_at=last_ice_at,
        crowd=crowd,
        hockey=hockey,
        crowd_at=crowd_at,
        hockey_at=hockey_at,
    )


def should_auto_hide(signal_actors_in_window: int) -> bool:
    """«Точки больше нет»: 3 сигнала разных людей за 7 дней."""
    return signal_actors_in_window >= GONE_SIGNALS
