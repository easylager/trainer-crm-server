"""Brest ice palace: read the weekly «Свободное катание» poster (a picture with dates and times).

The page ``brest.hockey.by/raspisanie-svobodnogo-kataniya/`` shows the grid only as an image:
big white ``dd.mm`` over ``HH:MM`` in one column per session day. Reading the whole poster at once
loses digits («26.10» → «6.10»), so each column is cut out, thresholded and read on its own at
three contrast levels; a value counts only when at least two levels agree. If any column cannot be
read, the whole poster is refused: a missing day must be a loud failure, never a quiet gap.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date
from urllib.parse import urljoin

from src.ingestion.dates import infer_date_from_day_month
from src.ingestion.image_io import open_image_bytes

THRESHOLDS = (170, 190, 210)  # date line: three contrast levels x two tesseract modes
TIME_THRESHOLDS = (150, 165, 180, 195)  # thin clock digits stay clean at lower levels, one mode
PSM_MODES = (7, 13)  # single line / raw line: they err differently, which is what the vote needs
MIN_VOTES = 3  # of 6 (date) / 4 (time) readings per line, and more than half of the readable ones
COLUMN_GAP_PX = 30
MIN_COLUMN_PX = 25  # a thinner cluster is a glow at the picture edge, not a column
LINE_GAP_PX = 40
INNER_LINE_GAP_PX = 4
MIN_LINE_PX = 15  # digits are ~25-35 px tall; thinner runs are glow or compression noise
_DATE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?!\d)")
_TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_POSTER_IMG = re.compile(r"""<img[^>]+width=["']?1080["']?[^>]*>""", re.I)
_SRC = re.compile(r"""src=["']([^"']+)["']""", re.I)


class PosterError(ValueError):
    """The poster is missing, unreadable or inconsistent."""


def find_poster_url(page_html: str, page_url: str) -> str:
    """The schedule image: the 1080-px-wide picture inside the page's main block, after the h1."""
    start = page_html.find("<h1")
    for match in _POSTER_IMG.finditer(page_html, start if start >= 0 else 0):
        src = _SRC.search(match.group(0))
        if src:
            return urljoin(page_url, src.group(1))
    raise PosterError("на странице нет картинки с расписанием")


def _runs(profile: list[int], gap: int) -> list[tuple[int, int]]:
    """Groups of non-empty positions; a gap of at least ``gap`` empty positions splits groups."""
    runs: list[tuple[int, int]] = []
    start = last = None
    empty = 0
    for i, value in enumerate(profile):
        if value:
            if start is None:
                start = i
            last, empty = i, 0
        elif start is not None:
            empty += 1
            if empty >= gap:
                runs.append((start, last))
                start = None
    if start is not None:
        runs.append((start, last))
    return runs


def _white_mask(img, threshold: int):
    from PIL import ImageChops

    r, g, b = img.split()
    low = ImageChops.darker(ImageChops.darker(r, g), b)  # min channel: white text is bright in all three
    return low.point(lambda p: 255 if p > threshold else 0)


def _profile(mask, axis: str) -> list[int]:
    from PIL import Image

    size = (1, mask.height) if axis == "rows" else (mask.width, 1)
    return [1 if v > 0 else 0 for v in mask.resize(size, Image.BOX).tobytes()]


def _ocr_line(img, box: tuple[int, int, int, int], threshold: int, psm: int, chars: str) -> str:
    import pytesseract
    from PIL import ImageOps

    mask = _white_mask(img.crop(box), threshold)
    inverted = ImageOps.invert(mask)  # black text on white reads best
    inverted = inverted.resize((inverted.width * 3, inverted.height * 3))
    inverted = ImageOps.expand(inverted, border=25, fill=255)
    return pytesseract.image_to_string(inverted, config=f"--psm {psm} -c tessedit_char_whitelist={chars}")


def _vote(readings: list, valid) -> object | None:
    """The value most readings agree on: at least MIN_VOTES and more than half of the readable ones."""
    values = [v for v in (valid(r) for r in readings) if v is not None]
    if not values:
        return None
    best, count = Counter(values).most_common(1)[0]
    return best if count >= MIN_VOTES and count * 2 > len(values) else None


def _valid_date(text: str):
    m = _DATE.search(text)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    return (day, month) if 1 <= day <= 31 and 1 <= month <= 12 else None


def _valid_time(text: str):
    m = _TIME.search(text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    return (hour, minute) if 0 <= hour <= 23 and 0 <= minute <= 59 else None


def _read_column(img, col_box: tuple[int, int, int, int]):
    """((day, month), (hour, minute)) for one column, or None when a line cannot be read with confidence."""
    column_mask = _white_mask(img.crop(col_box), THRESHOLDS[1])
    lines = [(a, b) for a, b in _runs(_profile(column_mask, "rows"), INNER_LINE_GAP_PX) if b - a >= MIN_LINE_PX]
    if len(lines) != 2:
        return None
    x0, y0, x1, _ = col_box
    pad = 6
    boxes = [(x0, y0 + a - pad, x1, y0 + b + pad) for a, b in lines]
    date_reads = [_ocr_line(img, boxes[0], t, psm, "0123456789.") for t in THRESHOLDS for psm in PSM_MODES]
    time_reads = [_ocr_line(img, boxes[1], t, 7, "0123456789:") for t in TIME_THRESHOLDS]
    day_month = _vote(date_reads, _valid_date)
    clock = _vote(time_reads, _valid_time)
    return (day_month, clock) if day_month and clock else None


def read_poster(image_bytes: bytes, reference: date) -> list[tuple[date, str]]:
    """Session dates and start times (``HH:MM``) found on the poster, in date order."""
    img = open_image_bytes(image_bytes).convert("RGB")
    offset_y = int(img.height * 0.5)
    mask = _white_mask(img.crop((0, offset_y, img.width, img.height)), THRESHOLDS[1])

    best: list[tuple[date, str]] = []
    best_bad = 0
    for y0, y1 in _runs(_profile(mask, "rows"), LINE_GAP_PX):
        band = mask.crop((0, y0, mask.width, y1 + 1))
        columns = [(a, b) for a, b in _runs(_profile(band, "cols"), COLUMN_GAP_PX) if b - a >= MIN_COLUMN_PX]
        found: list[tuple[date, str]] = []
        bad = 0
        for x0, x1 in columns:
            box = (max(0, x0 - 8), offset_y + y0 - 6, min(img.width, x1 + 8), offset_y + y1 + 6)
            result = _read_column(img, box)
            local = infer_date_from_day_month(*result[0], reference) if result else None
            if result is None or local is None:
                bad += 1
                continue
            found.append((local, f"{result[1][0]:02d}:{result[1][1]:02d}"))
        if len(found) > len(best):
            best, best_bad = found, bad
    if not best:
        raise PosterError("на афише не нашлось ни одной даты со временем")
    if best_bad:
        raise PosterError(f"не удалось прочитать {best_bad} колонок афиши, расписание неполное")
    dates = [d for d, _ in best]
    if dates != sorted(set(dates)):
        raise PosterError("даты на афише идут не по порядку или повторяются")
    return best
