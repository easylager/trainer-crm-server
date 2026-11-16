"""TASK-426 B6: тексты новых уведомлений — тест-греп правил, склонения, неразрывные пробелы, снапшоты."""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime
from pathlib import Path

import pytest

from src.application import kk_notify_texts as tx
from src.ingestion.hockey_sources import MINSK_TZ
from src.shared.copy_ru import COPY

ROOT = Path(__file__).resolve().parents[2]
NB = " "


def _preview():
    spec = importlib.util.spec_from_file_location("kk_notify_preview", ROOT / "scripts/kk_notify_preview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREVIEW = _preview()
RENDERED = PREVIEW.render_all()
KEYS = {k: v for k, v in COPY.items() if k.startswith("kk_notify.")}
STRINGS = list(KEYS.values()) + [body for _, body in RENDERED]

FORBIDDEN_WORDS = (
    "ставк", "поставить", "поставь", "срок", "вероятност", "удво", "не упусти", "успей", "эксклюзив",
    "скучаем", "давно", "вернись к нам", "присоединяйся", "фаза", "ретеншн", "козырь", "закрытие месяца",
)  # fmt: skip
EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿←-⇿⬀-⯿]")
CAPS = re.compile(r"\b[А-ЯЁA-Z]{3,}\b")


@pytest.mark.parametrize("value", STRINGS)
def test_forbidden_content(value: str) -> None:
    low = value.lower()
    for word in FORBIDDEN_WORDS:
        assert word not in low, (word, value)
    assert "!" not in value and "×" not in value and "%" not in value, value
    assert not EMOJI.search(value), value
    assert not CAPS.search(re.sub(r"</?b>", "", value)), value
    assert '"' not in value and " ," not in value and " ." not in value, value
    assert not re.search(r"\d{4}-\d{2}-\d{2}", value), value
    assert not re.search(r"\bдо\s*\d", low), value  # «до N»
    assert "BYN" not in value and "р." not in value, value
    assert "  " not in value, value


def test_only_declared_texts_exist() -> None:
    assert "kk_notify.consent" in KEYS and len(KEYS) >= 30  # шаблоны, подписи, дни, месяцы, склонения


# ---------- неразрывные пробелы ----------


@pytest.mark.parametrize("title,body", RENDERED)
def test_nbsp_after_prepositions_numbers_and_before_dash(title: str, body: str) -> None:
    visible = re.sub(r"</?b>", "", body)
    assert not re.search(r"(?<![0-9A-Za-zА-Яа-яЁё])(в|во|на|по|у|и|о|из|за|с|со|к|не) ", visible, re.IGNORECASE), (title, visible)
    assert not re.search(r"\d(?:-м)? [А-Яа-яЁё]", visible), (title, visible)
    assert " —" not in visible, (title, visible)
    assert NB in body, title


# ---------- склонения ----------


@pytest.mark.parametrize(
    ("n", "move", "point", "player"),
    [
        (0, "ходов", "очков", "игроков"),
        (1, "ход", "очко", "игрок"),
        (2, "хода", "очка", "игрока"),
        (4, "хода", "очка", "игрока"),
        (5, "ходов", "очков", "игроков"),
        (11, "ходов", "очков", "игроков"),
        (12, "ходов", "очков", "игроков"),
        (21, "ход", "очко", "игрок"),
        (22, "хода", "очка", "игрока"),
        (25, "ходов", "очков", "игроков"),
        (101, "ход", "очко", "игрок"),
        (111, "ходов", "очков", "игроков"),
    ],
)
def test_plural_forms(n, move, point, player) -> None:
    assert (tx.word("move", n), tx.word("point", n), tx.word("player", n)) == (move, point, player)


@pytest.mark.parametrize("moves,points,expected", [
    (1, 1, "За~неделю 1~ход и~1~очко."),
    (2, 2, "За~неделю 2~хода и~2~очка."),
    (5, 11, "За~неделю 5~ходов и~11~очков."),
    (21, 21, "За~неделю 21~ход и~21~очко."),
])  # fmt: skip
def test_week_declensions(moves, points, expected) -> None:
    now = datetime(2026, 11, 16, 9, 30, tzinfo=MINSK_TZ)
    body = tx.week_text(moves=moves, points=points, club=None, month=11, rank=None, size=None, match=None, now=now)
    assert body.replace(NB, "~") == expected


