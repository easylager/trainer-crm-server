"""Карточка экипировки для чата «КТО КОГО» (TASK-432): «Олег разыскивается — за 0 из 4».

Рисунки вещей — те же данные, что у Mini App (``kk_kit_shapes.json``; совпадение с ``kto-kogo-kit.js`` проверяет
tests/js/kto-kogo-kit.test.js). SVG здесь рисуется сам: пути (M L H V Q C A Z) раскладываются в ломаные, заливка —
маской (``evenodd`` — исключающим «или» подпутей), обводка — линиями. Рисуем вчетверо крупнее и уменьшаем — сглаживание.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from src.application.hockey_cards import CARD_SIZE, _display, _ellipsize, _largest, _png, _text, _wrap

_SHAPES_FILE = Path(__file__).with_name("kk_kit_shapes.json")
_SS = 4  # во сколько раз крупнее рисуем перед уменьшением
_BG = (23, 71, 181)
_WHITE = (255, 255, 255)
_SOFT = (197, 210, 238)
_YELLOW = (255, 210, 63)
_NAVY = (13, 20, 36)

# Как вещь звучит в заголовке: «Олег разыскивается», «Олег в ведре вместо шлема». Пол не нужен.
PHRASES = {
    "wanted": "разыскивается",
    "half": "в полушарфе",
    "bag": "с пакетом на голове",
    "sieve": "в маске-решете",
    "scorehat": "в шапке-табло",
    "snorkel": "в маске с трубкой",
    "hardhat": "в каске «Ремонт»",
    "curlers": "в бигуди",
    "foil": "в короне из фольги",
    "bucket": "в ведре вместо шлема",
}


@lru_cache(maxsize=1)
def shapes() -> dict:
    return json.loads(_SHAPES_FILE.read_text(encoding="utf-8"))


# ---------- матрицы и пути ----------

Matrix = tuple[float, float, float, float, float, float]  # a b c d e f, как в SVG
_ID: Matrix = (1, 0, 0, 1, 0, 0)


def _mul(m: Matrix, n: Matrix) -> Matrix:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + c * b2,
        b * a2 + d * b2,
        a * c2 + c * d2,
        b * c2 + d * d2,
        a * e2 + c * f2 + e,
        b * e2 + d * f2 + f,
    )


def _apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def parse_transform(raw: str | None) -> Matrix:
    m = _ID
    for name, args in re.findall(r"(\w+)\(([^)]*)\)", raw or ""):
        v = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        if name == "translate":
            m = _mul(m, (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0))
        elif name == "scale":
            m = _mul(m, (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0))
        elif name == "rotate":
            r = math.radians(v[0])
            cx, cy = (v[1], v[2]) if len(v) > 2 else (0.0, 0.0)
            m = _mul(m, (1, 0, 0, 1, cx, cy))
            m = _mul(m, (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0))
            m = _mul(m, (1, 0, 0, 1, -cx, -cy))
    return m


_TOKEN = re.compile(r"[MmLlHhVvQqCcAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?")


def _arc(x1, y1, rx, ry, phi, large, sweep, x2, y2, steps=24) -> list[tuple[float, float]]:
    """Дуга SVG (из конечных точек в центр) — ломаной."""
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(phi)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    k = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        k = -k
    cxp, cyp = k * rx * y1p / ry, -k * ry * x1p / rx
    cx, cy = cp * cxp - sp * cyp + (x1 + x2) / 2, sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    out = []
    for i in range(1, steps + 1):
        t = t1 + dt * i / steps
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cp * x - sp * y + cx, sp * x + cp * y + cy))
    return out


def parse_path(d: str) -> list[tuple[list[tuple[float, float]], bool]]:
    """Подпути пути SVG: (точки, замкнут ли). Кривые — ломаными по 16 отрезков."""
    tokens = _TOKEN.findall(d)
    subs: list[tuple[list[tuple[float, float]], bool]] = []
    pts: list[tuple[float, float]] = []
    x = y = sx = sy = 0.0
    i, cmd = 0, ""

    def num() -> float:
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    def flush(closed: bool) -> None:
        nonlocal pts
        if len(pts) > 1:
            subs.append((pts, closed))
        pts = []

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == "Z":
            flush(True)
            x, y = sx, sy
            continue
        if c == "M":
            flush(False)
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            sx, sy = x, y
            pts = [(x, y)]
            cmd = "l" if rel else "L"
        elif c == "L":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            pts.append((x, y))
        elif c == "H":
            n = num()
            x = x + n if rel else n
            pts.append((x, y))
        elif c == "V":
            n = num()
            y = y + n if rel else n
            pts.append((x, y))
        elif c in ("Q", "C"):
            k = 2 if c == "Q" else 3
            ctrl = [(num(), num()) for _ in range(k)]
            if rel:
                ctrl = [(x + a, y + b) for a, b in ctrl]
            p0 = (x, y)
            for s in range(1, 17):
                t = s / 16
                if c == "Q":
                    (ax, ay), (bx, by) = ctrl
                    px = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * ax + t * t * bx
                    py = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * ay + t * t * by
                else:
                    (ax, ay), (bx, by), (ex, ey) = ctrl
                    px = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * ax + 3 * (1 - t) * t * t * bx + t**3 * ex
                    py = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * ay + 3 * (1 - t) * t * t * by + t**3 * ey
                pts.append((px, py))
            x, y = ctrl[-1]
        elif c == "A":
            rx, ry, phi, large, sweep, nx, ny = (num() for _ in range(7))
            ex, ey = (x + nx, y + ny) if rel else (nx, ny)
            pts.extend(_arc(x, y, rx, ry, phi, bool(large), bool(sweep), ex, ey))
            x, y = ex, ey
        else:  # неизвестная команда — дальше не разбираем
            break
    flush(False)
    return subs


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> list[tuple[float, float]]:
    return [(cx + rx * math.cos(2 * math.pi * k / 48), cy + ry * math.sin(2 * math.pi * k / 48)) for k in range(48)]


def _round_rect(x: float, y: float, w: float, h: float, r: float) -> list[tuple[float, float]]:
    r = min(r, w / 2, h / 2)
    out: list[tuple[float, float]] = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        out.extend(
            (cx + r * math.cos(math.radians(a0 + 90 * k / 8)), cy + r * math.sin(math.radians(a0 + 90 * k / 8)))
            for k in range(9)
        )
    return out


def _color(raw: str | None) -> tuple[int, int, int] | None:
    if not raw or raw == "none":
        return None
    raw = raw.lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _dashes(pts: list[tuple[float, float]], on: float, off: float) -> list[list[tuple[float, float]]]:
    out, cur, left, draw = [], [pts[0]], on, True
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        pos = 0.0
        while seg - pos > left:
            pos += left
            p = (x1 + (x2 - x1) * pos / seg, y1 + (y2 - y1) * pos / seg)
            if draw:
                out.append(cur + [p])
            cur, draw = [p], not draw
            left = on if draw else off
        left -= seg - pos
        cur.append((x2, y2))
    if draw and len(cur) > 1:
        out.append(cur)
    return out


PAD = 0.4  # сколько вещь может выйти за круг аватара (доля размера) — столько поля у слоя вещи


def paint_item(item: str, *, size: int, stat: str = "", score: str = "") -> Image.Image:
    """Вещь на прозрачном слое: круг аватара — квадрат ``size`` в точке (``PAD*size``, ``PAD*size``) этого слоя."""
    pad = round(PAD * size)
    layer = Image.new("RGBA", (size + 2 * pad, size + 2 * pad), (0, 0, 0, 0))
    nodes = shapes().get(item)
    if not nodes:
        return layer
    k = size / 100

    def draw_nodes(items: list, m: Matrix) -> None:
        for node in items:
            tag, attrs = node[0], node[1]
            text_ = node[2] if len(node) > 2 else None
            kids = node[3] if len(node) > 3 else None
            mm = _mul(m, parse_transform(attrs.get("transform")))
            if tag == "g":
                draw_nodes(kids or [], mm)
            elif tag == "text":
                _paint_text(layer, attrs, text_ or "", mm, stat, score, pad)
            else:
                subs = _subpaths(tag, attrs)
                if subs:
                    _paint_shape(layer, subs, attrs, mm, pad)

    draw_nodes(nodes, (k, 0, 0, k, 0, 0))
    return layer


def _subpaths(tag: str, attrs: dict):
    if tag == "path":
        return parse_path(attrs["d"])
    if tag == "rect":
        w, h = float(attrs["width"]), float(attrs["height"])
        return [(_round_rect(float(attrs["x"]), float(attrs["y"]), w, h, float(attrs.get("rx", 0))), True)]
    if tag == "circle":
        r = float(attrs["r"])
        return [(_ellipse(float(attrs["cx"]), float(attrs["cy"]), r, r), True)]
    if tag == "ellipse":
        return [(_ellipse(float(attrs["cx"]), float(attrs["cy"]), float(attrs["rx"]), float(attrs["ry"])), True)]
    return None


def _scale(m: Matrix) -> float:
    return math.hypot(m[0], m[1])


def _to_px(m: Matrix, pts, pad: int) -> list[tuple[float, float]]:
    return [((px + pad) * _SS, (py + pad) * _SS) for px, py in (_apply(m, a, b) for a, b in pts)]


def _paint_shape(layer: Image.Image, subs, attrs: dict, m: Matrix, pad: int) -> None:
    w, h = layer.size
    fill = _color(attrs.get("fill", "#000000"))
    if fill is not None:
        mask = Image.new("L", (w * _SS, h * _SS), 0)
        for pts, _ in subs:
            part = Image.new("L", mask.size, 0)
            ImageDraw.Draw(part).polygon(_to_px(m, pts, pad), fill=255)
            if attrs.get("fill-rule") == "evenodd":
                mask = ImageChops.logical_xor(mask.convert("1"), part.convert("1")).convert("L")
            else:
                mask = ImageChops.lighter(mask, part)
        _blend(layer, fill, mask, float(attrs.get("fill-opacity", 1)))
    stroke = _color(attrs.get("stroke"))
    if stroke is not None:
        sw = max(1, round(float(attrs.get("stroke-width", 1)) * _scale(m) * _SS))
        mask = Image.new("L", (w * _SS, h * _SS), 0)
        d = ImageDraw.Draw(mask)
        dash = attrs.get("stroke-dasharray")
        for pts, closed in subs:
            line = _to_px(m, pts + ([pts[0]] if closed else []), pad)
            pieces = [line]
            if dash:
                on, off = (float(v) * _scale(m) * _SS for v in dash.split())
                pieces = _dashes(line, on, off)
            for piece in pieces:
                d.line(piece, fill=255, width=sw, joint="curve")
                if attrs.get("stroke-linecap") == "round":
                    for px, py in (piece[0], piece[-1]):
                        d.ellipse((px - sw / 2, py - sw / 2, px + sw / 2, py + sw / 2), fill=255)
        _blend(layer, stroke, mask, 1.0)


def _blend(layer: Image.Image, color, mask: Image.Image, alpha: float) -> None:
    small = mask.resize(layer.size, Image.Resampling.LANCZOS)
    if alpha < 1:
        small = small.point(lambda v: int(v * alpha))
    solid = Image.new("RGBA", layer.size, (*color, 255))
    solid.putalpha(small)
    layer.alpha_composite(solid)


def _paint_text(layer: Image.Image, attrs: dict, raw: str, m: Matrix, stat: str, score: str, pad: int) -> None:
    value = stat if raw == "{stat}" else score if raw == "{score}" else raw
    if not value:
        return
    font = _text(max(8, round(float(attrs.get("font-size", 12)) * _scale(m))), 900)
    color = _color(attrs.get("fill", "#000000")) or (0, 0, 0)
    px, py = _apply(m, float(attrs.get("x", 0)), float(attrs.get("y", 0)))
    ImageDraw.Draw(layer).text((px + pad, py + pad), value, font=font, fill=(*color, 255), anchor="ms")


# ---------- карточка ----------


def outfit_card_sig(token: str, league_id: int, day: str, pid: str, item: str) -> str:
    secret = hashlib.sha256(("kk-card:" + (token or "")).encode()).digest()
    return hmac.new(secret, f"o:{league_id}:{day}:{pid}:{item}".encode(), hashlib.sha256).hexdigest()[:16]


def check_outfit_card_sig(token: str, league_id: int, day: str, pid: str, item: str, sig: str) -> bool:
    return hmac.compare_digest(outfit_card_sig(token, league_id, day, pid, item), sig or "")


def outfit_head(name: str, item: str) -> str:
    return f"{name} {PHRASES[item]}"


def outfit_caption(*, name: str, item: str, stat: str) -> str:
    """Подпись под карточкой в чате: кто и в чём; у плаката — его счёт."""
    tail = f" — {stat.lower()}" if item == "wanted" and stat else ""
    return f"КТО КОГО: {outfit_head(name, item)}{tail}. Капитан лиги постарался — до следующего вечера."


def render_outfit_card(*, name: str, item: str, stat: str = "", score: str = "", joke: str = "") -> bytes:
    """1200×630: аватар с вещью слева, «Олег разыскивается» и подпись вещи справа."""
    width, height = CARD_SIZE
    image = Image.new("RGBA", CARD_SIZE, (*_BG, 255))
    draw = ImageDraw.Draw(image)
    draw.text((64, 70), "КТО КОГО?", font=_display(40), fill=(*_SOFT, 255))
    size, ax, ay = 250, 110, 210
    draw.ellipse((ax, ay, ax + size, ay + size), fill=(*_YELLOW, 255))
    initial = (name.strip()[:1] or "?").upper()
    draw.text((ax + size / 2, ay + size / 2), initial, font=_text(120, 800), fill=(*_NAVY, 255), anchor="mm")
    layer = paint_item(item, size=size, stat=stat, score=score)
    pad = round(PAD * size)
    image.alpha_composite(layer, (ax - pad, ay - pad))
    left, inner = 470, width - 470 - 64
    head = outfit_head(name, item)
    head_font = _largest(draw, head, _display, (84, 72, 64, 56, 48), inner)
    lines = _wrap(draw, head, head_font, inner)[:2]
    top = 210
    for line in lines:
        draw.text((left, top), _ellipsize(draw, line, head_font, inner), font=head_font, fill=(*_WHITE, 255))
        top += int(head_font.size * 1.15)
    if joke:
        sub_font = _text(34, 500)
        for line in _wrap(draw, joke, sub_font, inner)[:3]:
            draw.text((left, top + 18), line, font=sub_font, fill=(*_SOFT, 255))
            top += 44
    draw.text((left, height - 92), "От капитана лиги · до следующего вечера", font=_text(30, 600), fill=(*_YELLOW, 255))
    return _png(image.convert("RGB"))
