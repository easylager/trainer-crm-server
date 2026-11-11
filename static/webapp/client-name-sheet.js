/**
 * «Как тебя зовут?» (TASK-373).
 * ClientNameSheet.open({ current: string, onSaved(name) }).
 * Сравнение «пусто / изменилось» — normalizeDisplayName, как сервер (TASK-367):
 * Cc/Cf убираются, ZWJ остаётся, пробелы схлопываются. Длина — кодовые точки.
 * Поле: maxlength=40 (браузер считает UTF-16). fitNameField не даёт разрезать
 * ZWJ-кластер и не пускает 41-ю кодовую точку. Имя длиннее 40 единиц UTF-16
 * скриптом ставится как есть: так серверное имя из эмодзи не ломается при открытии.
 */
(function (root) {
  'use strict';

  var NAME_URL = '/api/webapp/client/me/name';
  var EMPTY_HINT = 'Имя не может быть пустым';
  var NET_HINT = 'Не сохранилось. Попробуй ещё раз';
  var ZWJ = 0x200D;
  var MAX_POINTS = 40;
  var STYLE_ID = 'cn-style';

  /* Категории Cc и Cf, кроме ZWJ. Снято с unicodedata того же Python, что и сервер. */
  var DROPPED = [
    [0x0000, 0x001F],
    [0x007F, 0x009F],
    [0x00AD, 0x00AD],
    [0x0600, 0x0605],
    [0x061C, 0x061C],
    [0x06DD, 0x06DD],
    [0x070F, 0x070F],
    [0x0890, 0x0891],
    [0x08E2, 0x08E2],
    [0x180E, 0x180E],
    [0x200B, 0x200C],
    [0x200E, 0x200F],
    [0x202A, 0x202E],
    [0x2060, 0x2064],
    [0x2066, 0x206F],
    [0xFEFF, 0xFEFF],
    [0xFFF9, 0xFFFB],
    [0x110BD, 0x110BD],
    [0x110CD, 0x110CD],
    [0x13430, 0x1343F],
    [0x1BCA0, 0x1BCA3],
    [0x1D173, 0x1D17A],
    [0xE0001, 0xE0001],
    [0xE0020, 0xE007F],
  ];

  var CSS = [
    '.cs-body > .cn { flex: none; overflow: visible; display: flex; flex-direction: column; gap: 12px; }',
    '.cn-title { flex: none; margin: 20px 0 0; font-family: var(--g-font-display); font-weight: 400; font-size: 24px; line-height: 1.15; }',
    '.cn-sub { flex: none; margin: 0; font-size: 14px; color: var(--g-muted); }',
    '.cn-field { flex: none; display: flex; flex-direction: column; gap: 6px; margin: 0; }',
    '.cn-input { box-sizing: border-box; width: 100%; height: 52px; margin: 0; padding: 0 14px; border: 2px solid var(--g-line-strong); border-radius: 14px; background: var(--g-surface); font: 500 17px var(--g-font); color: var(--g-ink); outline: none; }',
    '.cn-input:focus, .cn-input.is-filled { border-color: var(--g-accent); }',
    '.cn-hint { min-height: 18px; font-size: 13px; line-height: 18px; color: var(--g-muted); }',
    '.cn-save { flex: none; width: 100%; height: 52px; margin: 0; padding: 0; border: 0; border-radius: 14px; background: var(--g-accent); color: var(--g-on-accent); font: 700 16px var(--g-font); }',
    '.cn-save:disabled { background: var(--g-line); color: var(--g-muted); opacity: 1; }',
  ].join('\n');

  function isDropped(cp) {
    var lo = 0;
    var hi = DROPPED.length - 1;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      var range = DROPPED[mid];
      if (cp < range[0]) hi = mid - 1;
      else if (cp > range[1]) lo = mid + 1;
      else return true;
    }
    return false;
  }

  function codePointLength(value) {
    var src = value == null ? '' : String(value);
    var n = 0;
    var i = 0;
    while (i < src.length) {
      var cp = src.codePointAt(i);
      n += 1;
      i += cp > 0xFFFF ? 2 : 1;
    }
    return n;
  }

  function normalizeDisplayName(raw) {
    var src = raw == null ? '' : String(raw);
    var kept = [];
    var i = 0;
    while (i < src.length) {
      var cp = src.codePointAt(i);
      var width = cp > 0xFFFF ? 2 : 1;
      if (cp !== ZWJ && isDropped(cp)) {
        i += width;
        continue;
      }
      kept.push(src.slice(i, i + width));
      i += width;
    }
    var parts = kept.join('').split(/[\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/);
    var words = [];
    for (var p = 0; p < parts.length; p++) {
      if (parts[p]) words.push(parts[p]);
    }
    return words.join(' ');
  }

  function fitNameField(value) {
    var src = value == null ? '' : String(value);
    var points = [];
    var i = 0;
    while (i < src.length) {
      var cp = src.codePointAt(i);
      var width = cp > 0xFFFF ? 2 : 1;
      var ch = src.slice(i, i + width);
      i += width;
      if (cp >= 0xD800 && cp <= 0xDFFF) continue;
      points.push(ch);
    }
    var clusters = [];
    var at = 0;
    while (at < points.length) {
      var end = at + 1;
      while (end < points.length && (points[end] === '\u200d' || points[end - 1] === '\u200d')) end += 1;
      clusters.push(points.slice(at, end));
      at = end;
    }
    var out = [];
    var count = 0;
    for (var c = 0; c < clusters.length; c++) {
      var cluster = clusters[c];
      if (cluster[cluster.length - 1] === '\u200d') break;
      if (count + cluster.length > MAX_POINTS) break;
      out.push(cluster.join(''));
      count += cluster.length;
    }
    return out.join('');
  }

  function draftState(current, draft) {
    var base = normalizeDisplayName(current);
    var next = normalizeDisplayName(draft);
    var empty = next === '';
    var changed = next !== base;
    return {
      normalized: next,
      empty: empty,
      changed: changed,
      canSave: !empty && changed,
      hint: empty ? EMPTY_HINT : '',
    };
  }

  function ensureStyle() {
    var doc = root.document;
    if (!doc || typeof doc.getElementById !== 'function' || typeof doc.createElement !== 'function') return;
    if (doc.getElementById(STYLE_ID)) return;
    var style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    var parent = doc.head || doc.documentElement || doc.body;
    if (parent && typeof parent.appendChild === 'function') parent.appendChild(style);
  }

  function initData() {
    var tg = root.Telegram && root.Telegram.WebApp;
    if (tg && tg.initData) return String(tg.initData);
    try {
      var search = root.location && root.location.search;
      if (!search) return '';
      return new URLSearchParams(search).get('init_data') || '';
    } catch (err) {
      return '';
    }
  }

  function hapticSuccess() {
    try {
      var tg = root.Telegram && root.Telegram.WebApp;
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (err) { /* нет вибрации */ }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function readDetail(body) {
    if (!body || typeof body.detail !== 'string') return '';
    return body.detail;
  }

  function open(opts) {
    opts = opts || {};
    var Sheet = root.ClientSheet;
    var current = opts.current == null ? '' : String(opts.current);
    var alive = true;
    var busy = false;
    var serverHint = '';

    ensureStyle();

    var content = el('div', 'cn');
    var title = el('h2', 'cn-title', 'Как тебя зовут?');
    title.id = 'cn-title';
    var sub = el('p', 'cn-sub', 'Так тебя увидят в\u00a0таблицах «Кто кого» и\u00a0в\u00a0лигах друзей.');
    var field = el('label', 'cn-field');
    field.appendChild(el('span', 'cs-sr', 'Имя'));
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'cn-input';
    input.maxLength = MAX_POINTS;
    input.setAttribute('maxlength', String(MAX_POINTS));
    input.setAttribute('autocomplete', 'nickname');
    input.setAttribute('enterkeyhint', 'done');
    input.setAttribute('aria-describedby', 'cn-hint');
    input.value = current;
    var hint = el('span', 'cn-hint', '');
    hint.id = 'cn-hint';
    field.appendChild(input);
    field.appendChild(hint);
    var save = el('button', 'cn-save', 'Сохранить');
    save.type = 'button';
    content.appendChild(title);
    content.appendChild(sub);
    content.appendChild(field);
    content.appendChild(save);

    function paint() {
      var state = draftState(current, input.value);
      hint.textContent = state.empty ? state.hint : (serverHint || '');
      save.disabled = busy || !state.canSave;
      input.classList.toggle('is-filled', !state.empty);
    }

    function placeCaret() {
      if (!alive) return;
      if (!sheet.el.isConnected || sheet.el.getAttribute('data-closing') === '1') return;
      try {
        input.focus();
        var end = input.value.length;
        if (typeof input.setSelectionRange === 'function') input.setSelectionRange(end, end);
      } catch (err) { /* фокус недоступен */ }
    }

    function fail(text) {
      if (!alive) return;
      busy = false;
      serverHint = text;
      paint();
    }

    function submit() {
      if (busy || !alive) return;
      if (!draftState(current, input.value).canSave) return;
      busy = true;
      serverHint = '';
      paint();
      var sent = input.value;
      fetch(NAME_URL, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-Telegram-Init-Data': initData(),
        },
        body: JSON.stringify({ name: sent }),
      }).then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          return { ok: response.ok, status: response.status, body: body };
        });
      }).then(function (res) {
        if (!alive || sheet.el.getAttribute('data-closing') === '1') return;
        if (res.status === 422) {
          var detail = readDetail(res.body);
          fail(detail || NET_HINT);
          return;
        }
        if (!res.ok || !res.body || typeof res.body.name !== 'string') {
          fail(NET_HINT);
          return;
        }
        hapticSuccess();
        alive = false;
        sheet.close();
        if (typeof opts.onSaved === 'function') opts.onSaved(res.body.name);
      }).catch(function () {
        fail(NET_HINT);
      });
    }

    paint();
    var sheet = Sheet.open({
      labelledBy: 'cn-title',
      content: content,
      onClose: function () { alive = false; },
    });

    function writeField(next, caret) {
      input.value = next;
      if (typeof input.setSelectionRange === 'function') {
        var pos = caret > next.length ? next.length : caret;
        if (pos < 0) pos = 0;
        input.setSelectionRange(pos, pos);
      }
      serverHint = '';
      paint();
    }

    input.addEventListener('beforeinput', function (event) {
      if (!event || !event.cancelable || event.data == null) return;
      var type = event.inputType;
      if (type !== 'insertText' && type !== 'insertFromPaste') return;
      if (event.preventDefault) event.preventDefault();
      var start = typeof input.selectionStart === 'number' ? input.selectionStart : input.value.length;
      var end = typeof input.selectionEnd === 'number' ? input.selectionEnd : start;
      var data = String(event.data);
      var before = input.value.slice(0, start);
      var after = input.value.slice(end);
      var next = fitNameField(before + data + after);
      var caret = fitNameField(before + data).length;
      writeField(next, caret);
    });
    input.addEventListener('input', function () {
      var next = fitNameField(input.value);
      var caret = typeof input.selectionStart === 'number' ? input.selectionStart : next.length;
      if (next !== input.value) writeField(next, caret);
      else {
        serverHint = '';
        paint();
      }
    });
    input.addEventListener('keydown', function (event) {
      if (!event || event.key !== 'Enter' || event.isComposing) return;
      if (event.preventDefault) event.preventDefault();
      submit();
    });
    save.addEventListener('click', function () {
      submit();
    });

    var raf = root.requestAnimationFrame || function (fn) { fn(); };
    raf(function () {
      raf(placeCaret);
    });

    return { close: sheet.close, el: sheet.el };
  }

  var api = {
    open: open,
    normalizeDisplayName: normalizeDisplayName,
    codePointLength: codePointLength,
    fitNameField: fitNameField,
    draftState: draftState,
  };
  root.ClientNameSheet = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
