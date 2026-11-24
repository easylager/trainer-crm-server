/* TASK-449 (этап 4): вкладка «Лёд» v2 — GET /api/webapp/client/ice/schedule.
   Макет 14: заголовок-ответ, плитки видов, дни, «идёт сейчас», линия «Сейчас»,
   «Завтра с утра». Флаг redesign_s4 (разводит сервер); redesign_s3 — бандлы и
   кэш экрана; redesign_s5 — «Я здесь» в идущих строках. */
(function () {
  'use strict';

  var global = window;
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function tg() { return global.Telegram && global.Telegram.WebApp; }
  function tgUser() {
    var w = tg();
    return (w && w.initDataUnsafe && w.initDataUnsafe.user) || null;
  }
  function initData() {
    var rt = global.MiniAppRuntime;
    if (rt && rt.getCredential) return rt.getCredential() || '';
    var w = tg();
    return w && w.initData ? String(w.initData) : '';
  }
  function haptic(kind) {
    try {
      var h = tg() && tg().HapticFeedback;
      if (!h) return;
      if (kind === 'select' && h.selectionChanged) h.selectionChanged();
      else if (kind === 'success' && h.notificationOccurred) h.notificationOccurred('success');
      else if (kind === 'error' && h.notificationOccurred) h.notificationOccurred('error');
      else if (h.impactOccurred) h.impactOccurred('light');
    } catch (e) { /* */ }
  }
  function cap(t) { t = String(t || ''); return t.charAt(0).toUpperCase() + t.slice(1); }
  function plural(n, one, few, many) {
    n = Math.abs(n) % 100;
    var n10 = n % 10;
    if (n > 10 && n < 20) return many;
    if (n10 > 1 && n10 < 5) return few;
    if (n10 === 1) return one;
    return many;
  }
  function headersJson() {
    var h = { 'Content-Type': 'application/json' };
    var init = initData();
    if (init) h['X-Telegram-Init-Data'] = init;
    var pid = profileId();
    if (pid) h['X-Profile-Id'] = String(pid);
    return h;
  }
  function profileId() {
    try {
      var v = localStorage.getItem('cw_active_profile_id_v1');
      var pid = v ? parseInt(v, 10) : null;
      if (pid == null || !(pid > 0)) {
        var init = initData();
        var user = JSON.parse(new URLSearchParams(init).get('user') || 'null');
        var d = JSON.parse(localStorage.getItem('cw_default_profile_v1') || 'null');
        if (user && d && d.u === String(user.id) && Number(d.id) > 0) pid = Number(d.id);
      }
      return pid && pid > 0 ? pid : null;
    } catch (e) { return null; }
  }
  function navigate(path) {
    if (global.ClientShell && typeof global.ClientShell.navigate === 'function') {
      global.ClientShell.navigate(path);
    } else {
      global.location.href = '/webapp/' + path;
    }
  }
  function reducedMotion() {
    try { return global.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  }

  /* ── флаги из кэша cw_ui_flags_v1 — как тема читает redesign_s1 ── */
  function flag(name) {
    try {
      var u = tgUser();
      var uid = u && u.id != null ? String(u.id) : '';
      var c = JSON.parse(localStorage.getItem('cw_ui_flags_v1') || 'null');
      return !!(c && String(c.u) === uid && c[name] === true);
    } catch (e) { return false; }
  }
  function s3On() { return flag('redesign_s3'); }
  function s5On() { return flag('redesign_s5'); }

  /* ── кэш экрана (схема hv2_screen_v1) ── */
  function screenKey(cityId, kind, day) {
    var u = tgUser();
    var uid = u && u.id != null ? String(u.id) : '0';
    return 'iv2_screen_v1:' + uid + ':' + (cityId || 0) + ':' + kind + ':' + day;
  }
  function screenRead(key) {
    try {
      var c = JSON.parse(localStorage.getItem(key) || 'null');
      if (!c || c.v !== 1 || !c.data || typeof c.at !== 'number') return null;
      if (Date.now() - c.at > 24 * 60 * 60 * 1000) return null;
      return c;
    } catch (e) { return null; }
  }
  function screenWrite(key, data) {
    try {
      var payload = JSON.stringify({ v: 1, at: Date.now(), data: data });
      if (payload.length > 220 * 1024) return;
      localStorage.setItem(key, payload);
    } catch (e) {
      try {
        var ks = [];
        for (var i = 0; i < localStorage.length; i++) {
          var k = localStorage.key(i);
          if (k && k.indexOf('iv2_screen_v1:') === 0) ks.push(k);
        }
        ks.forEach(function (k) { localStorage.removeItem(k); });
      } catch (e2) { /* */ }
    }
  }

  var KIND_ICONS = {
    skate: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 2v20M4 6l16 12M20 6 4 18M8 4l4 4 4-4M8 20l4-4 4 4"/></svg>',
    ohm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M14 4l6 6M12 12l-6 8h4l6-8"/><path d="M4 20h6"/></svg>',
    figure: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 3c0 4 3 5 5 5s5-1 5-5M12 8v11M8 21h8"/><path d="M9 14c-2 1-3 2-3 4"/></svg>',
  };
  var CHEV = '<svg class="iv2-card__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';
  var BELL = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>';

  var LOAD_WORDS = { 1: 'Сейчас свободно', 2: 'Сейчас в меру', 3: 'Сейчас людно' };

  var state = {
    cityId: null, kind: 'skate', day: 'today',
    data: null, cities: null, ciAssets: false, checkins: {},
    reqSeq: 0,
  };
  var els = {};

  /* ── параметры адреса ── */
  function readParams() {
    var q = new URLSearchParams(location.search);
    var day = (q.get('day') || q.get('when') || 'today').toLowerCase();
    if (day === 'any') day = 'week';
    if (!/^(today|tomorrow|weekend|week|\d{4}-\d{2}-\d{2})$/.test(day)) day = 'today';
    var kind = (q.get('kind') || q.get('intent') || 'skate').toLowerCase();
    if ({ skate: 1, ohm: 1, figure: 1 }[kind] == null) kind = 'skate';
    state.day = day;
    state.kind = kind;
    var cid = parseInt(q.get('city_id') || '', 10);
    if (cid > 0) state.cityId = cid;
  }
  function writeParams() {
    try {
      var q = new URLSearchParams(location.search);
      q.set('day', state.day);
      q.set('kind', state.kind);
      if (state.cityId) q.set('city_id', String(state.cityId));
      history.replaceState(null, '', location.pathname + '?' + q.toString());
    } catch (e) { /* */ }
  }

  /* ── город: ?city_id → сохранённая сессия → первый из списка ── */
  function resolveCity() {
    if (state.cityId) return Promise.resolve(state.cityId);
    return fetch('/api/webapp/client/session', { headers: headersJson(), cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var cid = d && (d.city_id != null ? d.city_id : (d.city && d.city.id));
        if (cid != null) { state.cityId = Number(cid); return state.cityId; }
        return loadCities().then(function () {
          if (state.cities && state.cities.length) { state.cityId = Number(state.cities[0].id); return state.cityId; }
          return null;
        });
      })
      .catch(function () { return null; });
  }
  function loadCities() {
    if (state.cities) return Promise.resolve(state.cities);
    return fetch('/api/public/ice/cities', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { state.cities = (d && d.items) || []; return state.cities; })
      .catch(function () { state.cities = []; return []; });
  }

  /* ── загрузка расписания ── */
  function fetchSchedule() {
    var url = '/api/webapp/client/ice/schedule?city_id=' + encodeURIComponent(state.cityId) +
      '&day=' + encodeURIComponent(state.day) + '&kind=' + encodeURIComponent(state.kind);
    return fetch(url, { headers: headersJson(), cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('schedule ' + r.status);
        return r.json();
      });
  }

  /* ── рендер ── */
  function tileHtml(k) {
    return '<button type="button" class="iv2-kind ga-press' + (k.key === state.kind ? ' iv2-kind--on' : '') +
      (k.count === 0 && k.key !== state.kind ? ' iv2-kind--empty' : '') + '" data-kind="' + esc(k.key) + '">' +
      KIND_ICONS[k.key] +
      '<span class="iv2-kind__label">' + esc(k.label) + '</span>' +
      '<span class="iv2-kind__count">' + (k.count || 0) + '</span></button>';
  }
  function dayHtml(d) {
    return '<button type="button" class="iv2-day ga-press' + (d.key === state.day ? ' iv2-day--on' : '') +
      (d.count === 0 && d.key !== state.day ? ' iv2-day--empty' : '') + '" data-day="' + esc(d.key) + '">' +
      esc(d.label) + '<span class="iv2-day__count">' + (d.count || 0) + '</span></button>';
  }
  function renderChrome(data) {
    $('iv2CityName').textContent = (data.city && data.city.name) || 'Город';
    $('iv2Title').textContent = (data.title && data.title.main) || '';
    var sub = $('iv2Sub');
    sub.innerHTML = ((data.title && data.title.sub_parts) || []).map(function (p) {
      return '<span class="' + (p.tone === 'live' ? 'iv2-live' : '') + '">' + esc(p.text) + '</span>';
    }).join('');

    var kinds = data.kinds || [];
    var kindsInWeek = kinds.filter(function (k) { return (k.week_count || 0) > 0; });
    var kindsHtml = kindsInWeek.length > 1 ? kinds.map(tileHtml).join('') : '';
    var daysHtml = data.one_rink ? '' : (data.days || []).map(dayHtml).join('');
    $('iv2Kinds').innerHTML = kindsHtml;
    $('iv2Days').innerHTML = daysHtml;
    els.stick.hidden = !kindsHtml && !daysHtml;
  }

  function rowHtml(r, opts) {
    opts = opts || {};
    var photo = (r.photo && (r.photo.thumb || r.photo.card)) || '';
    var st = state.checkins[String(r.session_id)];
    var going = '';
    if (opts.ongoing) {
      var left = r.minutes_left != null ? ' · ещё ' + r.minutes_left + ' мин' : '';
      going = '<div class="iv2-card__going">идёт' + esc(left) + '</div>';
    }
    var live = '';
    /* TASK-450 (5.3): плашка «Твоя компания · идут N» — открывает страницу компании. */
    var comp = '';
    if (s5On() && r.company && r.company.code) {
      comp = '<button type="button" class="iv2-card__comp ga-press" data-company="' + esc(r.company.page_url || '') + '">' +
        'Твоя компания · идут ' + esc(r.company.going_count) + '</button>';
    }
    if (opts.ongoing && s5On()) {
      var lv = st && st.live;
      if (lv && lv.level && LOAD_WORDS[lv.level]) {
        var ago = lv.last_min != null ? (lv.last_min < 1 ? 'только что' : lv.last_min + ' мин назад') : '';
        var bars = '<span>' + [1, 2, 3].map(function (i) { return '<i class="' + (i <= lv.level ? 'on' : '') + '"></i>'; }).join('') + '</span>';
        live = '<div class="iv2-card__live">' + bars + '<em style="font-style:normal">' +
          esc(LOAD_WORDS[lv.level] + ' · ' + (lv.count || 0) + ' ' + plural(lv.count || 0, 'отметка', 'отметки', 'отметок') + (ago ? ', ' + ago : '')) + '</em></div>';
      }
      var checked = st && st.checked_in;
      live += '<button type="button" class="iv2-card__me ga-press" data-checkin="' + r.session_id + '" data-name="' + esc(r.arena_name) + '">' +
        (checked ? 'Отмечено' : '✓ Я здесь') + '</button>';
    }
    return '<div class="iv2-row">' +
      '<div class="iv2-row__time">' + esc(r.time) + '</div>' +
      '<a class="iv2-card ga-press" href="' + esc(r.href) + '" data-arena="' + r.arena_id + '" data-session="' + r.session_id + '">' +
      '<div class="iv2-card__top">' +
      (photo ? '<img class="iv2-card__img" src="' + esc(photo) + '" width="56" height="56" loading="lazy" decoding="async" alt="">' : '<div class="iv2-card__ph"></div>') +
      '<div class="iv2-card__txt">' + going +
      '<div class="iv2-card__name">' + esc(r.arena_name) + '</div>' +
      '<div class="iv2-card__sub">' + esc(r.price_line || '') + '</div>' +
      '</div>' + CHEV + '</div>' + comp + live + '</a></div>';
  }

  /* Один каток: строка без имени/фото — время + «до … · цена» (+ идёт/живость). */
  function bareRowHtml(r, ongoing) {
    var st = state.checkins[String(r.session_id)];
    var going = '';
    if (ongoing) {
      going = '<div class="iv2-card__going">идёт' + esc(r.minutes_left != null ? ' · ещё ' + r.minutes_left + ' мин' : '') + '</div>';
    }
    var live = '';
    if (ongoing && s5On()) {
      var lv = st && st.live;
      if (lv && lv.level && LOAD_WORDS[lv.level]) {
        var ago = lv.last_min != null ? (lv.last_min < 1 ? 'только что' : lv.last_min + ' мин назад') : '';
        var bars = '<span>' + [1, 2, 3].map(function (i) { return '<i class="' + (i <= lv.level ? 'on' : '') + '"></i>'; }).join('') + '</span>';
        live = '<div class="iv2-card__live">' + bars + '<em style="font-style:normal">' +
          esc(LOAD_WORDS[lv.level] + ' · ' + (lv.count || 0) + ' ' + plural(lv.count || 0, 'отметка', 'отметки', 'отметок') + (ago ? ', ' + ago : '')) + '</em></div>';
      }
      live += '<button type="button" class="iv2-card__me ga-press" data-checkin="' + r.session_id + '" data-name="' + esc(r.arena_name) + '">' +
        (st && st.checked_in ? 'Отмечено' : '✓ Я здесь') + '</button>';
    }
    var comp = '';
    if (s5On() && r.company && r.company.code) {
      comp = '<button type="button" class="iv2-card__comp ga-press" data-company="' + esc(r.company.page_url || '') + '">' +
        'Твоя компания · идут ' + esc(r.company.going_count) + '</button>';
    }
    return '<div class="iv2-row">' +
      '<div class="iv2-row__time">' + esc(r.time) + '</div>' +
      '<a class="iv2-card iv2-card--bare ga-press" href="' + esc(r.href) + '" data-arena="' + r.arena_id + '" data-session="' + r.session_id + '">' +
      '<div class="iv2-card__top"><div class="iv2-card__txt">' + going +
      '<div class="iv2-card__sub">' + esc(r.price_line || '') + '</div>' +
      '</div>' + CHEV + '</div>' + comp + live + '</a></div>';
  }

  function rinkCardHtml(rink) {
    var photo = (rink.photo && (rink.photo.thumb || rink.photo.card)) || '';
    return '<a class="iv2-rink ga-press" href="' + esc(rink.href) + '" data-act="nav">' +
      (photo ? '<img class="iv2-rink__img" src="' + esc(photo) + '" width="64" height="64" loading="lazy" decoding="async" alt="">' : '') +
      '<div class="iv2-rink__txt"><div class="iv2-rink__name">' + esc(rink.name) + '</div>' +
      (rink.address ? '<div class="iv2-rink__addr">' + esc(rink.address) + '</div>' : '') +
      '</div>' + CHEV + '</a>';
  }

  /* «На неделе»: день + чипсы времени — как блок недели дома. */
  function weekBlockHtml(week) {
    if (!week || !week.length) return '';
    var rows = week.map(function (d) {
      var chips = (d.times || []).map(function (t) {
        return '<a class="iv2-wchip ga-press" href="' + esc(t.href || '#') + '">' + esc(t.time) + '</a>';
      }).join('');
      return '<div class="iv2-wrow"><div class="iv2-wrow__day"><div class="iv2-wrow__label">' + esc(d.label) + '</div>' +
        '<div class="iv2-wrow__sub">' + esc(d.sub || '') + '</div></div>' +
        '<div class="iv2-wrow__chips">' + chips + '</div></div>';
    }).join('');
    return '<div class="iv2-grouphead">На неделе</div><div class="iv2-week">' + rows + '</div>';
  }

  function endBlockHtml(data) {
    var tm = data.tomorrow_morning;
    if (tm) {
      var rows = tm.rows.map(function (r) {
        return '<div class="iv2-end__row"><div class="iv2-end__time">' + esc(r.time) + '</div>' +
          '<div><div class="iv2-end__name">' + esc(r.arena_name) + '</div>' +
          '<div class="iv2-end__sub">' + esc(r.price_line || '') + '</div></div></div>';
      }).join('');
      return '<div class="iv2-end"><div class="iv2-end__head">Завтра с утра <span class="iv2-end__date">' + esc(tm.label) + '</span></div>' +
        '<div class="iv2-end__card">' + rows +
        '<button type="button" class="iv2-end__all ga-press" data-goto-day="tomorrow">' + esc(tm.all_label || 'Весь ' + tm.label.split(',')[0]) + ' · ' + (tm.total || 0) +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></button></div></div>';
    }
    if (data.next_ice) {
      return '<div class="iv2-end"><div class="iv2-end__card iv2-end__card--empty">' +
        '<div class="iv2-end__title">Следующий лёд: ' + esc(data.next_ice.label) + '</div>' +
        '<button type="button" class="iv2-btn iv2-btn--ink ga-press" data-watch="1">' + BELL + ' Сообщить о новом льде</button></div></div>';
    }
    return '';
  }

  function emptyDayHtml(data) {
    return '<div class="iv2-end"><div class="iv2-end__card iv2-end__card--empty">' +
      '<div class="iv2-end__title">Расписание ещё не вышло</div>' +
      '<button type="button" class="iv2-btn iv2-btn--ink ga-press" data-watch="1">' + BELL + ' Сообщить о новом льде</button></div></div>';
  }

  function renderList(data) {
    if (data.one_rink && data.rink && state.day === 'today') {
      renderOneRink(data);
      return;
    }
    var html = '';
    var hasRows = false;
    if (data.ongoing && data.ongoing.length) {
      hasRows = true;
      html += '<div class="iv2-grouphead"><span class="iv2-dot"></span>Идёт сейчас</div>' +
        data.ongoing.map(function (r) { return rowHtml(r, { ongoing: true }); }).join('');
    }
    if (data.now_line) html += '<div class="iv2-nowline">' + esc(data.now_line) + '</div>';
    if (data.upcoming && data.upcoming.length) {
      hasRows = true;
      html += data.upcoming.map(function (r) { return rowHtml(r); }).join('');
    }
    (data.groups || []).forEach(function (g) {
      hasRows = true;
      html += '<div class="iv2-grouphead">' + esc(cap(g.label)) + '</div>' +
        g.rows.map(function (r) { return rowHtml(r); }).join('');
    });
    if (!hasRows && !data.next_ice && !data.tomorrow_morning) html += emptyDayHtml(data);
    /* «Завтра с утра» — сервером только на «Сегодня»; «Следующий лёд» — когда завтра пусто. */
    if (state.day === 'today' || (!hasRows && data.next_ice)) html += endBlockHtml(data);
    els.list.innerHTML = html;
    refreshCheckins(data);
  }

  /* Один каток: карточка катка → «Сегодня» строками без имени → «На неделе». */
  function renderOneRink(data) {
    var html = rinkCardHtml(data.rink);
    var hasRows = false;
    var todayRows = '';
    if (data.ongoing && data.ongoing.length) {
      hasRows = true;
      todayRows += data.ongoing.map(function (r) { return bareRowHtml(r, true); }).join('');
    }
    if (data.now_line) todayRows += '<div class="iv2-nowline">' + esc(data.now_line) + '</div>';
    if (data.upcoming && data.upcoming.length) {
      hasRows = true;
      todayRows += data.upcoming.map(function (r) { return bareRowHtml(r); }).join('');
    }
    if (hasRows) html += '<div class="iv2-grouphead">Сегодня</div>' + todayRows;
    html += weekBlockHtml(data.week);
    if (!hasRows && !(data.week || []).length) html += emptyDayHtml(data);
    els.list.innerHTML = html;
    refreshCheckins(data);
  }

  function errorHtml() {
    els.list.innerHTML = '<div class="iv2-end"><div class="iv2-end__card iv2-end__card--empty">' +
      '<div class="iv2-end__title">Не загрузилось</div>' +
      '<div class="iv2-end__text">Проверь сеть и попробуй ещё раз.</div>' +
      '<button type="button" class="iv2-btn iv2-btn--ink ga-press" data-retry="1">Повторить</button></div></div>';
  }

  /* ── s5: «Я здесь» в идущих строках — один запрос state на экран ── */
  function refreshCheckins(data) {
    if (!s5On() || state._ciSeq === state.reqSeq) return;
    var ids = (data.ongoing || []).map(function (r) { return r.session_id; });
    if (!ids.length) return;
    var seq = state.reqSeq;
    state._ciSeq = seq;
    fetch('/api/webapp/client/checkins/state?session_ids=' + ids.join(','), { headers: headersJson(), cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.sessions || seq !== state.reqSeq) return;
        state.checkins = j.sessions;
        renderList(state.data);
      })
      .catch(function () { /* строки живут и без загрузки */ });
    loadCheckinAssets();
  }
  function loadCheckinAssets() {
    if (global.GlideCheckin || state.ciAssets) { state.ciAssets = true; return; }
    state.ciAssets = true;
    var v = (document.querySelector('link[href*="ice-v2.css"], link[href*="ice-v2.bundle.css"]') || {}).href || '';
    var m = v.match(/[?&]v=([^&]+)/);
    var q = m ? '?v=' + m[1] : '';
    var css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'checkin-sheet.css' + q;
    document.head.appendChild(css);
    var js = document.createElement('script');
    js.src = 'checkin-sheet.js' + q;
    js.defer = true;
    document.head.appendChild(js);
  }
  function openCheckin(btn) {
    if (!global.GlideCheckin) return;
    var st = state.checkins[btn.getAttribute('data-checkin')] || {};
    global.GlideCheckin.open({
      session_id: Number(btn.getAttribute('data-checkin')),
      arena_id: Number(btn.closest('[data-arena]') && btn.closest('[data-arena]').getAttribute('data-arena')) || null,
      arena_name: btn.getAttribute('data-name') || 'катке',
      company: !!(state.data && state.data.company_share),
      checkin_id: st.checkin_id || null,
      load_level: st.load_level || null,
      season_days: st.checked_in ? st.season_days : null,
      onDone: function () {
        st.checked_in = true;
        state.checkins[btn.getAttribute('data-checkin')] = st;
        btn.textContent = 'Отмечено';
      },
    });
  }

  /* ── подписка «Сообщить о новом льде» ── */
  function watchSubscribe(btn) {
    var arena = (state.data && state.data.arenas && state.data.arenas[0]) || null;
    var body = { watch_kind: 'schedule_fresh', city_id: state.cityId };
    if (arena) body.arena_id = arena.id;
    btn.disabled = true;
    fetch('/api/webapp/client/ice-watches', { method: 'POST', headers: headersJson(), body: JSON.stringify(body) })
      .then(function (r) {
        if (r.status === 409) { btn.parentNode && btn.parentNode.removeChild(btn); return; }
        if (!r.ok) { btn.disabled = false; return; }
        haptic('success');
        var ok = document.createElement('div');
        ok.className = 'iv2-watch-ok';
        ok.textContent = 'Сообщим, когда появится лёд';
        btn.parentNode.replaceChild(ok, btn);
      })
      .catch(function () { btn.disabled = false; });
  }

  /* ── листы ── */
  function openSheet(bg, sheet) { $(bg).hidden = false; $(sheet).hidden = false; }
  function closeSheets() {
    ['iv2CityBg', 'iv2CitySheet', 'iv2SearchBg', 'iv2SearchSheet'].forEach(function (id) { $(id).hidden = true; });
  }
  function renderCityOpts(cities) {
    var host = $('iv2CityList');
    if (!cities.length) { host.innerHTML = '<div style="padding:16px 20px;color:var(--muted);font-size:15px">Не удалось загрузить города.</div>'; return; }
    host.innerHTML = cities.map(function (c) {
      var n = Number(c.skate_count) || 0;
      var sub = n > 0 ? n + ' ' + plural(n, 'каток', 'катка', 'катков')
        : (Number(c.trainer_count) || 0) + ' ' + plural(Number(c.trainer_count) || 0, 'тренер', 'тренера', 'тренеров');
      return '<button type="button" class="iv2-srow ga-press" data-city="' + c.id + '">' +
        '<span><span class="iv2-srow__name">' + esc(c.name) + '</span><br>' +
        '<span class="iv2-srow__sub">' + esc(sub) + '</span></span>' +
        '<svg class="iv2-srow__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></button>';
    }).join('');
  }
  function pickCity(id) {
    fetch('/api/webapp/client/session/catalog-filters', {
      method: 'PATCH', headers: headersJson(), body: JSON.stringify({ city_id: id }),
    }).then(function (r) {
      if (!r.ok) throw new Error('city ' + r.status);
      haptic('success');
      state.cityId = id;
      closeSheets();
      writeParams();
      load();
    }).catch(function () { haptic('error'); });
  }
  function renderSearch(q) {
    var arenas = (state.data && state.data.arenas) || [];
    var needle = (q || '').trim().toLowerCase();
    var list = needle ? arenas.filter(function (a) { return a.name.toLowerCase().indexOf(needle) >= 0; }) : arenas;
    $('iv2SearchList').innerHTML = list.length
      ? list.map(function (a) {
        return '<button type="button" class="iv2-srow ga-press" data-arena-go="' + a.id + '">' +
          '<span class="iv2-srow__name">' + esc(a.name) + '</span>' +
          '<svg class="iv2-srow__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></button>';
      }).join('')
      : '<div style="padding:16px 20px;color:var(--muted);font-size:15px">Ничего не нашлось.</div>';
  }

  /* ── загрузка + кэш ── */
  function applyData(data, fromCache) {
    state.data = data;
    renderChrome(data);
    renderList(data);
  }
  function load(opts) {
    opts = opts || {};
    var seq = ++state.reqSeq;
    var key = screenKey(state.cityId, state.kind, state.day);
    var hadCache = false;
    if (s3On() && !opts.noCache) {
      var cached = screenRead(key);
      if (cached) {
        hadCache = true;
        applyData(cached.data, true);
      }
    }
    if (!hadCache && !opts.keep) {
      els.list.innerHTML = '<div class="iv2-skel"><div class="iv2-skel__row"></div><div class="iv2-skel__row"></div><div class="iv2-skel__row"></div></div>';
    }
    if (opts.fade) els.list.classList.add('iv2-list--fade');
    var minH = els.list.offsetHeight;
    if (opts.fade && minH > 0) els.list.style.minHeight = minH + 'px';

    fetchSchedule().then(function (data) {
      if (seq !== state.reqSeq) return;
      var emptyResult = !(data.ongoing || []).length && !(data.upcoming || []).length && !(data.groups || []).length;
      /* Пустой ВИД → прыжок в ближайший день с сеансами (по счётчикам этого ответа);
         пустой ДЕНЬ, выбранный явно, — карточка «ещё не вышло»/«Следующий лёд». */
      if (opts.kindJump && emptyResult) {
        var nextDay = (data.days || []).filter(function (d) { return d.key !== state.day && (d.count || 0) > 0; })[0];
        if (nextDay) { state.day = nextDay.key; renderChrome(data); load(opts); return; }
      }
      state.data = data;
      applyData(data);
      if (s3On()) screenWrite(key, data);
      els.list.classList.remove('iv2-list--fade');
      els.list.style.minHeight = '';
      writeParams();
      notifyContent(hadCache ? 'cache' : 'net');
    }).catch(function () {
      if (seq !== state.reqSeq) return;
      els.list.classList.remove('iv2-list--fade');
      els.list.style.minHeight = '';
      if (!hadCache) errorHtml();
    });
  }
  function notifyContent(src) {
    try {
      if (global.ClientShell && typeof global.ClientShell.contentShown === 'function') {
        global.ClientShell.contentShown({ src: src, data_ms: Math.round(performance.now()) });
      }
    } catch (e) { /* */ }
  }

  /* ── переход вида/дня ── */
  function switchFilter(patch) {
    if (patch.kind) state.kind = patch.kind;
    if (patch.day) state.day = patch.day;
    haptic('select');
    var data = state.data;
    if (data) {
      /* Пустой вид → прыгаем в ближайший день с сеансами (счётчики дней уже есть). */
      if (patch.kind) {
        var kinds = data.kinds || [];
        var sel = kinds.filter(function (k) { return k.key === state.kind; })[0];
        if (sel && sel.count === 0) {
          var dayWith = (data.days || []).filter(function (d) { return d.count > 0; })[0];
          if (dayWith) state.day = dayWith.key;
        }
        if (data) {
          /* счётчики дней пересчитает сервер — пока перерисуем выбор */
          renderChrome(data);
        }
      }
    }
    load({ fade: !reducedMotion(), keep: true, noCache: false, kindJump: !!patch.kind });
  }

  /* ── липкая шапка ── */
  function bindSticky() {
    var stick = els.stick;
    var mark = els.sub;
    var check = function () {
      var r = mark.getBoundingClientRect();
      stick.classList.toggle('iv2-stick--stuck', r.bottom <= 0);
    };
    global.addEventListener('scroll', check, { passive: true });
    check();
  }

  /* ── tap-переход с фото на арену ── */
  function markHeroForTransition(card) {
    var prev = document.querySelectorAll('[data-vt-hero]');
    for (var i = 0; i < prev.length; i++) prev[i].removeAttribute('data-vt-hero');
    if (!card) return;
    var photo = card.querySelector('.iv2-card__img');
    if (photo) photo.setAttribute('data-vt-hero', '1');
  }

  function bind() {
    els.list.addEventListener('click', function (ev) {
      var t = ev.target;
      var me = t && t.closest ? t.closest('[data-checkin]') : null;
      if (me) { ev.preventDefault(); ev.stopPropagation(); haptic('light'); openCheckin(me); return; }
      var w = t && t.closest ? t.closest('[data-watch]') : null;
      if (w) { ev.preventDefault(); haptic('light'); watchSubscribe(w); return; }
      var gd = t && t.closest ? t.closest('[data-goto-day]') : null;
      if (gd) { ev.preventDefault(); switchFilter({ day: gd.getAttribute('data-goto-day') }); return; }
      var retry = t && t.closest ? t.closest('[data-retry]') : null;
      if (retry) { ev.preventDefault(); load(); return; }
      var compBtn = t && t.closest ? t.closest('[data-company]') : null;
      if (compBtn) {
        ev.preventDefault(); ev.stopPropagation(); haptic('light');
        var cu = compBtn.getAttribute('data-company');
        var tw = window.Telegram && window.Telegram.WebApp;
        if (cu && tw && tw.openTelegramLink) { tw.openTelegramLink(cu); return; }
        if (cu) { window.open(cu, '_blank'); }
        return;
      }
      var a = t && t.closest ? t.closest('a.iv2-card') : null;
      if (a) {
        ev.preventDefault();
        markHeroForTransition(a);
        var href = a.getAttribute('href');
        if (href) navigate(href);
      }
    });
    $('iv2Kinds').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-kind]');
      if (b) switchFilter({ kind: b.getAttribute('data-kind') });
    });
    $('iv2Days').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-day]');
      if (b) switchFilter({ day: b.getAttribute('data-day') });
    });
    $('iv2City').addEventListener('click', function () {
      haptic('select');
      openSheet('iv2CityBg', 'iv2CitySheet');
      loadCities().then(renderCityOpts);
    });
    $('iv2CityList').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-city]');
      if (b) pickCity(Number(b.getAttribute('data-city')));
    });
    $('iv2Search').addEventListener('click', function () {
      haptic('select');
      openSheet('iv2SearchBg', 'iv2SearchSheet');
      renderSearch('');
      setTimeout(function () { try { $('iv2SearchInput').focus(); } catch (e) {} }, 60);
    });
    $('iv2SearchInput').addEventListener('input', function (ev) { renderSearch(ev.target.value); });
    $('iv2SearchList').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-arena-go]');
      if (b) { closeSheets(); navigate('arena?ref=' + b.getAttribute('data-arena-go')); }
    });
    $('iv2Map').addEventListener('click', function () {
      haptic('select');
      global.location.href = '/webapp/ice?map=1' + (state.cityId ? '&city_id=' + state.cityId : '');
    });
    ['iv2CityBg', 'iv2SearchBg'].forEach(function (id) {
      $(id).addEventListener('click', closeSheets);
    });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && state.cityId) load({ keep: true });
    });
  }

  function init() {
    els.list = $('iv2List');
    els.stick = $('iv2Stick');
    els.sub = $('iv2Sub');
    readParams();
    bind();
    bindSticky();
    resolveCity().then(function (cid) {
      if (!cid) { errorHtml(); return; }
      load();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
