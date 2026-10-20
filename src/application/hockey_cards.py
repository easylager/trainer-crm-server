"""Карточки «Кто кого» для чата (TASK-300, экран 5 макета): итог «в точку!» и приглашение в лигу.

PNG 1200×630 — так Telegram показывает фото в ленте без обрезки. Цвета и шрифты — игрового слоя
(PDEC-022): синий итог с жёлтой наклейкой, тёмная шапка приглашения. Рисуем без браузера, Pillow.
"""

from __future__ import annotations

import hashlib
import hmac
import io
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.application.hockey_teams import TEAMS, UNKNOWN_COLOR, logo_path, short_from_name
from src.ingestion.hockey_sources import MINSK_TZ

CARD_SIZE = (1200, 630)
STORY_SIZE = (1080, 1920)
_PAD = 72

_BLUE = (23, 71, 181)
_NAVY = (13, 20, 36)
_YELLOW = (255, 210, 63)
_WHITE = (255, 255, 255)
_GREY = (75, 85, 104)
# Кружки участников — те же цвета, что у аватарок в игре.
_FACE_COLORS = ((23, 71, 181), (226, 80, 44), (14, 124, 102), (194, 65, 12), (107, 116, 135))

_FONTS_DIR = Path(__file__).resolve().parents[2] / "static" / "fonts"
_DISPLAY = "Unbounded-wght.ttf"
_TEXT = "GolosText-wght.ttf"

_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
# Хвастаться — от победителя и выше; за 10 очков (только шайбы) карточки нет.
_VERDICT = {50: ("в точку!", "+50"), 30: ("почти в точку", "+30"), 20: ("есть победитель", "+20")}


def _font(name: str, size: int, weight: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _FONTS_DIR / name
    if not path.is_file():
        # Без шрифта карточка выйдет некрасивой, но не 500: превью ссылки важнее.
        return ImageFont.load_default()
    font = ImageFont.truetype(str(path), size)
    try:
        font.set_variation_by_axes([weight])
    except OSError:
        pass
    return font


def _display(size: int):
    return _font(_DISPLAY, size, 800)


def _text(size: int, weight: int = 700):
    return _font(_TEXT, size, weight)


def _width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font)


def _largest(draw: ImageDraw.ImageDraw, text: str, make, sizes: Sequence[int], max_w: float):
    """Самый крупный кегль, при котором строка влезает. Если не влезла даже мелкая — мелкая."""
    for size in sizes:
        font = make(size)
        if _width(draw, text, font) <= max_w:
            return font
    return make(sizes[-1])


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> str:
    if _width(draw, text, font) <= max_w:
        return text
    cut = text
    while cut and _width(draw, cut + "…", font) > max_w:
        cut = cut[:-1]
    return cut.rstrip() + "…"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> list[str]:
    rows: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if not current or _width(draw, trial, font) <= max_w:
            current = trial
        else:
            rows.append(current)
            current = word
    if current:
        rows.append(current)
    return rows


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _sticker(label: str, *, size: int, angle: float) -> Image.Image:
    """Жёлтая наклейка «+50», чуть повёрнутая, как в игре."""
    font = _display(size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), label, font=font)
    pad_x, pad_y = int(size * 0.42), int(size * 0.26)
    w, h = int(right - left) + 2 * pad_x, int(bottom - top) + 2 * pad_y
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(size * 0.55), fill=_YELLOW)
    d.text((pad_x - left, pad_y - top), label, font=font, fill=_NAVY)
    return tile.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)


def result_verdict(points: int) -> tuple[str, str] | None:
    """Заголовок и наклейка; за промах карточки нет — хвастаться нечем."""
    return _VERDICT.get(points)


def render_result_card(*, home: str, away: str, home_score: int, away_score: int, points: int) -> bytes:
    verdict = result_verdict(points)
    if verdict is None:
        raise ValueError("карточка только за угаданный матч")
    head, sticker = verdict
    image = Image.new("RGB", CARD_SIZE, _BLUE)
    draw = ImageDraw.Draw(image)
    width, height = CARD_SIZE
    inner = width - 2 * _PAD

    draw.text((_PAD, 70), "кто кого", font=_display(40), fill=(197, 210, 238))

    head_font = _largest(draw, head, _display, (150, 132, 116, 104, 92, 84), inner)
    draw.text((_PAD, 190), head, font=head_font, fill=_WHITE)

    score = f"{home_score}:{away_score}"
    score_font = _display(120)
    score_w = _width(draw, score, score_font)
    teams = f"{home} — {away}"
    teams_max = inner - score_w - 48
    teams_font = _largest(draw, teams, _text, (52, 46, 40, 36), teams_max)
    teams = _ellipsize(draw, teams, teams_font, teams_max)
    baseline = height - 92
    draw.text((width - _PAD - score_w, baseline), score, font=score_font, fill=_WHITE, anchor="ls")
    draw.text((_PAD, baseline), teams, font=teams_font, fill=_WHITE, anchor="ls")

    tile = _sticker(sticker, size=84, angle=8)
    image.paste(tile, (width - _PAD - tile.width + 12, 44), tile)
    return _png(image)