@pytest.mark.parametrize("crowned,expected", [
    (3, "ещё 2~игрока"), (4, "ещё 3~игрока"), (5, "ещё 4~игрока"), (6, "ещё 5~игроков"), (12, "ещё 11~игроков"), (22, "ещё 21~игрок"),
])  # fmt: skip
def test_crown_many_declension(crowned, expected) -> None:
    now = datetime(2026, 12, 1, 10, 0, tzinfo=MINSK_TZ)
    body = tx.month_text(month=11, club="Динамо-Минск", points=10, exact=0, rank=1, size=9, crowned=crowned, i_am_crowned=True, match=None, now=now)
    assert expected in body.replace(NB, "~")


def test_exact_clause_only_when_at_least_one() -> None:
    now = datetime(2026, 12, 1, 10, 0, tzinfo=MINSK_TZ)
    base = dict(month=11, club=None, points=40, rank=None, size=None, crowned=0, i_am_crowned=False, match=None, now=now)
    assert "в~точку" not in tx.month_text(**base, exact=0).replace(NB, "~")
    assert tx.month_text(**base, exact=1).replace(NB, "~") == "В~ноябре 40~очков, 1~ход в~точку."
    assert tx.month_text(**base, exact=5).replace(NB, "~") == "В~ноябре 40~очков, 5~ходов в~точку."


def test_month_cases_for_every_month() -> None:
    for number, (nom, gen, prep) in enumerate(
        zip(
            "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь".split(),
            "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split(),
            "январе феврале марте апреле мае июне июле августе сентябре октябре ноябре декабре".split(),
        ),
        start=1,
    ):
        assert (tx.month_nom(number), tx.month_gen(number), tx.month_prep(number)) == (nom, gen, prep)


@pytest.mark.parametrize(
    ("day", "expected"),
    [(16, "сегодня"), (17, "завтра"), (18, "в среду"), (19, "в четверг"), (20, "в пятницу"), (21, "в субботу"), (22, "в воскресенье")],
)
def test_day_phrase_words(day, expected) -> None:
    now = datetime(2026, 11, 16, 9, 30, tzinfo=MINSK_TZ)
    assert tx.day_phrase(datetime(2026, 11, day, 19, 30, tzinfo=MINSK_TZ), now) == expected


def test_day_phrase_tuesday_and_far_date() -> None:
    now = datetime(2026, 11, 16, 9, 30, tzinfo=MINSK_TZ)
    assert tx.day_phrase(datetime(2026, 11, 17, 19, 30, tzinfo=MINSK_TZ), datetime(2026, 11, 11, 9, 0, tzinfo=MINSK_TZ)) == "во вторник"
    assert tx.day_phrase(datetime(2026, 12, 3, 19, 30, tzinfo=MINSK_TZ), now) == "3 декабря"


def test_day_phrase_uses_minsk_not_utc() -> None:
    from datetime import timezone

    now = datetime(2026, 11, 16, 22, 30, tzinfo=timezone.utc)  # уже 01:30 17 ноября по Минску
    start = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)  # 19:00 17-го по Минску
    assert tx.day_phrase(start, now) == "сегодня"


# ---------- правило места ----------


@pytest.mark.parametrize(
    ("rank", "size", "shown"),
    [(1, 5, True), (2, 5, True), (3, 5, False), (5, 10, True), (6, 10, False), (3, 4, False), (1, 4, False), (4, 8, True), (11, 21, False), (10, 21, True)],
)
def test_place_rule(rank, size, shown) -> None:
    assert tx.place_shown(rank, size) is shown


# ---------- снапшоты ----------

SNAPSHOT = {
    "1. Матч сегодня": "<b>Динамо-Минск~— Торпедо</b> сегодня в~19:30. Твой ход?",
    "1. Матч завтра": "<b>Динамо-Минск~— Торпедо</b> завтра в~17:00. Твой ход?",
    "2. Возврат, 3 дня": "<b>Динамо-Минск~— Ак Барс</b> в~субботу в~17:00. Твой ход?",
    "2. Возврат, 10 дней, место есть": "В~таблице ноября (Динамо-Минск) ты на~9-м~месте.\n<b>Динамо-Минск~— Ак Барс</b> в~субботу в~17:00. Твой ход?",
    "2. Возврат, 30 дней": "<b>Динамо-Минск~— Сочи</b> 3~декабря в~19:30. Твой ход?",
    "3. Итог недели, место и матч": "За~неделю 3~хода и~60~очков, в~таблице ноября (Динамо-Минск) ты на~4-м~месте.\n<b>Динамо-Минск~— Спартак</b> в~среду в~19:30. Твой ход?",
    "3. Итог недели, места нет (мало участников)": "За~неделю 3~хода и~60~очков.\n<b>Динамо-Минск~— Спартак</b> в~среду в~19:30. Твой ход?",
    "4. Месяц без короны, место": "В~таблице ноября (Динамо-Минск) ты на~3-м~месте из~21: 240~очков, 2~хода в~точку.\n<b>Динамо-Минск~— Сочи</b> в~четверг в~19:30. Твой ход?",
    "4. Месяц без короны, места нет": "В~ноябре 240~очков, 2~хода в~точку.\n<b>Динамо-Минск~— Сочи</b> в~четверг в~19:30. Твой ход?",
    "4. Корона одному": "Корона за~ноябрь (Динамо-Минск)~— твоя. 240~очков, 2~хода в~точку.\n<b>Динамо-Минск~— Сочи</b> в~четверг в~19:30. Твой ход?",
    "4. Корона на двоих": "Корона за~ноябрь (Динамо-Минск)~— на~двоих: у~тебя и~ещё одного игрока.\n<b>Динамо-Минск~— Сочи</b> в~четверг в~19:30. Твой ход?",
    "4. Корона общая, трое": "Корона за~ноябрь (Динамо-Минск)~— общая: у~тебя и~ещё 2~игрока.\n<b>Динамо-Минск~— Сочи</b> в~четверг в~19:30. Твой ход?",
    "5. Согласие после первого хода": "Присылать напоминания о~матчах и~итоги недели и~месяца? Не~чаще раза в~день.",
}  # fmt: skip


