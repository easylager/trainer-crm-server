"""Страница /k/{code}. noindex. Согласие перед первым ответом с веба."""

from __future__ import annotations

import html
import json
from typing import Any


def render_company_page(view: dict[str, Any]) -> str:
    data = json.dumps(view, ensure_ascii=False).replace("<", "\\u003c")
    title = html.escape(view.get("name") or "Компания на лёд")
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<meta property="og:title" content="{title}">
<meta property="og:description" content="{html.escape(view.get("card_text") or "")}">
<meta property="og:image" content="{html.escape(view.get("page_url") or "")}/og.png">
<style>
body {{ margin:0; font:18px/1.4 -apple-system,BlinkMacSystemFont,sans-serif; background:#f4f6f7; color:#0d1b26; }}
main {{ max-width:28rem; margin:0 auto; padding:1.25rem; }}
h1 {{ font-size:1.6rem; font-weight:650; margin:0 0 .5rem; }}
.card {{ white-space:pre-line; background:#fff; border-radius:16px; padding:1rem; }}
.row {{ display:flex; gap:.5rem; margin:1rem 0; }}
button, .share a {{ flex:1; border:0; border-radius:12px; padding:.9rem .4rem; font:inherit; background:#0d1b26; color:#fff; text-align:center; text-decoration:none; }}
button.alt {{ background:#e7eef2; color:#0d1b26; }}
label {{ display:block; margin:.5rem 0; }}
input[type=text] {{ width:100%; box-sizing:border-box; font:inherit; padding:.7rem; border-radius:12px; border:1px solid #c9d5dc; }}
.hp {{ position:absolute; left:-9999px; }}
ul {{ padding-left:1.1rem; }}
.consent {{ background:#fff; border-radius:16px; padding:1rem; margin-top:1rem; }}
</style>
</head>
<body>
<main>
<h1>Компания на лёд</h1>
<p class="card" id="card"></p>
<p id="together"></p>
<label>Имя <input id="name" type="text" maxlength="20" autocomplete="name"></label>
<p class="hp"><label>Сайт <input id="website" type="text" tabindex="-1" autocomplete="off"></label></p>
<div class="row">
<button type="button" data-status="going">Иду</button>
<button type="button" class="alt" data-status="maybe">Может</button>
<button type="button" class="alt" data-status="cant">Не могу</button>
</div>
<p id="going"></p>
<p id="cant"></p>
<p><a id="ics" href="">Добавить в календарь</a></p>
<p class="share" id="share"></p>
<div class="consent" id="consent" hidden>
<p>Имя и ответ «иду / может / не могу» увидят остальные в этой компании. Удалить свои данные можно на этой странице. Подробности в <a href="/privacy">политике</a>.</p>
<p>Ответ уходит на сервер. Если вы открыли ссылку из Telegram или Viber, имя может оказаться у оператора мессенджера за пределами Беларуси.</p>
<button type="button" id="ok">Понятно, продолжить</button>
</div>
<button type="button" id="forget">Удалить мои данные</button>
</main>
<script type="application/json" id="companyData">{data}</script>
<script>
(function () {{
  var view = JSON.parse(document.getElementById('companyData').textContent);
  var code = view.public_code;
  var nameKey = 'glide_company_name';
  var consentKey = 'glide_company_consent';
  var tokenKey = 'glide_company_token_' + code;
  document.getElementById('card').textContent = view.card_text || '';
  document.getElementById('together').textContent = view.together_line || '';
  document.getElementById('ics').href = view.calendar_url;
  var going = (view.going || []).map(function (p) {{ return p.display_name; }}).join(', ');
  document.getElementById('going').textContent = going ? ('Идут: ' + going) : 'Пока никто не отметился';
  document.getElementById('cant').textContent = view.cant_count ? ('Не могу: ' + view.cant_count) : '';
  var name = localStorage.getItem(nameKey) || '';
  document.getElementById('name').value = name;
  var page = location.origin + '/k/' + code;
  var text = view.card_text || '';
  document.getElementById('share').innerHTML =
    '<a href="viber://forward?text=' + encodeURIComponent(text + ' ' + page) + '">Viber</a> ' +
    '<a href="https://t.me/share/url?url=' + encodeURIComponent(page) + '&text=' + encodeURIComponent(text) + '">Telegram</a> ' +
    '<a href="' + page + '" id="copy">Ссылка</a>';
  document.getElementById('copy').addEventListener('click', function (e) {{
    e.preventDefault();
    navigator.clipboard && navigator.clipboard.writeText(page);
  }});
  function post(status) {{
    if (!localStorage.getItem(consentKey)) {{
      document.getElementById('consent').hidden = false;
      document.getElementById('ok').onclick = function () {{
        localStorage.setItem(consentKey, '1');
        document.getElementById('consent').hidden = true;
        post(status);
      }};
      return;
    }}
    var body = {{
      status: status,
      display_name: document.getElementById('name').value,
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
        if (!res.ok) return;
        if (res.j.participant_token) localStorage.setItem(tokenKey, res.j.participant_token);
        localStorage.setItem(nameKey, document.getElementById('name').value);
        location.reload();
      }});
  }}
  document.querySelectorAll('button[data-status]').forEach(function (btn) {{
    btn.addEventListener('click', function () {{ post(btn.getAttribute('data-status')); }});
  }});
  document.getElementById('forget').addEventListener('click', function () {{
    var token = localStorage.getItem(tokenKey) || '';
    fetch('/api/public/ice-companies/' + code + '/me', {{
      method: 'DELETE',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ participant_token: token }})
    }}).then(function () {{
      localStorage.removeItem(tokenKey);
      location.reload();
    }});
  }});
}})();
</script>
</body>
</html>
"""
