"""Страница /k/{code}. noindex.

Ночной каток: порог — крупная цифра, имя встаёт на лёд по нажатию «Я».
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from src.application.ice_company.copy import clock, crowd_line, kind_label, weekday_in
from src.application.style_b import public_fonts_head_html

_SKATE = frozenset({"public_skate", "open_ice"})
_MARKS = 8

_CSS = """
:root {
  color-scheme: dark;
  --g-bg: #0e1c24; --g-surface: #14313b; --g-ink: #f4f7f8; --g-muted: #9bb0bc;
  --g-ink-2: #d5e2e8; --g-line: #2a4652; --g-line-strong: rgba(244, 247, 248, .28);
  --g-accent: #7fd7d8; --g-accent-pressed: #45b9bb; --g-on-accent: #04262a;
  --g-accent-ink: #9fe7e4; --g-accent-wash: #1c4a50;
  --g-warn-wash: #3a2d13; --g-warn-ink: #ffcf86;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(90% 40% at 50% -10%, rgba(127, 215, 216, .22), transparent 55%),
    var(--g-bg);
  color: var(--g-ink);
  font-family: var(--g-font);
  font-size: 16px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
}
button, input { font: inherit; color: inherit; }
button { cursor: pointer; background: none; border: 0; padding: 0; }
:focus-visible { outline: 2px solid var(--g-accent); outline-offset: 3px; }
.wrap { max-width: 440px; margin: 0 auto; padding: 22px 20px 56px; display: grid; gap: 18px; }
.brand { font-weight: 700; font-size: 17px; letter-spacing: -.01em; color: inherit; text-decoration: none; }
.brand span { color: var(--g-accent-ink); }
.kicker { margin: 0; font-size: 13px; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; color: var(--g-accent-ink); }
h1 {
  margin: 0;
  font-family: var(--g-font-display);
  font-weight: 400;
  font-size: clamp(32px, 9vw, 44px);
  line-height: .95;
  letter-spacing: -.02em;
  text-wrap: balance;
}
.when { display: flex; align-items: baseline; gap: 10px; }
.when b { font-size: 40px; font-weight: 650; letter-spacing: -.04em; line-height: 1; font-variant-numeric: tabular-nums; }
.when span { font-size: 15px; font-weight: 650; color: var(--g-ink-2); }
.warn { margin: 0; color: var(--g-warn-ink); font-size: 15px; font-weight: 650; }
.rink {
  position: relative;
  display: flex; flex-wrap: nowrap; align-items: center; justify-content: center; gap: 6px;
  min-height: 112px; margin: 0; padding: 22px 14px;
  border-radius: 999px;
  background:
    radial-gradient(80% 120% at 50% 120%, rgba(127, 215, 216, .28), transparent 60%),
    var(--g-surface);
  box-shadow: inset 0 0 0 3px var(--g-accent), inset 0 0 0 10px rgba(255, 255, 255, .04);
}
.seat {
  position: relative; z-index: 1;
  display: inline-flex; align-items: center; justify-content: center;
  width: 48px; height: 48px; min-width: 48px; padding: 0; border-radius: 50%;
  border: 2px dashed var(--g-line-strong); background: transparent; color: var(--g-muted);
  font-size: 13px; font-weight: 700;
  overflow: hidden; white-space: nowrap;
}
.seat.is-taken {
  width: auto; max-width: 96px; min-width: 48px; padding: 0 12px; border-radius: 999px;
  border-style: solid; border-color: transparent;
  background: var(--g-ink); color: var(--g-on-accent);
  text-overflow: ellipsis;
}
.seat.is-mine { box-shadow: 0 0 0 3px var(--g-accent); }
.seat.is-next {
  border: 0; background: var(--g-accent); color: var(--g-on-accent);
  font-family: var(--g-font-display); font-size: 22px; font-weight: 400;
}
input.seat.is-next {
  width: 92px; min-width: 92px; flex: 0 0 92px; z-index: 2;
  border: 2px solid var(--g-accent); border-radius: 999px; background: transparent;
  color: var(--g-ink); font-family: var(--g-font); font-size: 16px; font-weight: 650; text-align: center;
}
input.seat.is-next::placeholder { color: var(--g-muted); opacity: 1; font-weight: 600; }
.miss { display: grid; gap: 2px; margin: 0; }
.miss b {
  font-family: var(--g-font-display); font-weight: 400;
  font-size: clamp(72px, 22vw, 104px); line-height: .85; letter-spacing: -.04em;
}
.miss span { font-size: 15px; font-weight: 650; color: var(--g-muted); }
.miss.is-go b { font-size: clamp(56px, 16vw, 80px); color: var(--g-accent-ink); }
.maybe { margin: 0; font-size: 15px; color: var(--g-ink-2); }
.fine { margin: 0; font-size: 13px; color: var(--g-muted); }
.quiet { display: flex; gap: 18px; }
.quiet button { min-height: 44px; font-size: 16px; font-weight: 650; color: var(--g-ink-2); text-decoration: underline; text-underline-offset: 4px; }
.quiet button.is-on { color: var(--g-accent-ink); }
.err { margin: 0; font-size: 14px; font-weight: 650; color: var(--g-warn-ink); }
.err:empty { display: none; }
.tools { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 8px 0 0; }
.tools a, .tools button { color: var(--g-accent-ink); font-size: 14px; font-weight: 650; text-decoration: none; }
.tools button.forget { color: var(--g-muted); font-weight: 500; }
.hp { position: absolute; left: -9999px; }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto; } }
"""


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _starts(view: dict[str, Any]) -> datetime:
    raw = str(view["event"]["starts_at"])
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        from datetime import timezone

        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _closed(view: dict[str, Any]) -> bool:
    return view.get("status") in ("cancelled", "expired") or bool(view["event"].get("cancelled"))


def _headline(view: dict[str, Any], starts: datetime) -> str:
    kind = str(view["event"].get("kind") or "")
    verb = "Катаемся" if kind in _SKATE else "Собираемся"
    return f"{verb} в {weekday_in(starts)}"


def _marks(view: dict[str, Any]) -> str:
    going = [str(person["display_name"]) for person in view.get("going") or []]
    if _closed(view):
        if not going:
            return ""
        return '<div class="rink" role="list">' + "".join(
            f'<span class="seat is-taken" role="listitem" data-name="{_esc(name)}">{_esc(name)}</span>'
            for name in going[:_MARKS]
        ) + "</div>"
    shown = going[:_MARKS]
    parts: list[str] = []
    for name in shown:
        parts.append(
            f'<span class="seat is-taken" role="listitem" data-name="{_esc(name)}">{_esc(name)}</span>'
        )
    parts.append(
        '<button type="button" class="seat is-next" data-status="going" aria-label="Занять место">Я</button>'
    )
    extra = len(going) - len(shown)
    html_marks = '<div class="rink" role="list">' + "".join(parts) + "</div>"
    if extra > 0:
        html_marks += f'<p class="maybe">И ещё {extra}</p>'
    return html_marks


def _poster(view: dict[str, Any]) -> str:
    line = str(view.get("crowd_line") or crowd_line(int(view.get("going_count") or 0)))
    if _closed(view):
        if bool(view["event"].get("cancelled")):
            word = "Сеанс сняли"
        elif view.get("status") == "cancelled":
            word = "Сбор снят"
        elif int(view.get("going_count") or 0) >= 2:
            word = "Покатались"
        else:
            word = "Сеанс прошёл"
        return f'<p class="miss is-go"><b>{_esc(word)}</b><span>{_esc(line)}</span></p>'
    return f'<p class="maybe">{_esc(line)}</p>'


def _maybe_line(view: dict[str, Any]) -> str:
    names = [str(person["display_name"]) for person in view.get("maybe") or []]
    if not names:
        return ""
    return f'<p class="maybe">Может: {_esc(", ".join(names[:8]))}</p>'


def render_company_page(view: dict[str, Any]) -> str:
    data = json.dumps(view, ensure_ascii=False).replace("<", "\\u003c")
    starts = _starts(view)
    headline = _headline(view, starts)
    title = _esc(view.get("name") or headline)
    venue = _esc(view["event"].get("venue_label") or "")
    kind = kind_label(str(view["event"].get("kind") or ""))
    kind_html = f'<p class="kicker">{_esc(kind)}</p>' if kind else ""
    actions = '<p class="err" id="err" role="alert"></p>'
    if not _closed(view):
        actions += """
