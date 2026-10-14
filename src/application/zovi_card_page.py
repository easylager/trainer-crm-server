"""Страница открытки ``/zovi/{code}`` — тексты и SSR-шаблон (TASK-232).

Механика живёт в ``static/shared/zovi-card.js``; здесь то, что нужно без JS:
``<meta>`` для превью в Telegram и Threads, первая отрисовка вопроса и сеанса и
данные приглашения JSON-ом, чтобы скрипт не ждал запроса.

Тексты повторяют ``static/shared/zovi-model.js``: og:title, картинки и календарь
собирает сервер, а экран — браузер.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from src.application.place_page import absolute_day_label, session_kind_label
from src.shared.html_template import fill_placeholders

_REPO = Path(__file__).resolve().parents[2]
_TEMPLATE_PATH = _REPO / "static" / "share" / "zovi-card.html"
_SHARED_DIR = _REPO / "static" / "shared"

_WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_WEEKDAYS_LONG = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
_MONTHS_LONG = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_NBSP = " "


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def activity(kind: str | None) -> str:
    return "на хоккей" if kind == "hockey_practice" else "на каток"


def question_text(to_name: str | None, kind: str | None) -> str:
    """«Лера, пойдёшь со мной на каток?» / «Пойдёшь со мной на хоккей?» (S4, S5)."""
    to = (to_name or "").strip()
    tail = f"пойдёшь со мной {activity(kind)}?"
    return f"{to}, {tail}" if to else tail[:1].upper() + tail[1:]


def decline(name: str | None, kind: str) -> str:
    """«от Макса» (gen), «Максу» (dat) — эвристика прототипа. ``ins`` — «с Максом» для календаря."""
    n = (name or "").strip()
    if not n:
        return {"dat": "другу", "ins": "другом"}.get(kind, "друга")
    low = n.lower()
    if low[-1] in "ая":
        stem = n[:-1]
        if kind == "dat":
            return stem + "е"
        if kind == "ins":
            if low[-1] == "я" or (len(low) > 1 and low[-2] in "жшщчц"):
                return stem + "ей"
            return stem + "ой"
        return stem + ("и" if re.search(r"[гкхжшщч]а$|я$", low) else "ы")
    if low[-1] in "бвгджзклмнпрстфхцчшщ":
        if kind == "ins":
            return n + ("ем" if low[-1] in "жшщчц" else "ом")
        return n + ("у" if kind == "dat" else "а")
    if low[-1] == "й":
        return n[:-1] + {"dat": "ю", "ins": "ем"}.get(kind, "я")
    return n


def verdict(tries: int, falls: int, tricked: bool) -> str:
    """Вердикт без рода: открытку шлют кому угодно."""
    if tricked:
        return "Нажали «Нет». Это была «Да» в маскировке. Засчитано."
    if tries == 0:
        return "Ответ «да» — с первой секунды. Кнопка «Нет» даже не проснулась."
    if tries <= 2:
        return "Пара секунд на раздумья. Для приличия."
    if tries >= 5:
        return "Кнопка «Нет» сдалась первой."
    if falls:
        return "Кнопку «Нет» довели до падения. Беспощадно."
    return "Долго думали. Но правильно."


def ticket_who(to_name: str | None, from_name: str | None) -> tuple[str, str]:
    to = (to_name or "").strip()
    sender = (from_name or "").strip()
    return (to, sender) if to else (sender, "компания")


def _day(iso: Any) -> date | None:
    try:
        return date.fromisoformat(str(iso or "")[:10])
    except ValueError:
        return None


def day_short(iso: Any) -> str:
    """«Сб, 17 окт» — дата сеанса по Минску (``local_date`` уже минская)."""
    d = _day(iso)
    return absolute_day_label(d) if d else ""


def day_ticket(iso: Any) -> str:
    d = _day(iso)
    return f"{_WEEKDAYS_SHORT[d.weekday()]}, {d.day} {_MONTHS_LONG[d.month - 1]}" if d else ""


def day_long(iso: Any) -> str:
    d = _day(iso)
    return f"{_WEEKDAYS_LONG[d.weekday()]}, {d.day} {_MONTHS_LONG[d.month - 1]}" if d else ""


def og_description(invite: Mapping[str, Any]) -> str:
    """«Сб, 17 окт · 19:15 · Каток» — абсолютная дата: превью живёт в кэше Telegram днями."""
    s = invite["session"]
    parts = [day_short(s.get("local_date")), str(s.get("starts_at_local") or ""), str(s["arena"].get("name") or "")]
    return " · ".join(p for p in parts if p)


def kind_label(kind: str | None) -> str:
    return session_kind_label({"kind": kind or ""})


def image_version(invite: Mapping[str, Any]) -> str:
    """Хэш того, что видно на og.png: Telegram кэширует картинку по адресу."""
    s = invite["session"]
    seen = [
        invite.get("to_name"),
        invite.get("from_name"),
        invite.get("kind"),
        s.get("local_date"),
        s.get("starts_at_local"),
        s["arena"].get("name"),
    ]
    raw = json.dumps(seen, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


@lru_cache(maxsize=8)
def asset_version(name: str) -> str:
    """``?v=`` по содержимому файла: новая сборка — новый адрес, старый кэш не мешает."""
    path = _SHARED_DIR / name
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    except OSError:
        return "0"


_SHARED_SCRIPT_RE = re.compile(r'<script src="/static/shared/([a-z][a-z0-9-]*\.js)\?v=[^"]*"></script>')
_CLOSING_TAG_RE = re.compile(r"</(script|style)", re.IGNORECASE)
_SHARED_STYLE_RE = re.compile(r'<link rel="stylesheet" href="/static/shared/([a-z][a-z0-9-]*\.css)\?v=[^"]*" />')


@lru_cache(maxsize=16)
def _shared_text(name: str, mtime_ns: int) -> str:
    del mtime_ns  # ключ кэша: правка файла — новое содержимое
    # «</script» или «</style» внутри встроенного кода закрыли бы тег раньше времени.
    # Остальные «</» не трогаем: в JS это бывает регулярное выражение (/</g).
    return _CLOSING_TAG_RE.sub(r"<\\/\1", (_SHARED_DIR / name).read_text(encoding="utf-8"))


def _shared(name: str) -> str:
    return _shared_text(name, (_SHARED_DIR / name).stat().st_mtime_ns)


def inline_shared_assets(html_text: str) -> str:
    """Стили и скрипты из ``/static/shared`` — прямо в страницу.

    Открытку и ``/zovi`` открывают по ссылке из чата, во встроенных браузерах: каждый лишний
    запрос — задержка первой отрисовки. И прокси вроде бесплатного ngrok отдают телефону
    вместо подресурсов HTML-заглушку — страница остаётся без стилей и механики (2026-10-12).
    """
    html_text = _SHARED_STYLE_RE.sub(lambda m: f"<style>{_shared(m.group(1))}</style>", html_text)
    return _SHARED_SCRIPT_RE.sub(lambda m: f"<script>{_shared(m.group(1))}</script>", html_text)


def page_data(invite: Mapping[str, Any]) -> dict[str, Any]:
    """Что уходит в ``<script type="application/json">``. Без ``my_answer``: SSR не знает устройство."""
    data = {key: value for key, value in invite.items() if key != "my_answer"}
    data["kind_label"] = kind_label(str(invite.get("kind") or ""))
    data["calendar_title"] = calendar_title(invite)
    return data


def calendar_title(invite: Mapping[str, Any]) -> str:
    """«Каток с Максом» — и в .ics, и в ссылке на Google Календарь."""
    what = "Хоккей" if invite.get("kind") == "hockey_practice" else "Каток"
    return f"{what} с {decline(invite.get('from_name'), 'ins')}"


def _json_for_script(data: Mapping[str, Any]) -> str:
    # «<» экранируем целиком: «</script>» и «<!--» внутри имени не закроют тег.
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _question_html(invite: Mapping[str, Any]) -> str:
    to = (invite.get("to_name") or "").strip()
    act = activity(str(invite.get("kind") or "")).replace(" ", _NBSP)
    if to:
        return f'<span class="name">{_esc(to)}</span>, пойдёшь со{_NBSP}мной {act}?'
    return f"Пойдёшь со{_NBSP}мной {act}?"


def _plan_html(invite: Mapping[str, Any]) -> str:
    s = invite["session"]
    arena = s["arena"]
    meta = [f"{kind_label(str(invite.get('kind') or ''))} до {s.get('ends_at_local') or ''}".strip()]
    if arena.get("address"):
        meta.append(str(arena["address"]))
    if s.get("price"):
        meta.append(str(s["price"]))
    return (
        f'<span class="plan__time">{_esc(s.get("starts_at_local"))}</span>'
        f'<span class="plan__day">{_esc(day_long(s.get("local_date")))}</span>'
        f'<span class="plan__place">{_esc(arena.get("name"))}</span>'
        f'<span class="plan__meta">{_esc(" · ".join(meta))}</span>'
    )


def render_zovi_page(
    invite: Mapping[str, Any],
    *,
    page_url: str,
    og_image_url: str,
    catalog_url: str,
) -> str:
    title = question_text(invite.get("to_name"), str(invite.get("kind") or ""))
    from src.application.style_b import public_fonts_head_html

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    values = {
        "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(og_description(invite)),
        "__OG_URL__": _esc(page_url),
        "__OG_IMAGE__": _esc(og_image_url),
        "__FROM_GEN__": _esc(decline(invite.get("from_name"), "gen")),
        "__QUESTION_HTML__": _question_html(invite),
        "__PLAN_HTML__": _plan_html(invite),
        "__CATALOG_URL__": _esc(catalog_url),
        "__DATA_JSON__": _json_for_script(page_data(invite)),
        "__MODEL_V__": asset_version("zovi-model.js"),
        "__CARD_V__": asset_version("zovi-card.js"),
    }
    return inline_shared_assets(fill_placeholders(template, values))


NOT_FOUND_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>Приглашение не найдено — Glide</title>
__PUBLIC_FONTS_HEAD__
<link rel="stylesheet" href="/static/shared/glide-tokens.css?v=2" />
<style>
body{margin:0;padding:16px 16px 48px;background:var(--g-bg);color:var(--g-ink);font-family:var(--g-font);line-height:1.45;-webkit-font-smoothing:antialiased}
.wrap{max-width:440px;margin:0 auto;display:grid;gap:12px}
.brand{font-weight:700;font-size:17px;min-height:32px;display:flex;align-items:center}.brand span{color:var(--g-accent-ink)}
.hero{position:relative;background:var(--g-surface);border:1px solid var(--g-line);padding:20px 20px 20px 23px;display:grid;gap:12px;
clip-path:polygon(0 0,calc(100% - 18px) 0,100% 18px,100% 100%,0 100%)}
.hero::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:#2aa7c9}
h1{margin:0;font-size:30px;font-weight:650;line-height:1.1;letter-spacing:-.02em}p{margin:0;color:var(--g-muted)}
a.cta{display:flex;align-items:center;justify-content:center;min-height:50px;border-radius:var(--g-r);background:var(--g-accent);
color:var(--g-on-accent);font-weight:600;text-decoration:none}
</style></head>
<body><div class="wrap"><div class="brand">Glide<span>.</span></div>
<section class="hero"><h1>Такого приглашения нет</h1>
<p>Ссылка неполная или приглашение удалили. Сеансы катания — в каталоге.</p>
<a class="cta" href="__CATALOG__">Открыть каталог Glide</a></section></div></body></html>"""


