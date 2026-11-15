/**
 * «Мой каток» (TASK-372).
 * ClientRinkSheet.open({ currentId: number|null, onSaved(homeArena|null) }).
 *
 * Список — тот же GET, что вкладка «Поиск»: IceTabModel.buildListUrl
 * (intent=skate, город из GET /api/webapp/client/session, окно «когда» как у «Поиска»).
 * Порядок — IceTabModel.orderForFeed, без «Рядом».
 * Подпись «сегодня ещё N» — только из sessions_left_today ленты (TASK-379).
 * Нет поля — число не показываем. Завтра и «сеансов нет» берём из ближайшего сеанса.
 * more_count — все будущие сеансы горизонта, в подпись не входит.
 */
(function (root) {
  'use strict';

  var SESSION_URL = '/api/webapp/client/session';
  var SAVE_URL = '/api/webapp/client/me/home-arena';
  var SAVE_ERROR = 'Не сохранилось. Попробуй ещё раз';
  /* Та же фраза, что COPY_FAILED в bell-follow.js. Модуль её не экспортирует. */
  var BELL_FAILED = 'Не удалось сохранить подписку.';
  var PAGE_CAP = 20;

  var COPY = {
    title: 'Где катаешься чаще всего?',
    sub: 'Покажем его сеансы в\u00a0«Я».',
    searchLabel: 'Найти каток',
    search: 'Название катка',
    save: 'Это мой каток',
    saveEmpty: 'Выбери каток',
    ask: 'Писать в\u00a0Telegram, когда каток выложит новое расписание?',
    yes: 'Да, писать',
    no: 'Не надо',
    error: SAVE_ERROR,
  };

  function pluralRu(n, one, few, many) {
    var abs = Math.abs(Number(n)) % 100;
    if (abs >= 11 && abs <= 14) return many;
    var last = abs % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  function formatClock(value) {
    var raw = String(value || '').trim();
    var match = /^(\d{1,2}):(\d{2})/.exec(raw);
    if (!match) return raw.slice(0, 5);
    return String(Number(match[1])) + ':' + match[2];
  }

  function sessionsCaption(input) {
    input = input || {};
    var left = Number(input.sessionsLeftToday);
    if (!isFinite(left) || left < 0) left = 0;
    left = Math.floor(left);
    if (left > 0) {
      return 'сегодня ещё\u00a0' + left + '\u00a0' + pluralRu(left, 'сеанс', 'сеанса', 'сеансов');
    }
    var clock = formatClock(input.tomorrowFirst);
    if (clock) return 'сегодня сеансов нет, завтра\u00a0— с\u00a0' + clock;
    return 'сегодня сеансов нет';
  }

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function addDaysIso(iso, days) {
    var parts = String(iso || '').split('-');
    if (parts.length < 3) return '';
    var date = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])));
    if (isNaN(date.getTime())) return '';
    date.setUTCDate(date.getUTCDate() + days);
    return date.getUTCFullYear() + '-' + pad2(date.getUTCMonth() + 1) + '-' + pad2(date.getUTCDate());
  }

  function minskTodayIso(now) {
    var MT = root.MinskTime;
    if (MT && typeof MT.dateIso === 'function') return MT.dateIso(now || new Date());
    try {
      var fmt = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Europe/Minsk',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      });
      var parts = fmt.formatToParts(now || new Date());
      var y = '';
      var m = '';
      var d = '';
      for (var i = 0; i < parts.length; i++) {
        if (parts[i].type === 'year') y = parts[i].value;
        if (parts[i].type === 'month') m = parts[i].value;
        if (parts[i].type === 'day') d = parts[i].value;
      }
      if (y && m && d) return y + '-' + m + '-' + d;
    } catch (err) { /* нет Intl */ }
    return '';
  }

  /**
   * Ближайший сеанс ленты, без числа «сегодня ещё».
   * sessionsLeftToday === null — сеанс сегодня есть, но сколько их, из live не узнать.
   */
  function countsFromLive(item, todayIso) {
    var live = (item && item.live) || {};
    var date = String(live.local_date || '').slice(0, 10);
    var today = String(todayIso || '');
    if (String(live.kind || '') === 'session' && date && date === today) {
      return { sessionsLeftToday: null, tomorrowFirst: null };
    }
    if (String(live.kind || '') === 'session' && today && date === addDaysIso(today, 1)) {
      return { sessionsLeftToday: 0, tomorrowFirst: formatClock(live.starts_at_local) || null };
    }
    return { sessionsLeftToday: 0, tomorrowFirst: null };
  }

  function rinkCaption(item, todayIso) {
    var live = countsFromLive(item, todayIso);
    if (item && typeof item.sessions_left_today === 'number' && isFinite(item.sessions_left_today)) {
      var left = Math.floor(item.sessions_left_today);
      if (left < 0) left = 0;
      if (left > 0) return sessionsCaption({ sessionsLeftToday: left, tomorrowFirst: null });
      var tomorrow = item.tomorrow_first;
      if (tomorrow == null || tomorrow === '') tomorrow = live.tomorrowFirst;
      return sessionsCaption({ sessionsLeftToday: 0, tomorrowFirst: tomorrow });
    }
    if (live.sessionsLeftToday == null) return '';
    return sessionsCaption({ sessionsLeftToday: 0, tomorrowFirst: live.tomorrowFirst });
  }

  function norm(value) {
    return String(value || '').toLowerCase().replace(/ё/g, 'е').trim();
  }

  function filterRinks(items, query) {
    var list = Array.isArray(items) ? items : [];
    var needle = norm(query);
    if (!needle) return list.slice();
    return list.filter(function (item) {
      return norm(item && item.name).indexOf(needle) !== -1;
    });
  }

  function buttonState(selected, busy) {
    if (!selected) return { label: COPY.saveEmpty, disabled: true };
    return { label: COPY.save, disabled: !!busy };
  }

  function afterSave(home) {
    return home && home.subscribed === true ? 'done' : 'subscribe';
  }

  function stepTitle(name) {
    var raw = String(name || '').trim();
    if (raw.charAt(0) === '\u00ab' && raw.charAt(raw.length - 1) === '\u00bb') {
      return raw + '\u00a0\u2014 твой каток';
    }
    return '\u00ab' + raw + '\u00bb\u00a0\u2014 твой каток';
  }

  function searchQuery(input) {
    input = input || {};
    var session = input.session || {};
    var model = input.model;
    var when = 'any';
    var whenDay = '';
    if (model && typeof model.hydrateWhenFromSaved === 'function') {
      var fromIce = model.hydrateWhenFromSaved(input.iceState, 'skate', []);
      var fromPref = model.hydrateWhenFromSaved(input.whenPref, 'skate', []);
      var restored = fromIce || fromPref;
      if (restored) {
        when = restored.when;
        whenDay = restored.whenDay || '';
      }
      if (session.ice_when != null || session.ice_when_day) {
        var fromSession = model.hydrateWhenFromSaved(
          { when: session.ice_when || 'any', whenDay: session.ice_when_day || '' },
          'skate',
          []
        );
        if (fromSession) {
          when = fromSession.when;
          whenDay = fromSession.whenDay || '';
        }
      }
    }
    var cityId = session.city_id;
    if (cityId == null || cityId === '') cityId = null;
    return {
      cityId: cityId,
      intent: 'skate',
      venueTypes: [],
      season: '',
      when: when,
      whenDay: whenDay,
      near: '',
    };
  }

  function orderedRinks(items, win, model) {
    var list = Array.isArray(items) ? items.slice() : [];
    if (!model || typeof model.orderForFeed !== 'function') return list;
    var parts = model.orderForFeed(list, win || null, false) || {};
    return (parts.hits || []).concat(parts.rest || []);
  }

  function iceModel() {
    if (root.IceTabModel) return root.IceTabModel;
    if (typeof require === 'function') {
      try { return require('./ice-tab-model.js'); } catch (err) { return null; }
    }
    return null;
  }

  function bellApi() {
    if (root.GlideBellFollow) return root.GlideBellFollow;
    if (typeof require === 'function') {
      try { return require('./bell-follow.js'); } catch (err) { return null; }
    }
    return null;
  }

  function storageOf(name) {
    try { return root[name] || null; } catch (err) { return null; }
  }

  var CSS = [
    '.cr-title{flex:none;margin:18px 0 0;font-family:var(--g-font-display);font-weight:400;font-size:24px;line-height:1.15}',
    '.cr-sub{flex:none;margin:8px 0 0;font-size:14px;color:var(--g-muted)}',
    '.cr-search{position:relative;flex:none;margin-top:14px;display:flex;align-items:center;gap:10px;height:44px;padding:0 14px;border-radius:14px;background:var(--g-chip);color:var(--g-muted)}',
    '.cr-search input{flex:1 1 auto;min-width:0;border:0;padding:0;background:transparent;font:400 16px var(--g-font);color:var(--g-ink);outline:none}',
    '.cr-search input::placeholder{color:var(--g-muted)}',
    '.cr-list{margin:6px -16px 0;padding:0 16px}',
    '.cr-city{margin:12px 0 2px;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--g-muted)}',
    '.cr-row{display:flex;align-items:center;gap:12px;min-height:62px;border-bottom:1px solid var(--g-line);cursor:pointer}',
    '.cr-mark{flex:none;width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;background:var(--g-chip);color:var(--g-muted)}',
    '.cr-mark.is-on{background:var(--g-accent-wash);color:var(--g-accent-ink)}',
    '.cr-text{flex:1 1 auto;min-width:0;display:flex;flex-direction:column}',
    '.cr-name{font-weight:600;font-size:16px}',
    '.cr-line{font-size:13px;color:var(--g-muted)}',
    '.cr-row input{flex:none;width:22px;height:22px;margin:0;accent-color:var(--g-accent-ink)}',
    '.cr-actions{flex:none;display:flex;flex-direction:column;gap:4px;padding-top:12px}',
    '.cr-toast{margin:0 0 8px;padding:10px 12px;border-radius:14px;background:var(--g-ink);color:var(--g-bg);font-size:14px;font-weight:600;text-align:center}',
    '.cr-toast[hidden]{display:none}',
    '.cr-save,.cr-yes,.cr-no{border:0;padding:0;font-family:var(--g-font)}',
    '.cr-save,.cr-yes{height:52px;border-radius:14px;background:var(--g-line);color:var(--g-muted);font-size:16px;font-weight:700}',
    '.cr-save:disabled{background:var(--g-line);color:var(--g-muted);opacity:1}',
    '.cr-save.is-ready,.cr-save.is-ready:disabled,.cr-yes{background:var(--g-accent);color:var(--g-on-accent);opacity:1}',
    '.cr-step{display:flex;flex-direction:column;align-items:center;text-align:center}',
    '.cr-bell{flex:none;margin-top:16px;width:64px;height:64px;border-radius:20px;display:flex;align-items:center;justify-content:center;background:var(--g-accent-wash);color:var(--g-accent-ink)}',
    '.cr-bell-title{margin:8px 0 0;font-family:var(--g-font-display);font-weight:400;font-size:22px;line-height:1.15}',
    '.cr-ask{margin:0;font-size:15px;color:var(--g-ink-2)}',
    '.cr-step .cr-actions{width:100%;gap:6px;margin-top:10px;padding-top:0}',
    '.cr-no{height:44px;background:transparent;color:var(--g-ink-2);font-size:15px;font-weight:600}',
    '.cr-no:disabled,.cr-yes:disabled{opacity:1}',
  ].join('');

  function ensureStyles() {
    var doc = root.document;
    if (!doc || typeof doc.getElementById !== 'function' || typeof doc.createElement !== 'function') return;
    if (doc.getElementById('cr-style')) return;
    var style = doc.createElement('style');
    style.id = 'cr-style';
    style.textContent = CSS;
    var parent = doc.head || doc.documentElement || doc.body;
    if (parent && parent.appendChild) parent.appendChild(style);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function svgEl(size, parts) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS ? document.createElementNS(ns, 'svg') : document.createElement('svg');
    svg.setAttribute('width', String(size));
    svg.setAttribute('height', String(size));
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    for (var i = 0; i < parts.length; i++) {
      var spec = parts[i];
      var node = document.createElementNS ? document.createElementNS(ns, spec[0]) : document.createElement(spec[0]);
      var attrs = spec[1];
      for (var key in attrs) if (Object.prototype.hasOwnProperty.call(attrs, key)) node.setAttribute(key, attrs[key]);
      svg.appendChild(node);
    }
    return svg;
  }

  function searchIcon() {
    return svgEl(18, [
      ['circle', { cx: '11', cy: '11', r: '7' }],
      ['path', { d: 'm20 20-3.9-3.9' }],
    ]);
  }

  function skateIcon() {
    return svgEl(22, [
      ['path', { d: 'M4 15h11.5c1.5 0 2.5-.8 2.5-2V6h-4v4l-3 1.2c-1.2.5-2 1.6-2 2.8' }],
      ['path', { d: 'M3 19h17' }],
    ]);
  }

  function bellIcon() {
    return svgEl(32, [
      ['path', { d: 'M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z' }],
      ['path', { d: 'M10 20a2 2 0 0 0 4 0' }],
    ]);
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

  function authHeaders(json) {
    var headers = { 'X-Telegram-Init-Data': initData() };
    if (json) headers['Content-Type'] = 'application/json';
    return headers;
  }

  function hapticSuccess() {
    try {
      var tg = root.Telegram && root.Telegram.WebApp;
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (err) { /* нет вибрации */ }
  }

  function readJson(response) {
    return response.json().catch(function () { return {}; });
  }

  function loadRinks(model, query) {
    var limit = model && model.LIST_PAGE_LIMIT ? model.LIST_PAGE_LIMIT : 50;
    var append = model && model.appendPage ? model.appendPage : function (items, more) {
      return (items || []).concat(more || []);
    };
    function page(cursor, acc) {
      var url = model.buildListUrl(Object.assign({}, query, { limit: limit, cursor: cursor || '' }));
      return fetch(url, { method: 'GET', cache: 'no-store' }).then(function (response) {
        if (!response.ok) throw new Error('list');
        return readJson(response);
      }).then(function (data) {
        data = data || {};
        var items = append(acc.items, data.items || []);
        var win = acc.window || data.window || null;
        if (data.next_cursor && acc.pages + 1 < PAGE_CAP) {
          return page(data.next_cursor, { items: items, window: win, pages: acc.pages + 1 });
        }
        return { items: items, window: win };
      });
    }
    return page('', { items: [], window: null, pages: 0 });
  }

  function open(opts) {
    opts = opts || {};
    var Sheet = root.ClientSheet;
    ensureStyles();
    var wanted = opts.currentId == null || opts.currentId === '' ? null : Number(opts.currentId);
    if (wanted != null && !isFinite(wanted)) wanted = null;
    var selected = null;
    var touched = false;
    var busy = false;
    var catalog = [];
    var cityName = '';
    var todayIso = minskTodayIso(new Date());
    var alive = true;
    var model = iceModel();

    var content = el('div', 'cr');
    var title = el('h2', 'cr-title', COPY.title);
    title.id = 'cr-title';
    var sub = el('p', 'cr-sub', COPY.sub);
    var search = el('label', 'cr-search');
    search.appendChild(searchIcon());
    search.appendChild(el('span', 'cs-sr', COPY.searchLabel));
    var input = document.createElement('input');
    input.type = 'search';
    input.placeholder = COPY.search;
    input.setAttribute('placeholder', COPY.search);
    search.appendChild(input);
    var list = el('div', 'cs-scroll cr-list');
    var actions = el('div', 'cr-actions');
    var toast = el('p', 'cr-toast', SAVE_ERROR);
    toast.setAttribute('role', 'status');
    toast.hidden = true;
    var save = el('button', 'cr-save', COPY.saveEmpty);
    save.type = 'button';
    save.disabled = true;
    actions.appendChild(toast);
    actions.appendChild(save);
    content.appendChild(title);
    content.appendChild(sub);
    content.appendChild(search);
    content.appendChild(list);
    content.appendChild(actions);

    function paintButton() {
      var state = buttonState(selected, busy);
      save.textContent = state.label;
      save.disabled = state.disabled;
      save.classList.toggle('is-ready', !!selected);
    }

    function showError() {
      toast.hidden = false;
    }

    function findById(id) {
      if (id == null) return null;
      for (var i = 0; i < catalog.length; i++) {
        if (catalog[i] && Number(catalog[i].id) === Number(id)) return catalog[i];
      }
      return null;
    }

    function rowFor(item) {
      var on = !!(selected && Number(selected.id) === Number(item.id));
      var label = el('label', 'cr-row');
      var mark = el('span', on ? 'cr-mark is-on' : 'cr-mark');
      mark.appendChild(skateIcon());
      var text = el('span', 'cr-text');
      text.appendChild(el('span', 'cr-name', item.name || ''));
      var caption = rinkCaption(item, todayIso);
      if (caption) text.appendChild(el('span', 'cr-line', caption));
      var radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'cr-rink';
      radio.value = item.id == null ? '' : String(item.id);
      radio.checked = on;
      radio.addEventListener('change', function () {
        if (!radio.checked) return;
        touched = true;
        selected = item;
        paintButton();
        paintMarks();
      });
      label.appendChild(mark);
      label.appendChild(text);
      label.appendChild(radio);
      return label;
    }

    function paintMarks() {
      var rows = list.querySelectorAll('.cr-row');
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var radio = row.querySelector('input');
        var mark = row.querySelector('.cr-mark');
        var on = !!(selected && radio && Number(radio.value) === Number(selected.id));
        if (radio) radio.checked = on;
        if (mark) mark.className = on ? 'cr-mark is-on' : 'cr-mark';
      }
    }

    function paintList() {
      var rows = filterRinks(catalog, input.value);
      while (list.firstChild) list.removeChild(list.firstChild);
      if (!rows.length) return;
      if (cityName) list.appendChild(el('h3', 'cr-city', cityName));
      for (var i = 0; i < rows.length; i++) list.appendChild(rowFor(rows[i]));
    }

    function showSubscribe(home) {
      var name = (home && home.name) || (selected && selected.name) || '';
      while (content.firstChild) content.removeChild(content.firstChild);
      content.className = 'cr cr-step';
      var badge = el('span', 'cr-bell');
      badge.appendChild(bellIcon());
      var heading = el('h2', 'cr-bell-title', stepTitle(name));
      heading.id = 'cr-bell-title';
      var ask = el('p', 'cr-ask', COPY.ask);
      var box = el('div', 'cr-actions');
      var yes = el('button', 'cr-yes', COPY.yes);
      yes.type = 'button';
      var no = el('button', 'cr-no', COPY.no);
      no.type = 'button';
      box.appendChild(yes);
      box.appendChild(no);
      content.appendChild(badge);
      content.appendChild(heading);
      content.appendChild(ask);
      content.appendChild(box);
      if (sheet && sheet.el) sheet.el.setAttribute('aria-labelledby', 'cr-bell-title');
      no.addEventListener('click', function () {
        if (!alive || busy) return;
        alive = false;
        sheet.close();
      });
      yes.addEventListener('click', function () {
        if (!alive || busy) return;
        var bell = bellApi();
        var arenaId = home && home.id != null ? home.id : (selected && selected.id);
        var tg = root.Telegram && root.Telegram.WebApp;
        if (!bell || typeof bell.run !== 'function' || arenaId == null) return;
        busy = true;
        yes.disabled = true;
        no.disabled = true;
        bell.run({
          tg: tg,
          startParam: 'follow_arena_' + String(arenaId),
          storage: null,
          post: bell.makePost(initData(), root.fetch.bind(root)),
          fetch: root.fetch.bind(root),
        }).then(function (result) {
          if (!alive) return;
          if (result && result.status === 'skipped') {
            busy = false;
            yes.disabled = false;
            no.disabled = false;
            showBellFailed(box, bell);
            return;
          }
          alive = false;
          sheet.close();
        });
      });
    }

    function showBellFailed(box, bell) {
      var phrase = bell && bell.COPY_FAILED ? bell.COPY_FAILED : BELL_FAILED;
      var note = box.querySelector ? box.querySelector('.cr-toast') : null;
      if (!note) {
        note = el('p', 'cr-toast', phrase);
        note.setAttribute('role', 'status');
        if (box.insertBefore && box.firstChild) box.insertBefore(note, box.firstChild);
        else box.appendChild(note);
      }
      note.textContent = phrase;
      note.hidden = false;
    }

    function canAskSubscribe() {
      var bell = bellApi();
      var tg = root.Telegram && root.Telegram.WebApp;
      return !!(bell && typeof bell.isTelegramPrincipal === 'function' && bell.isTelegramPrincipal(tg));
    }

    paintButton();
    var sheet = Sheet.open({
      labelledBy: 'cr-title',
      content: content,
      onClose: function () { alive = false; },
    });

    input.addEventListener('input', paintList);
    input.addEventListener('keydown', function (event) {
      if (!event || event.key !== 'Escape') return;
      if (!input.value) return;
      input.value = '';
      paintList();
      if (event.preventDefault) event.preventDefault();
      if (event.stopPropagation) event.stopPropagation();
    });
    save.addEventListener('click', function () {
      if (busy || !alive || !selected || selected.id == null) return;
      busy = true;
      paintButton();
      toast.hidden = true;
      fetch(SAVE_URL, {
        method: 'PUT',
        headers: authHeaders(true),
        body: JSON.stringify({ arena_id: Number(selected.id) }),
      }).then(function (response) {
        if (!response.ok) throw new Error('save');
        return readJson(response);
      }).then(function (data) {
        var home = data && data.home_arena;
        if (!home || home.id == null) throw new Error('save');
        if (typeof opts.onSaved === 'function') opts.onSaved(home);
        if (!alive || sheet.el.getAttribute('data-closing') === '1') return;
        if (afterSave(home) === 'done' || !canAskSubscribe()) {
          if (afterSave(home) === 'done') hapticSuccess();
          alive = false;
          sheet.close();
          return;
        }
        busy = false;
        showSubscribe(home);
      }).catch(function () {
        if (!alive) return;
        busy = false;
        paintButton();
        showError();
      });
    });

    fetch(SESSION_URL, { method: 'GET', headers: authHeaders(false), cache: 'no-store' }).then(function (response) {
      if (!response.ok) throw new Error('session');
      return readJson(response);
    }).then(function (session) {
      if (!alive) return null;
      session = session || {};
      if (session.city_name) cityName = String(session.city_name);
      var query = searchQuery({
        session: session,
        iceState: model && model.loadIceState ? model.loadIceState(storageOf('sessionStorage')) : null,
        whenPref: model && model.loadWhenPreference ? model.loadWhenPreference(storageOf('localStorage')) : null,
        model: model,
      });
      if (query.cityId == null || !model || typeof model.buildListUrl !== 'function') throw new Error('city');
      return loadRinks(model, query);
    }).then(function (loaded) {
      if (!alive || !loaded) return;
      catalog = orderedRinks(loaded.items, loaded.window, model);
      if (!cityName) {
        for (var i = 0; i < catalog.length; i++) {
          if (catalog[i] && catalog[i].city_name) {
            cityName = String(catalog[i].city_name);
            break;
          }
        }
      }
      if (!touched) selected = findById(wanted);
      paintList();
      paintButton();
    }).catch(function () {
      if (!alive) return;
      showError();
    });

    return { close: sheet.close, el: sheet.el };
  }

  var api = {
    open: open,
    COPY: COPY,
    SAVE_ERROR: SAVE_ERROR,
    pluralRu: pluralRu,
    formatClock: formatClock,
    sessionsCaption: sessionsCaption,
    countsFromLive: countsFromLive,
    rinkCaption: rinkCaption,
    filterRinks: filterRinks,
    buttonState: buttonState,
    afterSave: afterSave,
    stepTitle: stepTitle,
    searchQuery: searchQuery,
    orderedRinks: orderedRinks,
    addDaysIso: addDaysIso,
  };
  root.ClientRinkSheet = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