<p class="fine">Встанешь на лёд — имя увидят остальные.</p>
<div class="quiet">
<button type="button" data-status="cant">Не смогу</button>
</div>
"""
    fonts = public_fonts_head_html()
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<meta property="og:title" content="{title}">
<meta property="og:description" content="{_esc(view.get("card_text") or "")}">
<meta property="og:image" content="{_esc(view.get("page_url") or "")}/og.png">
{fonts}
<link rel="stylesheet" href="/static/shared/glide-tokens.css?v=2">
<style>{_CSS}</style>
</head>
<body>
<main class="wrap">
<a class="brand" href="/">Glide<span>.</span></a>
<p class="kicker">{_esc(view.get("name") or "Компания на лёд")}</p>
{kind_html}
<h1>{_esc(headline)}</h1>
<div class="when"><b>{_esc(clock(starts))}</b><span>{venue}</span></div>
{_marks(view)}
{_poster(view)}
{_maybe_line(view)}
{actions}
<p class="hp"><label>Сайт <input id="website" type="text" tabindex="-1" autocomplete="off"></label></p>
<p class="tools">
<a id="ics" href="{_esc(view.get("calendar_url") or "")}">В календарь</a>
<button type="button" id="copy">Ссылка</button>
<button type="button" class="forget" id="forget" hidden>Убрать меня</button>
</p>
</main>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script type="application/json" id="companyData">{data}</script>
<script>
(function () {{
  var view = JSON.parse(document.getElementById('companyData').textContent);
  var code = view.public_code;
  var nameKey = 'glide_company_name';
  var statusKey = 'glide_company_status_' + code;
  var tokenKey = 'glide_company_token_' + code;
  var pending = 'going';
  var tgUser = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initDataUnsafe
    && window.Telegram.WebApp.initDataUnsafe.user;
  var fromTelegram = tgUser ? (tgUser.first_name || tgUser.username || '') : '';
  var remembered = (localStorage.getItem(nameKey) || fromTelegram || '').trim();
  var saved = localStorage.getItem(statusKey) || '';
  document.querySelectorAll('[data-status]').forEach(function (btn) {{
    if (btn.getAttribute('data-status') === saved) btn.classList.add('is-on');
  }});
  document.querySelectorAll('.seat.is-taken').forEach(function (seat) {{
    if (remembered && seat.getAttribute('data-name') === remembered) seat.classList.add('is-mine');
  }});
  var forget = document.getElementById('forget');
  if (forget && localStorage.getItem(tokenKey)) forget.hidden = false;
  var page = location.origin + '/k/' + code;
  var copy = document.getElementById('copy');
  if (copy) copy.addEventListener('click', function () {{
    var done = function () {{ copy.textContent = 'Скопирована'; }};
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(page).then(done, done);
    else done();
  }});
  function knownName() {{
    var field = document.getElementById('name');
    var typed = field && field.value ? field.value.trim() : '';
    return typed || remembered;
  }}
  function askName(status) {{
    pending = status || 'going';
    var seat = document.querySelector('.seat.is-next');
    var err = document.getElementById('err');
    if (!seat) {{
      if (err) err.textContent = 'Как тебя записать?';
      return;
    }}
    if (seat.tagName === 'INPUT') {{ seat.focus(); return; }}
    var input = document.createElement('input');
    input.id = 'name';
    input.className = 'seat is-next';
    input.maxLength = 20;
    input.placeholder = 'Имя';
    input.setAttribute('enterkeyhint', 'done');
    input.setAttribute('aria-label', 'Как тебя записать');
    input.autocomplete = 'given-name';
    seat.replaceWith(input);
    input.focus();
    input.addEventListener('keydown', function (e) {{
      if (e.key === 'Enter') post(pending);
    }});
  }}
  var sending = false;
  function post(status) {{
    if (sending) return;
    var display = knownName();
    var err = document.getElementById('err');
    if (!display) {{
      askName(status);
      if (err) err.textContent = 'Напиши имя прямо на льду';
      return;
    }}
    if (err) err.textContent = '';
    sending = true;
    var body = {{
      status: status,
      display_name: display,
      participant_token: localStorage.getItem(tokenKey) || '',
      consent: true,
      source: 'web',
      website: document.getElementById('website').value
    }};
    fetch('/api/public/ice-companies/' + code + '/responses', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(body)
    }}).then(function (r) {{ return r.json().then(function (j) {{ return {{ ok: r.ok, j: j }}; }}); }})
      .then(function (res) {{
        sending = false;
        if (!res.ok) {{
          if (err) err.textContent = (res.j && res.j.detail) || 'Не получилось';
          return;
        }}
        if (res.j.participant_token) localStorage.setItem(tokenKey, res.j.participant_token);
        localStorage.setItem(nameKey, display);
        localStorage.setItem(statusKey, status);
        location.reload();
      }})
      .catch(function () {{
        sending = false;
        if (err) err.textContent = 'Не получилось. Проверь связь.';
      }});
  }}
  document.querySelectorAll('[data-status]').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      var status = btn.getAttribute('data-status');
      if (!knownName()) askName(status);
      else post(status);
    }});
  }});
  if (forget) forget.addEventListener('click', function () {{
    var token = localStorage.getItem(tokenKey) || '';
    fetch('/api/public/ice-companies/' + code + '/me', {{
      method: 'DELETE',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ participant_token: token }})
    }}).then(function () {{
      localStorage.removeItem(tokenKey);
      localStorage.removeItem(statusKey);
      location.reload();
    }});
  }});
}})();
</script>
</body>
</html>
"""