def render_not_found(catalog_url: str) -> str:
    from src.application.style_b import public_fonts_head_html

    html = NOT_FOUND_HTML.replace("__PUBLIC_FONTS_HEAD__", public_fonts_head_html()).replace(
        "__CATALOG__", _esc(catalog_url)
    )
    return inline_shared_assets(html)


# ---------------------------------------------------------------------------
# Страница статуса /zovi/{code}/s/{key} — для того, кто позвал.
# Открытку собрали без Telegram — пуша нет, ответ виден здесь. Ключ в адресе —
# единственный доступ: страница не показывает кнопки «Да», чтобы создатель не ответил сам себе.

STATUS_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
__REFRESH__
<title>Ответ на открытку — Glide</title>
__PUBLIC_FONTS_HEAD__
<link rel="stylesheet" href="/static/shared/glide-tokens.css?v=2" />
<style>
body{margin:0;padding:16px 16px 48px;background:var(--g-bg);color:var(--g-ink);font-family:var(--g-font);line-height:1.45;-webkit-font-smoothing:antialiased}
.wrap{max-width:440px;margin:0 auto;display:grid;gap:12px}
.brand{font-weight:700;font-size:17px;min-height:32px;display:flex;align-items:center;color:inherit;text-decoration:none}.brand span{color:var(--g-accent-ink)}
.hero{position:relative;background:var(--g-surface);border:1px solid var(--g-line);padding:20px 20px 20px 23px;display:grid;gap:14px;
clip-path:polygon(0 0,calc(100% - 18px) 0,100% 18px,100% 100%,0 100%)}
.hero::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:#2aa7c9}
p{margin:0}.kicker{font-size:13px;color:var(--g-muted)}
.q{font-size:24px;font-weight:650;line-height:1.12;letter-spacing:-.02em}.q .name{color:var(--g-accent-ink)}
.plan{font-size:14px;color:var(--g-muted);font-variant-numeric:tabular-nums}
.state{padding-top:14px;border-top:1px solid var(--g-line);display:grid;gap:10px}
.big{font-size:30px;font-weight:650;letter-spacing:-.02em;line-height:1.1}.big span{color:var(--g-accent-ink)}
.ans{display:grid;gap:2px;padding:10px 12px;border:1px solid var(--g-line);border-radius:12px}
.ans b{font-size:16px}.ans small{font-size:13px;color:var(--g-muted)}
.muted{font-size:14px;color:var(--g-muted)}
.cta{display:flex;align-items:center;justify-content:center;min-height:50px;border-radius:var(--g-r);background:var(--g-accent);
color:var(--g-on-accent);font:inherit;font-weight:600;text-decoration:none;border:0;cursor:pointer;width:100%}
</style></head>
<body><div class="wrap"><a class="brand" href="__CATALOG__">Glide<span>.</span></a>
<section class="hero">
<p class="kicker">Твоя открытка</p>
<p class="q">__QUESTION__</p>
<p class="plan">__PLAN__</p>
<div class="state">__STATE__</div>
</section>
<button class="cta" id="again" type="button" data-url="__INVITE_URL__">Отправить открытку ещё раз</button>
<p class="muted">Сохрани эту страницу — по ней видно, ответили или нет. Ссылка только у тебя.</p>
</div>
<script>
(function(){var b=document.getElementById('again');b.addEventListener('click',function(){var u=b.getAttribute('data-url');
if(navigator.share){navigator.share({url:u}).catch(function(){});return;}
if(navigator.clipboard){navigator.clipboard.writeText(u).then(function(){b.textContent='Ссылка скопирована';});}else{window.prompt('Скопируйте:',u);}});})();
</script>
</body></html>"""


def _status_answer_html(answer: Mapping[str, Any]) -> str:
    seconds = max(0, round(int(answer.get("resist_ms") or 0) / 1000))
    tries = int(answer.get("tries") or 0)
    falls = int(answer.get("falls") or 0)
    stats = f"Держались {seconds} с · отказов {tries} · падений {falls}"
    return (
        f'<div class="ans"><b>{_esc(verdict(tries, falls, bool(answer.get("tricked"))))}</b>'
        f"<small>{_esc(stats)}</small></div>"
    )


def status_state_html(invite: Mapping[str, Any], status: Mapping[str, Any]) -> str:
    """Что видит создатель: ответ(ы), «открыли, думают» или «ещё не открыли»."""
    answers = list(status.get("answers") or [])
    to = (invite.get("to_name") or "").strip()
    if answers:
        if to:
            head = f'<p class="big"><span>{_esc(to)}</span>: ДА!</p>'
        elif len(answers) == 1:
            head = '<p class="big">Ответили: <span>ДА!</span></p>'
        else:
            head = f'<p class="big"><span>{len(answers)}</span> × ДА</p>'
        return head + "".join(_status_answer_html(a) for a in answers)
    if status.get("first_opened_at"):
        return '<p class="big">Открыли. Думают…</p><p class="muted">Кнопка «Нет» держит оборону. Страница обновится сама.</p>'
    return '<p class="big">Ещё не открыли</p><p class="muted">Как только ответят, здесь появится «ДА». Страница обновится сама.</p>'


def render_status_page(
    invite: Mapping[str, Any],
    status: Mapping[str, Any],
    *,
    invite_url: str,
    catalog_url: str,
) -> str:
    s = invite["session"]
    plan = " · ".join(
        p for p in (day_long(s.get("local_date")), str(s.get("starts_at_local") or ""), str(s["arena"].get("name") or "")) if p
    )
    answered = bool(status.get("answers"))
    values = {
        "__REFRESH__": "" if answered else '<meta http-equiv="refresh" content="30" />',
        "__CATALOG__": _esc(catalog_url),
        "__QUESTION__": _question_html(invite),
        "__PLAN__": _esc(plan),
        "__STATE__": status_state_html(invite, status),
        "__INVITE_URL__": _esc(invite_url),
    }
    from src.application.style_b import public_fonts_head_html

    out = STATUS_HTML.replace("__PUBLIC_FONTS_HEAD__", public_fonts_head_html())
    for key, value in values.items():
        out = out.replace(key, value)
    return inline_shared_assets(out)
