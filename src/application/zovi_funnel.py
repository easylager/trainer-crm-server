"""Воронка открытки «Пойдёшь со мной на каток?» и K-фактор (TASK-237).

Чистая логика подсчёта над событиями ``invite_*`` из ``catalog_consumer_events`` — скрипт
``scripts/report_zovi_funnel.py`` только печатает. События пишет ``zovi_funnel_events``.

**Получатель** — уникальный человек, открывший чужое приглашение. Человек = токен устройства
(``payload.device``); у события без него — актёр (``actor_hash``). Открытие создателем своего
приглашения (то же устройство или тот же актёр, что у ``invite_create`` этого кода) не считается.

**Конвертировался** — получатель, у которого после первого открытия есть ``invite_create``, если:

* ``actor``  — тот же ``actor_hash``, что у одного из его открытий;
* ``device`` — то же устройство;
* ``parent``  — ``parent_code`` нового приглашения — код, который он открывал.

K = конвертировавшиеся / получатели. Отчёт разбирает, на каком признаке держится цифра:
признаков может быть несколько сразу, поэтому есть и «любой из», и «только этот».

**Порог** (README эпика): ≥ 200 приглашений и K ≥ 0.1 — продолжаем; K < 0.03 — сворачиваем;
между — смотреть, где обрывается воронка.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import (
    INVITE_FUNNEL_KINDS,
    KIND_INVITE_CREATE,
    KIND_INVITE_NO_ATTEMPT,
    KIND_INVITE_OPEN,
    KIND_INVITE_SEND_ANSWER,
    KIND_INVITE_YES,
    catalog_actor_exclusion_sql,
    catalog_event_day_minsk,
    minsk_day_start_utc,
)

THRESHOLD_MIN_INVITES = 200
THRESHOLD_K_CONTINUE = 0.1
THRESHOLD_K_FOLD = 0.03

SIGNALS = ("actor", "device", "parent")
NO_VALUE = "(нет)"
DIRECT_VIA = "прямой /zovi"


@dataclass(frozen=True)
class FunnelEvent:
    kind: str
    actor: str | None
    at: datetime
    payload: Mapping[str, Any]

    @property
    def code(self) -> str:
        return str(self.payload.get("code") or "")

    @property
    def device(self) -> str | None:
        return str(self.payload["device"]) if self.payload.get("device") else None


@dataclass
class _Person:
    pid: int
    first_open: FunnelEvent
    codes: set[str] = field(default_factory=set)
    devices: set[str] = field(default_factory=set)
    actors: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class SliceRow:
    key: str
    created: int | None
    recipients: int
    no_attempt: int
    yes: int
    send_answer: int
    converted: int

    @property
    def k(self) -> float | None:
        return self.converted / self.recipients if self.recipients else None


@dataclass(frozen=True)
class FunnelReport:
    created: int
    opened_invites: int
    self_opens: int
    recipients: int
    no_attempt: int
    yes: int
    send_answer: int
    converted: int
    signals_any: Mapping[str, int]
    signals_only: Mapping[str, int]
    signals_multi: int
    max_act: Mapping[int, int]
    slices: Mapping[str, Sequence[SliceRow]]
    events_total: int
    events_without_actor: int

    @property
    def k(self) -> float | None:
        return self.converted / self.recipients if self.recipients else None

    @property
    def verdict(self) -> str:
        return threshold_verdict(self.created, self.k)

    @property
    def actor_linking_warning(self) -> str | None:
        if self.events_total == 0 or self.events_without_actor == 0:
            return None
        if self.events_without_actor == self.events_total:
            return (
                "Склейка по актёру недоступна: ни у одного события нет actor_hash "
                "(CATALOG_ACTOR_HMAC_SECRET не задан или короче 32 символов). "
                "Уникальных получателей считаю по токену устройства; K — только по device и parent_code."
            )
        return (
            f"Склейка по актёру неполная: у {self.events_without_actor} из {self.events_total} событий "
            "нет actor_hash (секрет CATALOG_ACTOR_HMAC_SECRET задан не с самого начала?)."
        )


def threshold_verdict(created: int, k: float | None) -> str:
    """Строка порога из README эпика."""
    if k is None:
        return "нет данных: никто из получателей ещё не открыл чужое приглашение"
    if k < THRESHOLD_K_FOLD:
        return f"сворачиваем: K {k:.3f} < {THRESHOLD_K_FOLD}"
    if k >= THRESHOLD_K_CONTINUE and created >= THRESHOLD_MIN_INVITES:
        return f"продолжаем: {created} ≥ {THRESHOLD_MIN_INVITES} приглашений и K {k:.3f} ≥ {THRESHOLD_K_CONTINUE}"
    if k >= THRESHOLD_K_CONTINUE:
        return f"смотреть: K {k:.3f} ≥ {THRESHOLD_K_CONTINUE}, но приглашений {created} < {THRESHOLD_MIN_INVITES}"
    return f"смотреть: K {k:.3f} между {THRESHOLD_K_FOLD} и {THRESHOLD_K_CONTINUE} — где обрывается воронка"


def _is_self_open(event: FunnelEvent, creator: FunnelEvent | None) -> bool:
    if creator is None:
        return False
    if event.device and event.device == creator.device:
        return True
    return bool(event.actor and event.actor == creator.actor)


def compute_funnel(events: Iterable[FunnelEvent]) -> FunnelReport:
    ordered = sorted(events, key=lambda e: e.at)
    creates: dict[str, FunnelEvent] = {}
    for event in ordered:
        if event.kind == KIND_INVITE_CREATE and event.code and event.code not in creates:
            creates[event.code] = event

    persons: list[_Person] = []
    by_device: dict[str, _Person] = {}
    by_actor: dict[str, _Person] = {}
    opened_codes: set[str] = set()
    self_opens = 0
    for event in ordered:
        if event.kind != KIND_INVITE_OPEN or not event.code:
            continue
        if _is_self_open(event, creates.get(event.code)):
            self_opens += 1
            continue
        person = by_device.get(event.device) if event.device else None
        if person is None and not event.device and event.actor:
            person = by_actor.get(event.actor)
        if person is None:
            person = _Person(pid=len(persons), first_open=event)
            persons.append(person)
        person.codes.add(event.code)
        opened_codes.add(event.code)
        if event.device:
            person.devices.add(event.device)
            by_device.setdefault(event.device, person)
        if event.actor:
            person.actors.add(event.actor)
            by_actor.setdefault(event.actor, person)

    def owner(event: FunnelEvent) -> _Person | None:
        person = by_device.get(event.device) if event.device else None
        if person is None and not event.device and event.actor:
            person = by_actor.get(event.actor)
        return person if person is not None and event.code in person.codes else None

    reached: dict[str, set[int]] = {
        KIND_INVITE_NO_ATTEMPT: set(),
        KIND_INVITE_YES: set(),
        KIND_INVITE_SEND_ANSWER: set(),
    }
    act_of: dict[int, int] = {}
    for event in ordered:
        if event.kind not in reached:
            continue
        person = owner(event)
        if person is None:
            continue
        reached[event.kind].add(person.pid)
        if event.kind == KIND_INVITE_NO_ATTEMPT:
            act = event.payload.get("act")
            if isinstance(act, int) and not isinstance(act, bool):
                act_of[person.pid] = max(act_of.get(person.pid, 0), act)

    by_code: dict[str, list[_Person]] = defaultdict(list)
    actor_index: dict[str, list[_Person]] = defaultdict(list)
    device_index: dict[str, list[_Person]] = defaultdict(list)
    for person in persons:
        for code in person.codes:
            by_code[code].append(person)
        for actor in person.actors:
            actor_index[actor].append(person)
        for device in person.devices:
            device_index[device].append(person)

    found: dict[int, set[str]] = defaultdict(set)
    for event in ordered:
        if event.kind != KIND_INVITE_CREATE:
            continue
        matched: dict[int, set[str]] = defaultdict(set)
        people: dict[int, _Person] = {}
        for person in actor_index.get(event.actor, ()) if event.actor else ():
            matched[person.pid].add("actor")
            people[person.pid] = person
        for person in device_index.get(event.device, ()) if event.device else ():
            matched[person.pid].add("device")
            people[person.pid] = person
        parent = event.payload.get("parent_code")
        if parent:
            # Родителя открывали многие, а создал один: засчитываем одного получателя —
            # того, кого уже склеили actor/device, иначе открывшего позже всех до создания.
            candidates = [p for p in by_code.get(str(parent), ()) if p.first_open.at <= event.at]
            linked = [p for p in candidates if p.pid in matched]
            pick = linked or sorted(candidates, key=lambda p: (p.first_open.at, p.pid))[-1:]
            for person in pick:
                matched[person.pid].add("parent")
                people[person.pid] = person
        for pid, signals in matched.items():
            person = people[pid]
            if event.at >= person.first_open.at and event.code not in person.codes:
                found[pid] |= signals

    signals_any = {s: sum(1 for v in found.values() if s in v) for s in SIGNALS}
    signals_only = {s: sum(1 for v in found.values() if v == {s}) for s in SIGNALS}
    signals_multi = sum(1 for v in found.values() if len(v) > 1)
    max_act: dict[int, int] = defaultdict(int)
    for act in act_of.values():
        max_act[act] += 1

    def create_attr(person: _Person, name: str) -> str | None:
        creator = creates.get(person.first_open.code)
        value = creator.payload.get(name) if creator else None
        return str(value) if value else None

    def open_attr(person: _Person, name: str) -> str | None:
        value = person.first_open.payload.get(name)
        return str(value) if value else None

    def created_attr(name: str) -> dict[str, int]:
        return _count_by(creates.values(), lambda e: str(e.payload.get(name) or "") or None)

    slices = {
        "src": _slice(persons, lambda p: open_attr(p, "src"), None, reached, found),
        "via": _slice(
            persons, lambda p: create_attr(p, "via") or DIRECT_VIA, created_attr("via"), reached, found, DIRECT_VIA
        ),
        "kind": _slice(persons, lambda p: open_attr(p, "kind"), created_attr("kind"), reached, found),
        "audience": _slice(persons, lambda p: open_attr(p, "audience"), created_attr("audience"), reached, found),
    }
    funnel_events = [e for e in ordered if e.kind in INVITE_FUNNEL_KINDS]
    return FunnelReport(
        created=len(creates),
        opened_invites=len(opened_codes),
        self_opens=self_opens,
        recipients=len(persons),
        no_attempt=len(reached[KIND_INVITE_NO_ATTEMPT]),
        yes=len(reached[KIND_INVITE_YES]),
        send_answer=len(reached[KIND_INVITE_SEND_ANSWER]),
        converted=len(found),
        signals_any=signals_any,
        signals_only=signals_only,
        signals_multi=signals_multi,
        max_act=dict(sorted(max_act.items())),
        slices=slices,
        events_total=len(funnel_events),
        events_without_actor=sum(1 for e in funnel_events if not e.actor),
    )


def _count_by(items: Iterable[FunnelEvent], key: Callable[[FunnelEvent], str | None]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[key(item) or NO_VALUE] += 1
    return counts


def _slice(
    persons: Sequence[_Person],
    key: Callable[[_Person], str | None],
    created: Mapping[str, int] | None,
    reached: Mapping[str, set[int]],
    converted: Mapping[int, set[str]],
    created_alias: str | None = None,
) -> list[SliceRow]:
    groups: dict[str, list[_Person]] = defaultdict(list)
    for person in persons:
        groups[key(person) or NO_VALUE].append(person)
    keys = set(groups)
    if created is not None:
        keys |= {created_alias if k == NO_VALUE and created_alias else k for k in created}
    rows: list[SliceRow] = []
    for name in sorted(keys):
        members = groups.get(name, [])
        pids = {p.pid for p in members}
        created_count: int | None = None
        if created is not None:
            created_count = created.get(name, 0)
            if created_alias and name == created_alias:
                created_count += created.get(NO_VALUE, 0)
        rows.append(
            SliceRow(
                key=name,
                created=created_count,
                recipients=len(members),
                no_attempt=len(pids & reached[KIND_INVITE_NO_ATTEMPT]),
                yes=len(pids & reached[KIND_INVITE_YES]),
                send_answer=len(pids & reached[KIND_INVITE_SEND_ANSWER]),
                converted=len(pids & set(converted)),
            )
        )
    return rows


def report_window(days: int, until: date | None = None) -> tuple[datetime, datetime]:
    """``days`` суток по Минску, последние — ``until`` включительно (по умолчанию сегодня)."""
    last = until or catalog_event_day_minsk()
    return minsk_day_start_utc(last - timedelta(days=days - 1)), minsk_day_start_utc(last + timedelta(days=1))


async def load_funnel_events(session: AsyncSession, *, since: datetime, until: datetime) -> list[FunnelEvent]:
    """События окна без служебных аккаунтов (как везде в учёте каталога)."""
    exclusion, ex_params = catalog_actor_exclusion_sql("actor_hash")
    kinds = {f"k{i}": kind for i, kind in enumerate(INVITE_FUNNEL_KINDS)}
    placeholders = ", ".join(f":{name}" for name in kinds)
    rows = (
        (
            await session.execute(
                text(f"""
                    SELECT kind, actor_hash, occurred_at, payload
                    FROM catalog_consumer_events
                    WHERE kind IN ({placeholders})
                      AND occurred_at >= :since AND occurred_at < :until
                      {exclusion}
                    ORDER BY occurred_at, id
                    """),
                {**kinds, **ex_params, "since": since, "until": until},
            )
        )
        .mappings()
        .all()
    )
    return [
        FunnelEvent(
            kind=str(row["kind"]),
            actor=row["actor_hash"],
            at=row["occurred_at"].astimezone(timezone.utc),
            payload=row["payload"] or {},
        )
        for row in rows
    ]


async def build_funnel_report(session: AsyncSession, *, days: int = 14, until: date | None = None) -> FunnelReport:
    since, end = report_window(days, until)
    return compute_funnel(await load_funnel_events(session, since=since, until=end))


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "—"


def format_funnel_report(report: FunnelReport, *, days: int, since: datetime, until: datetime) -> list[str]:
    lines = [f"Воронка открытки «Пойдёшь со мной на каток?» — {days} дн., {since:%Y-%m-%d} … {until:%Y-%m-%d} (UTC)"]
    warning = report.actor_linking_warning
    if warning:
        lines += ["", f"!!! ПРЕДУПРЕЖДЕНИЕ: {warning}"]
    steps = [
        ("создано приглашений", report.created, None),
        ("открыто (получатели, чужие)", report.recipients, report.created),
        ("пытались «нет»", report.no_attempt, report.recipients),
        ("сказали «да»", report.yes, report.no_attempt),
        ("отправили ответ", report.send_answer, report.yes),
        ("создали своё", report.converted, report.send_answer),
    ]
    lines += ["", "Воронка (доля — от предыдущего звена):"]
    for name, count, prev in steps:
        share = "" if prev is None else f"  {_pct(count, prev)}"
        lines.append(f"  {name:<30}{count:>6}{share}")
    lines.append(
        f"  (приглашений открыто хоть кем-то: {report.opened_invites}; "
        f"открытий создателем не в счёт: {report.self_opens}; звенья «да» и «отправили» не вложены "
        "строго, доля к предыдущему может быть > 100%)"
    )
    k = report.k
    lines += ["", f"K = {report.converted}/{report.recipients} = " + (f"{k:.3f}" if k is not None else "—")]
    lines.append("  склейка (признак → получателей; «только» — когда он единственный):")
    for signal in SIGNALS:
        lines.append(f"    {signal:<8} любой {report.signals_any[signal]:>4}   только {report.signals_only[signal]:>4}")
    lines.append(f"    сошлись два и больше признаков: {report.signals_multi}")
    if report.max_act:
        acts = ", ".join(f"акт {act}: {n}" for act, n in report.max_act.items())
        lines.append(f"  до какого акта дошли «нет»: {acts}")
    titles = {
        "src": "канал (src открытия)",
        "via": "вход создателя (via)",
        "kind": "вид сеанса",
        "audience": "одному / компании",
    }
    for name, title in titles.items():
        rows = report.slices[name]
        if not rows:
            continue
        lines += ["", f"Разрез: {title}", "  значение            создано  получ.  «нет»  «да»  ответ  своё     K"]
        for row in rows:
            created = "—" if row.created is None else str(row.created)
            k_row = "—" if row.k is None else f"{row.k:.2f}"
            lines.append(
                f"  {row.key:<20}{created:>7}{row.recipients:>8}{row.no_attempt:>7}{row.yes:>6}"
                f"{row.send_answer:>7}{row.converted:>6}{k_row:>6}"
            )
    lines += [
        "",
        f"Порог: ≥ {THRESHOLD_MIN_INVITES} и K ≥ {THRESHOLD_K_CONTINUE} — продолжаем / "
        f"K < {THRESHOLD_K_FOLD} — сворачиваем / между — смотреть.",
        f"Итог: {report.verdict}",
    ]
    return lines