def _hex(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _team_badge(draw: ImageDraw.ImageDraw, image: Image.Image, team: str, *, cx: int, cy: int, size: int) -> None:
    """Логотип команды в белом круге; нет логотипа — круг цвета команды с короткими буквами."""
    box = (cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2)
    known = TEAMS.get(team)
    path = logo_path(known.slug) if known else None
    if path is not None and path.is_file():
        draw.ellipse(box, fill=_WHITE)
        logo = Image.open(path).convert("RGBA")
        inner = int(size * 0.72)
        logo.thumbnail((inner, inner), Image.Resampling.LANCZOS)
        image.paste(logo, (cx - logo.width // 2, cy - logo.height // 2), logo)
        return
    draw.ellipse(box, fill=_hex(known.color if known else UNKNOWN_COLOR))
    short = known.short if known else short_from_name(team)
    draw.text((cx, cy), short, font=_display(int(size * 0.34)), fill=_WHITE, anchor="mm")


def _match_card_title(invite: bool) -> str:
    return "Погнали?" if invite else "Идём на матч?"


def match_card_version(home: str, away: str, starts_at: datetime) -> str:
    """Меняется вместе с картинкой (команды, время) — Telegram кэширует фото по адресу."""
    raw = "\x1f".join([home, away, starts_at.astimezone(MINSK_TZ).isoformat()])
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def render_match_card(*, home: str, away: str, starts_at: datetime, invite: bool = False, story: bool = False) -> bytes:
    """Открытка-превью домашнего матча: «Идём на матч?» / «Погнали?», команды, дата, Минск-Арена.

    ``story=False`` — 1200×630 для ленты и превью ссылки, ``story=True`` — 1080×1920 для историй.
    """
    size = STORY_SIZE if story else CARD_SIZE
    width, height = size
    image = Image.new("RGB", size, _BLUE)
    draw = ImageDraw.Draw(image)
    pad = _PAD
    inner = width - 2 * pad
    head = _match_card_title(invite)
    when = match_when(starts_at)
    place = "Минск-Арена"

    if story:
        head_font = _largest(draw, head, _display, (150, 132, 116, 104, 92), inner)
        draw.text((pad, 180), "кто кого", font=_display(46), fill=(197, 210, 238))
        draw.text((pad, 270), head, font=head_font, fill=_YELLOW)
        badge, centers = 340, (650, 1230)
        draw.text((width // 2, (centers[0] + centers[1]) // 2 + 10), "—", font=_display(90), fill=_WHITE, anchor="mm")
        slots = ((width // 2, centers[0], home), (width // 2, centers[1], away))
        name_gap, name_w, name_sizes = badge // 2 + 64, inner, (64, 56, 48, 42)
        when_y, place_y = 1620, 1710
        when_sizes, place_size = (86, 76, 66, 58), 54
    else:
        head_font = _largest(draw, head, _display, (96, 88, 80, 72), inner)
        draw.text((pad, 52), head, font=head_font, fill=_YELLOW)
        badge = 190
        slots = ((width // 4 + 20, 300, home), (3 * width // 4 - 20, 300, away))
        draw.text((width // 2, 300), "—", font=_display(72), fill=_WHITE, anchor="mm")
        name_gap, name_w, name_sizes = badge // 2 + 38, 470, (38, 34, 30, 27)
        when_y, place_y = 508, 566
        when_sizes, place_size = (50, 46, 42, 38), 34

    for cx, cy, team in slots:
        _team_badge(draw, image, team, cx=cx, cy=cy, size=badge)
        font = _largest(draw, team, lambda s: _text(s, 800), name_sizes, name_w)
        label = _ellipsize(draw, team, font, name_w)
        draw.text((cx, cy + name_gap), label, font=font, fill=_WHITE, anchor="mm")

    when_font = _largest(draw, when, _display, when_sizes, inner)
    draw.text((width // 2, when_y), when, font=when_font, fill=_WHITE, anchor="mm")
    draw.text((width // 2, place_y), place, font=_text(place_size, 700), fill=(197, 210, 238), anchor="mm")
    return _png(image)


def _initial(name: str) -> str:
    name = (name or "").strip()
    return name[:1].upper() if name else "·"


def people_label(count: int) -> str:
    m10, m100 = count % 10, count % 100
    if m10 == 1 and m100 != 11:
        word = "человек"
    elif 2 <= m10 <= 4 and not 12 <= m100 <= 14:
        word = "человека"
    else:
        word = "человек"
    return f"уже {count} {word}"


def match_when(starts_at: datetime) -> str:
    """«сб 24.10, 17:00» — без «завтра»: картинку пересылают, а «завтра» протухает."""
    local = starts_at.astimezone(MINSK_TZ)
    return f"{_WEEKDAYS[local.weekday()]} {local:%d.%m, %H:%M}"


def render_league_card(*, name: str, members: int, names: Sequence[str], next_match: str | None) -> bytes:
    image = Image.new("RGB", CARD_SIZE, _WHITE)
    draw = ImageDraw.Draw(image)
    width, height = CARD_SIZE
    inner = width - 2 * _PAD
    top_h = 460
    draw.rectangle((0, 0, width, top_h), fill=_NAVY)

    draw.text((_PAD, 62), "кто кого · лига", font=_display(34), fill=_YELLOW)

    # Название — крупно: сначала в одну строку, не влезло — в две, кеглем помельче, чтобы
    # обе строки встали над кружками. Ни пустого поля справа, ни обрезанного слова.
    rows: list[str] = []
    font = _display(44)
    for size, max_rows in ((120, 1), (108, 1), (96, 1), (84, 1), (74, 2), (66, 2), (58, 2), (52, 2), (44, 2)):
        font = _display(size)
        rows = _wrap(draw, name, font, inner)
        if len(rows) <= max_rows and all(_width(draw, row, font) <= inner for row in rows):
            break
    else:
        rows = rows[:2]
        rows[-1] = _ellipsize(draw, rows[-1], font, inner)
    line_h = int(font.size * 1.12)
    title_top = 124 if len(rows) == 1 else 112
    for i, row in enumerate(rows):
        draw.text((_PAD, title_top + i * line_h), row, font=font, fill=_WHITE)

    face, overlap, ring = 64, 18, 5
    y = top_h - 52 - face
    x = _PAD
    initial_font = _text(26, 800)
    for i, member in enumerate(list(names)[:6]):
        box = (x - ring, y - ring, x + face + ring, y + face + ring)
        draw.ellipse(box, fill=_NAVY)
        draw.ellipse((x, y, x + face, y + face), fill=_FACE_COLORS[i % len(_FACE_COLORS)])
        draw.text((x + face / 2, y + face / 2), _initial(member), font=initial_font, fill=_WHITE, anchor="mm")
        x += face - overlap
    label_x = x + overlap + 22 if names else _PAD
    draw.text((label_x, y + face / 2), people_label(members), font=_text(34), fill=(208, 214, 226), anchor="lm")

    if next_match:
        draw.text((_PAD, top_h + 36), "ближайший матч", font=_text(30), fill=_GREY)
        match_font = _largest(draw, next_match, lambda s: _text(s, 800), (44, 40, 36, 32), inner)
        draw.text((_PAD, top_h + 80), _ellipsize(draw, next_match, match_font, inner), font=match_font, fill=_NAVY)
    else:
        draw.text((_PAD, top_h + 58), "угадываем матчи Динамо-Минск", font=_text(44, 800), fill=_NAVY)
    return _png(image)


def _secret(token: str) -> bytes:
    return hmac.new(b"kto-kogo-card", (token or "").encode(), hashlib.sha256).digest()


def result_card_sig(token: str, match_id: int, points: int) -> str:
    """Подпись адреса карточки итога: чужие «+50» на нашем домене не нарисовать."""
    return hmac.new(_secret(token), f"{match_id}:{points}".encode(), hashlib.sha256).hexdigest()[:16]


def check_result_card_sig(token: str, match_id: int, points: int, sig: str) -> bool:
    return hmac.compare_digest(result_card_sig(token, match_id, points), sig or "")


def league_card_version(name: str, members: int, names: Sequence[str], next_match: str | None) -> str:
    """Меняется вместе с картинкой — Telegram кэширует фото по адресу."""
    raw = "\x1f".join([name, str(members), *names, next_match or ""])
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def result_caption(*, home: str, away: str, home_score: int, away_score: int, points: int) -> str:
    head, sticker = _VERDICT[points]
    return f"Кто кого: {head} {home} — {away} {home_score}:{away_score}, {sticker}"


def league_caption(name: str) -> str:
    return f"Угадываем матчи Динамо-Минск в лиге «{name}». Тапни за команду — посмотрим, кто кого."


__all__ = [
    "CARD_SIZE",
    "check_result_card_sig",
    "STORY_SIZE",
    "league_caption",
    "league_card_version",
    "match_card_version",
    "match_when",
    "people_label",
    "render_league_card",
    "render_match_card",
    "render_result_card",
    "result_caption",
    "result_card_sig",
    "result_verdict",
]