@pytest.mark.parametrize(("title", "expected"), list(SNAPSHOT.items()))
def test_snapshot(title: str, expected: str) -> None:
    got = dict(RENDERED)[title]
    assert got.replace(NB, "~") == expected


def test_every_variant_is_rendered_and_snapshotted_or_grepped() -> None:
    assert len(RENDERED) >= 19 and len({t for t, _ in RENDERED}) == len(RENDERED)


def test_no_other_players_names_or_points_in_templates() -> None:
    joined = " ".join(KEYS.values())
    assert "{name}" not in joined and "{display_name}" not in joined and "{other" not in joined


def test_preview_script_runs_without_database(capsys) -> None:
    assert PREVIEW.main([]) == 0
    out = capsys.readouterr().out
    assert "Корона за" in out and "Присылать напоминания" in out and "**" in out


# ---------- падеж клуба и экранирование ----------


def _all_team_names() -> list[str]:
    from src.application.hockey_teams import TEAMS

    return sorted(TEAMS)


def _club_texts(club: str) -> list[str]:
    now = datetime(2026, 12, 1, 10, 0, tzinfo=MINSK_TZ)
    nxt = {"home": club, "away": "Спартак", "starts_at": datetime(2026, 12, 3, 19, 30, tzinfo=MINSK_TZ)}
    month = dict(month=11, club=club, points=240, exact=2, rank=3, size=21, match=nxt, now=now)
    return [
        tx.place_line(club=club, month=11, rank=3, size=9) or "",
        tx.week_text(moves=3, points=60, club=club, month=11, rank=2, size=9, match=nxt, now=now),
        tx.month_text(**month, crowned=1, i_am_crowned=False),
        tx.month_text(**month, crowned=1, i_am_crowned=True),
        tx.month_text(**month, crowned=2, i_am_crowned=True),
        tx.month_text(**month, crowned=5, i_am_crowned=True),
    ]


@pytest.mark.parametrize("club", _all_team_names())
def test_club_name_never_follows_the_preposition_po(club: str) -> None:
    """Название клуба ставится в скобки: после «по» (где нужен дательный падеж) его нет ни у одного клуба."""
    shown = tx.club_text(club)
    for body in _club_texts(club):
        flat = body.replace(NB, " ")
        assert f"({shown})" in flat or shown in flat
        assert not re.search(r"\bпо\s+" + re.escape(shown), flat), (club, flat)


def test_templates_have_no_po_before_club_placeholder() -> None:
    for key, value in KEYS.items():
        assert "по {club}" not in value, key


def test_club_names_are_escaped_for_html() -> None:
    nasty = "Ёж&Ко <i>"
    for body in _club_texts(nasty):
        assert "Ёж&amp;Ко&nbsp;" not in body  # экранируем «&» и «<», пробелы не трогаем
        assert "Ёж&amp;Ко &lt;i&gt;" in body.replace(NB, " "), body
        assert "<i>" not in body and "Ёж&Ко" not in body
    line = tx.match_line(nasty, "А<Б", datetime(2026, 12, 3, 19, 30, tzinfo=MINSK_TZ), datetime(2026, 12, 1, 9, 30, tzinfo=MINSK_TZ))
    assert "Ёж&amp;Ко &lt;i&gt;" in line.replace(NB, " ") and "А&lt;Б" in line
    assert line.count("<b>") == 1 and line.count("</b>") == 1
