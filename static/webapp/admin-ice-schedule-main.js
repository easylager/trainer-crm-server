(function() {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  var initData = tg ? tg.initData : '';

  var KIND_LABELS = {
    public_skate: 'Массовое',
    hockey_practice: 'ОХМ',
    open_ice: 'Открытый лёд',
    rental: 'Прокат',
    school_group: 'Школа',
    event: 'Событие'
  };
  var DOW = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

  var HINT_WEEKS_BACK = 16;
  var PRIMARY_KINDS = ['public_skate', 'hockey_practice'];

  var LOAD_DAY_LABELS = {
    mon_thu: 'Пн–чт',
    fri: 'Пятница',
    sat: 'Суббота',
    sun: 'Воскресенье'
  };
  var LOAD_LEVELS = ['calm', 'medium', 'busy'];
  var LOAD_LEVEL_LABELS = { calm: 'Свободно', medium: 'Средне', busy: 'Людно' };

  var state = {
    cities: [],
    arenas: [],
    arenaQ: '',
    cityId: null,
    arenaId: null,
    weekStart: null,
    selectedDate: null,
    grid: null,
    editingSessionId: null,
    priceHints: {},
    activeKind: 'public_skate',
    hintsLoading: false,
    globalLoadRules: null,
    arenaLoad: null
  };

  function apiUrl(path) {
    if (path.indexOf('/api') === 0) return path;
    return '/api/webapp' + path;
  }
  function withInit(url) {
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    if (initData) url += sep + 'init_data=' + encodeURIComponent(initData);
    return url;
  }
  function fetchJson(method, path, body) {
    var opts = { method: method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(withInit(apiUrl(path)), opts).then(function(r) {
      return r.json().then(function(data) {
        if (!r.ok) {
          var msg = (data && data.detail) ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : r.statusText;
          throw new Error(msg || 'Ошибка запроса');
        }
        return data;
      });
    });
  }
  function getJson(path) { return fetchJson('GET', path); }
  function sendJson(method, path, body) { return fetchJson(method, path, body); }

  function showToast(text) {
    var el = document.getElementById('toast');
    if (!el) return;
    el.textContent = text;
    el.classList.add('visible');
    clearTimeout(el._t);
    el._t = setTimeout(function() { el.classList.remove('visible'); }, 2500);
  }
  function showAlert(text) {
    if (tg && tg.showAlert) tg.showAlert(text);
    else window.alert(text);
  }

  function mondayIso(d) {
    var day = d instanceof Date ? new Date(d.getTime()) : new Date(d + 'T12:00:00');
    var wd = (day.getDay() + 6) % 7;
    day.setDate(day.getDate() - wd);
    return day.toISOString().slice(0, 10);
  }
  function shiftWeek(iso, days) {
    var d = new Date(iso + 'T12:00:00');
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }
  function todayIso() {
    return new Date().toISOString().slice(0, 10);
  }
  function minorFromInput(el) {
    var raw = (el && el.value || '').trim();
    if (!raw) return null;
    var n = Number(raw.replace(',', '.'));
    if (!isFinite(n)) return null;
    return Math.round(n * 100);
  }
  function minorToDisplay(minor) {
    if (minor == null) return '—';
    return (minor / 100).toFixed(2).replace(/\.00$/, '');
  }
  function minorToInput(minor) {
    if (minor == null) return '';
    return (minor / 100).toFixed(2).replace(/\.00$/, '');
  }
  function hintStorageKey(arenaId) {
    return 'adminIcePriceHints:' + arenaId;
  }
  function readStoredHints(arenaId) {
    try {
      var raw = localStorage.getItem(hintStorageKey(arenaId));
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }
  function writeStoredHints(arenaId, hints) {
    try {
      localStorage.setItem(hintStorageKey(arenaId), JSON.stringify(hints || {}));
    } catch (e) { /* private mode */ }
  }
  function sessionSortKey(s) {
    return String(s.local_date || '') + 'T' + String(s.starts_at_local || '');
  }
  function pricesFromSession(s) {
    if (s.price_adult_minor == null && s.price_child_minor == null && s.price_rental_minor == null) {
      return null;
    }
    return {
      adult: s.price_adult_minor,
      child: s.price_child_minor,
      rental: s.price_rental_minor,
      duration_minutes: null
    };
  }
  function durationFromSession(s) {
    var start = String(s.starts_at_local || '').split(':');
    var end = String(s.ends_at_local || '').split(':');
    if (start.length < 2 || end.length < 2) return null;
    var mins = (Number(end[0]) * 60 + Number(end[1])) - (Number(start[0]) * 60 + Number(start[1]));
    return isFinite(mins) && mins > 0 ? mins : null;
  }
  function mergeHintFromSession(bucket, s) {
    if (!s || s.status === 'cancelled') return;
    var prices = pricesFromSession(s);
    if (!prices) return;
    var dur = durationFromSession(s);
    if (dur != null) prices.duration_minutes = dur;
    var kind = s.kind;
    var key = sessionSortKey(s);
    if (!bucket[kind] || key >= bucket[kind].sortKey) {
      bucket[kind] = { sortKey: key, prices: prices };
    }
  }
  function flattenHintBucket(bucket) {
    var out = {};
    Object.keys(bucket).forEach(function(kind) {
      out[kind] = bucket[kind].prices;
    });
    return out;
  }
  function bucketFromFlatHints(flat) {
    var bucket = {};
    Object.keys(flat || {}).forEach(function(kind) {
      bucket[kind] = { sortKey: '0000-00-00T00:00', prices: flat[kind] };
    });
    return bucket;
  }
  function collectHintsFromGrid(data, bucket) {
    (data.days || []).forEach(function(day) {
      (day.sessions || []).forEach(function(s) {
        mergeHintFromSession(bucket, s);
      });
    });
  }
  function rememberPayloadPrices(kind, payload) {
    if (!state.arenaId || !kind) return;
    var bucket = bucketFromFlatHints(state.priceHints);
    mergeHintFromSession(bucket, {
      kind: kind,
      status: 'active',
      local_date: payload.local_date,
      starts_at_local: payload.starts_at_local,
      ends_at_local: payload.starts_at_local,
      price_adult_minor: payload.price_adult_minor,
      price_child_minor: payload.price_child_minor,
      price_rental_minor: payload.price_rental_minor
    });
    if (payload.duration_minutes) {
      bucket[kind].prices.duration_minutes = payload.duration_minutes;
    }
    state.priceHints = flattenHintBucket(bucket);
    writeStoredHints(state.arenaId, state.priceHints);
  }
  function setPriceInput(id, minor) {
    var el = document.getElementById(id);
    if (!el || minor == null) return;
    el.value = minorToInput(minor);
  }
  function applyComposerPrices(kind) {
    if (kind) state.activeKind = kind;
    var p = state.priceHints[state.activeKind];
    if (!p) {
      updateComposerHint();
      return;
    }
    setPriceInput('priceAdult', p.adult);
    setPriceInput('priceChild', p.child);
    setPriceInput('priceRental', p.rental);
    if (p.duration_minutes != null) {
      document.getElementById('addDuration').value = String(p.duration_minutes);
    }
    var kindSel = document.getElementById('addKind');
    if (kindSel && state.activeKind) kindSel.value = state.activeKind;
    updateComposerHint();
  }
  function updateComposerHint() {
    var el = document.getElementById('composerHint');
    if (!el) return;
    var tz = (state.grid && state.grid.timezone) || 'Europe/Minsk';
    var day = state.selectedDate || '—';
    var p = state.priceHints[state.activeKind];
    var priceNote = '';
    if (p && (p.adult != null || p.child != null || p.rental != null)) {
      priceNote = ' · цены с прошлых слотов (' + (KIND_LABELS[state.activeKind] || state.activeKind) + ')';
    } else if (state.hintsLoading) {
      priceNote = ' · подгружаем цены…';
    } else {
      priceNote = ' · цен в истории нет — введите один раз';
    }
    el.textContent = 'День: ' + day + ' · ' + tz + priceNote;
  }
  function refreshPriceHintsFromHistory() {
    if (!state.arenaId) return Promise.resolve();
    state.hintsLoading = true;
    updateComposerHint();
    var bucket = bucketFromFlatHints(readStoredHints(state.arenaId));
    var baseMonday = mondayIso(new Date());
    var weekStarts = [];
    for (var i = 0; i < HINT_WEEKS_BACK; i++) {
      weekStarts.push(shiftWeek(baseMonday, -7 * i));
    }
    return Promise.all(weekStarts.map(function(ws) {
      return getJson(
        '/admin/arenas/' + state.arenaId + '/ice-sessions?week_start=' +
        encodeURIComponent(ws) + '&include_cancelled=false'
      );
    })).then(function(grids) {
      grids.forEach(function(g) { collectHintsFromGrid(g, bucket); });
      state.priceHints = flattenHintBucket(bucket);
      writeStoredHints(state.arenaId, state.priceHints);
      applyComposerPrices(state.activeKind);
    }).catch(function() {
      /* сеть — остаёмся на localStorage + текущей неделе */
    }).then(function() {
      state.hintsLoading = false;
      updateComposerHint();
    });
  }
  function mergeGridIntoPriceHints(data) {
    var bucket = bucketFromFlatHints(state.priceHints);
    collectHintsFromGrid(data, bucket);
    state.priceHints = flattenHintBucket(bucket);
    if (state.arenaId) writeStoredHints(state.arenaId, state.priceHints);
  }
  function badgeClass(kind) {
    if (kind === 'public_skate') return 'badge-mk';
    if (kind === 'hockey_practice') return 'badge-ohm';
    return 'badge-other';
  }
  function queryParams() {
    var q = {};
    (window.location.search || '').replace(/^\?/, '').split('&').forEach(function(pair) {
      if (!pair) return;
      var p = pair.split('=');
      q[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || '');
    });
    return q;
  }

  function activeCurrencyCode() {
    if (state.grid && state.grid.currency_code) return state.grid.currency_code;
    var city = state.cities.filter(function(c) { return c.id === state.cityId; })[0];
    if (city && city.currency_code) return city.currency_code;
    return 'BYN';
  }

  function updatePricePlaceholders() {
    var cur = activeCurrencyCode();
    [
      ['priceAdult', 'Взрослый'],
      ['priceChild', 'Детский'],
      ['priceRental', 'Прокат'],
      ['editPriceAdult', 'Взрослый'],
      ['editPriceChild', 'Детский'],
      ['editPriceRental', 'Прокат']
    ].forEach(function(pair) {
      var el = document.getElementById(pair[0]);
      if (el) el.placeholder = pair[1] + ', ' + cur;
    });
  }

  function filteredArenas() {
    var q = (state.arenaQ || '').trim().toLowerCase();
    return state.arenas.filter(function(a) {
      if (!q) return true;
      return (a.name || '').toLowerCase().indexOf(q) >= 0 || (a.address || '').toLowerCase().indexOf(q) >= 0;
    });
  }

  function fillCitySelect() {
    var sel = document.getElementById('citySelect');
    sel.innerHTML = '';
    state.cities.forEach(function(c) {
      var opt = document.createElement('option');
      opt.value = String(c.id);
      opt.textContent = c.name || ('#' + c.id);
      sel.appendChild(opt);
    });
    if (state.cityId) sel.value = String(state.cityId);
  }

  function fillArenaSelect() {
    var sel = document.getElementById('arenaSelect');
    var list = filteredArenas();
    sel.innerHTML = '';
    if (!list.length) {
      var empty = document.createElement('option');
      empty.value = '';
      empty.textContent = state.arenas.length ? 'Нет по фильтру' : 'Нет арен';
      sel.appendChild(empty);
      state.arenaId = null;
      return;
    }
    list.forEach(function(a) {
      var opt = document.createElement('option');
      opt.value = String(a.id);
      opt.textContent = (a.name || 'Арена') + (a.is_active === false ? ' (неакт.)' : '');
      sel.appendChild(opt);
    });
    if (state.arenaId && list.some(function(a) { return a.id === state.arenaId; })) {
      sel.value = String(state.arenaId);
    } else {
      state.arenaId = list[0].id;
      sel.value = String(state.arenaId);
    }
  }

  function updateSubtitle() {
    var el = document.getElementById('arenaSubtitle');
    var city = state.cities.filter(function(c) { return c.id === state.cityId; })[0];
    var arena = state.arenas.filter(function(a) { return a.id === state.arenaId; })[0];
    if (!city || !arena) {
      el.textContent = 'Выберите город и арену';
      return;
    }
    el.textContent = (city.name || '') + ' · ' + (arena.name || '') + ' · ' + activeCurrencyCode();
    updatePricePlaceholders();
  }

  function loadCities() {
    return getJson('/admin/cities').then(function(data) {
      state.cities = (data && data.items) || [];
      if (!state.cityId && state.cities.length) state.cityId = state.cities[0].id;
      if (state.cityId && !state.cities.some(function(c) { return c.id === state.cityId; })) {
        state.cityId = state.cities[0] ? state.cities[0].id : null;
      }
      fillCitySelect();
      return loadArenas();
    }).catch(function(err) { showAlert(err.message || String(err)); });
  }

  function loadArenas() {
    if (!state.cityId) return Promise.resolve();
    var path = '/admin/arenas?city_id=' + encodeURIComponent(state.cityId) + '&include_inactive=true';
    return getJson(path).then(function(data) {
      state.arenas = (data && data.items) || [];
      fillArenaSelect();
      updateSubtitle();
      if (state.arenaId) return loadWeek();
      hideSchedule();
      return null;
    }).catch(function(err) { showAlert(err.message || String(err)); });
  }

  function hideSchedule() {
    document.getElementById('schedulePanel').hidden = true;
    document.getElementById('composer').hidden = true;
  }

  function showSchedule() {
    document.getElementById('schedulePanel').hidden = false;
    document.getElementById('composer').hidden = false;
  }

  function loadWeek() {
    if (!state.arenaId) {
      hideSchedule();
      return Promise.resolve();
    }
    if (!state.weekStart) state.weekStart = mondayIso(new Date());
    return getJson(
      '/admin/arenas/' + state.arenaId + '/ice-sessions?week_start=' +
      encodeURIComponent(state.weekStart) + '&include_cancelled=true'
    ).then(function(data) {
      state.grid = data;
      state.weekStart = data.week_start;
      if (!state.selectedDate || !data.days.some(function(d) { return d.local_date === state.selectedDate; })) {
        var today = todayIso();
        var inWeek = data.days.some(function(d) { return d.local_date === today; });
        state.selectedDate = inWeek ? today : data.days[0].local_date;
      }
      mergeGridIntoPriceHints(data);
      showSchedule();
      renderWeek();
      updateSubtitle();
      applyComposerPrices(state.activeKind);
      refreshPriceHintsFromHistory();
    }).catch(function(err) { showAlert(err.message || String(err)); });
  }

  function sessionsForSelectedDay() {
    if (!state.grid || !state.selectedDate) return [];
    var day = state.grid.days.filter(function(d) { return d.local_date === state.selectedDate; })[0];
    return (day && day.sessions) || [];
  }

  function renderWeek() {
    var data = state.grid;
    document.getElementById('weekLabel').textContent =
      'Неделя с ' + data.week_start + ' (' + (data.timezone || '') + ')';

    var tabs = document.getElementById('dayTabs');
    tabs.innerHTML = '';
    (data.days || []).forEach(function(day) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'day-tab' + (day.local_date === state.selectedDate ? ' on' : '');
      var cnt = (day.sessions || []).filter(function(s) { return s.status !== 'cancelled'; }).length;
      btn.innerHTML =
        (DOW[day.weekday] || '') +
        '<strong>' + day.local_date.slice(8) + '</strong>' +
        '<span class="cnt">' + cnt + ' сл.</span>';
      btn.addEventListener('click', function() {
        state.selectedDate = day.local_date;
        renderWeek();
        updateComposerHint();
      });
      tabs.appendChild(btn);
    });

    var list = document.getElementById('sessionList');
    var sessions = sessionsForSelectedDay();
    if (!sessions.length) {
      list.innerHTML = '<div class="empty-day">На этот день слотов нет. Добавьте массовое или ОХМ внизу.</div>';
      return;
    }
    list.innerHTML = '';
    sessions.forEach(function(s) {
      var card = document.createElement('div');
      card.className = 'session-card' + (s.status === 'cancelled' ? ' cancelled' : '');
      var prices = [];
      if (s.price_adult_minor != null) prices.push('взр. ' + minorToDisplay(s.price_adult_minor));
      if (s.price_child_minor != null) prices.push('дет. ' + minorToDisplay(s.price_child_minor));
      if (s.price_rental_minor != null) prices.push('прокат ' + minorToDisplay(s.price_rental_minor));
      var meta = prices.join(' · ');
      if (s.recurrence_key) meta += (meta ? ' · ' : '') + 'повтор';
      if (s.status === 'cancelled') meta = (meta ? meta + ' · ' : '') + 'отменён';
      card.innerHTML =
        '<div>' +
          '<div class="session-time">' +
            '<span class="badge ' + badgeClass(s.kind) + '">' + (KIND_LABELS[s.kind] || s.kind) + '</span>' +
            escapeHtml(s.starts_at_local) + '–' + escapeHtml(s.ends_at_local) +
          '</div>' +
          '<div class="session-meta">' + escapeHtml(meta || 'без цен') + '</div>' +
        '</div>' +
        '<div class="session-actions">' +
          '<button type="button" data-act="edit">Изменить</button>' +
          '<button type="button" class="danger" data-act="del">Удалить</button>' +
        '</div>';
      card.querySelector('[data-act="del"]').addEventListener('click', function() {
        var ok = window.confirm('Удалить сеанс ' + s.starts_at_local + '?');
        if (!ok) return;
        sendJson('DELETE', '/admin/ice-sessions/' + s.id, {})
          .then(function() { showToast('Удалено'); return loadWeek(); })
          .catch(function(err) { showAlert(err.message || String(err)); });
      });
      card.querySelector('[data-act="edit"]').addEventListener('click', function() {
        openEditSheet(s);
      });
      list.appendChild(card);
    });
  }

  function escapeHtml(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function buildCreatePayload(kind) {
    var duration = Number(document.getElementById('addDuration').value || 45);
    if (kind === 'hockey_practice' && duration === 45) duration = 60;
    return {
      local_date: state.selectedDate,
      starts_at_local: document.getElementById('addTime').value || '11:00',
      duration_minutes: duration,
      kind: kind,
      price_adult_minor: minorFromInput(document.getElementById('priceAdult')),
      price_child_minor: minorFromInput(document.getElementById('priceChild')),
      price_rental_minor: minorFromInput(document.getElementById('priceRental')),
      repeat_weekly: !!document.getElementById('repeatWeekly').checked
    };
  }

  function createSession(kind) {
    if (!state.arenaId || !state.selectedDate) {
      showAlert('Выберите арену и день');
      return;
    }
    var payload = buildCreatePayload(kind);
    rememberPayloadPrices(kind, payload);
    sendJson('POST', '/admin/arenas/' + state.arenaId + '/ice-sessions', payload)
      .then(function() {
        showToast((KIND_LABELS[kind] || kind) + ' добавлено');
        return loadWeek();
      })
      .catch(function(err) { showAlert(err.message || String(err)); });
  }

  function fillEditKindSelect(sel, value) {
    sel.innerHTML = '';
    Object.keys(KIND_LABELS).forEach(function(k) {
      var opt = document.createElement('option');
      opt.value = k;
      opt.textContent = KIND_LABELS[k];
      sel.appendChild(opt);
    });
    sel.value = value || 'public_skate';
  }

  function openEditSheet(session) {
    state.editingSessionId = session.id;
    document.getElementById('editDate').value = session.local_date;
    document.getElementById('editTime').value = session.starts_at_local;
    var start = session.starts_at_local.split(':');
    var end = session.ends_at_local.split(':');
    var dur = 45;
    if (start.length >= 2 && end.length >= 2) {
      dur = (Number(end[0]) * 60 + Number(end[1])) - (Number(start[0]) * 60 + Number(start[1]));
    }
    document.getElementById('editDuration').value = dur;
    fillEditKindSelect(document.getElementById('editKind'), session.kind);
    document.getElementById('editPriceAdult').value =
      session.price_adult_minor != null ? (session.price_adult_minor / 100) : '';
    document.getElementById('editPriceChild').value =
      session.price_child_minor != null ? (session.price_child_minor / 100) : '';
    document.getElementById('editPriceRental').value =
      session.price_rental_minor != null ? (session.price_rental_minor / 100) : '';
    var sheet = document.getElementById('editSheet');
    sheet.hidden = false;
    sheet.classList.add('open');
  }

  function closeEditSheet() {
    state.editingSessionId = null;
    var sheet = document.getElementById('editSheet');
    sheet.classList.remove('open');
    sheet.hidden = true;
  }

  function saveEdit() {
    if (!state.editingSessionId) return;
    var payload = {
      local_date: document.getElementById('editDate').value,
      starts_at_local: document.getElementById('editTime').value,
      duration_minutes: Number(document.getElementById('editDuration').value || 45),
      kind: document.getElementById('editKind').value,
      price_adult_minor: minorFromInput(document.getElementById('editPriceAdult')),
      price_child_minor: minorFromInput(document.getElementById('editPriceChild')),
      price_rental_minor: minorFromInput(document.getElementById('editPriceRental'))
    };
    sendJson('PATCH', '/admin/ice-sessions/' + state.editingSessionId, payload)
      .then(function() {
        closeEditSheet();
        showToast('Сохранено');
        return loadWeek();
      })
      .catch(function(err) { showAlert(err.message || String(err)); });
  }

  function levelBtnClass(level) {
    return 'lvl-btn on-' + level;
  }

  function renderLoadBand(band, onPick) {
    var row = document.createElement('div');
    row.className = 'load-band';
    var time = document.createElement('span');
    time.className = 'time';
    time.textContent = band.starts_from + '–' + (band.starts_before || 'конец');
    row.appendChild(time);
    LOAD_LEVELS.forEach(function(lv) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'lvl-btn' + (band.level === lv ? ' on-' + lv : '');
      b.textContent = LOAD_LEVEL_LABELS[lv];
      b.addEventListener('click', function() { onPick(lv); });
      row.appendChild(b);
    });
    return row;
  }

  function renderGlobalLoadRules(data) {
    var root = document.getElementById('loadRulesGlobal');
    if (!root) return;
    root.innerHTML = '';
    var rules = (data && data.rules) || {};
    Object.keys(LOAD_DAY_LABELS).forEach(function(dg) {
      var block = document.createElement('div');
      var title = document.createElement('div');
      title.className = 'panel-title';
      title.textContent = LOAD_DAY_LABELS[dg];
      block.appendChild(title);
      (rules[dg] || []).forEach(function(band) {
        block.appendChild(renderLoadBand(band, function(level) {
          var next = (rules[dg] || []).map(function(b) {
            if (b.id === band.id) return Object.assign({}, b, { level: level });
            return b;
          });
          sendJson('PUT', '/admin/session-load/global', {
            day_group: dg,
            intervals: next.map(function(b) {
              return {
                starts_from: b.starts_from,
                starts_before: b.starts_before,
                level: b.level
              };
            })
          }).then(function(res) {
            state.globalLoadRules = res;
            renderGlobalLoadRules(res);
            showToast('Общая шкала сохранена');
          }).catch(function(err) { showAlert(err.message || String(err)); });
        }));
      });
      root.appendChild(block);
    });
  }

  function loadGlobalLoadRules() {
    return getJson('/admin/session-load/global').then(function(data) {
      state.globalLoadRules = data;
      renderGlobalLoadRules(data);
    });
  }

  function renderArenaLoad(data) {
    var wrap = document.getElementById('loadRulesArena');
    if (!wrap) return;
    if (!state.arenaId) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    state.arenaLoad = data;
    var sel = document.getElementById('arenaLoadCharacter');
    if (sel) sel.value = data.load_character || 'steady';
    var badge = document.getElementById('arenaLoadBadge');
    if (badge) {
      badge.textContent = data.has_custom_rules ? 'Своя шкала для этой арены' : 'Как у всех (общие правила)';
    }
    var bands = document.getElementById('loadRulesArenaBands');
    if (!bands) return;
    bands.innerHTML = '';
    if (!data.has_custom_rules) return;
    var byDay = {};
    (data.rules || []).forEach(function(r) {
      if (!byDay[r.day_group]) byDay[r.day_group] = [];
      byDay[r.day_group].push(r);
    });
    Object.keys(LOAD_DAY_LABELS).forEach(function(dg) {
      if (!byDay[dg] || !byDay[dg].length) return;
      var title = document.createElement('div');
      title.className = 'panel-title';
      title.textContent = LOAD_DAY_LABELS[dg];
      bands.appendChild(title);
      byDay[dg].forEach(function(band) {
        bands.appendChild(renderLoadBand(band, function(level) {
          var next = byDay[dg].map(function(b) {
            if (b.id === band.id) return Object.assign({}, b, { level: level });
            return b;
          });
          sendJson('PUT', '/admin/arenas/' + state.arenaId + '/session-load/rules', {
            day_group: dg,
            intervals: next.map(function(b) {
              return {
                starts_from: b.starts_from,
                starts_before: b.starts_before,
                level: b.level
              };
            })
          }).then(function(res) {
            renderArenaLoad(res);
            showToast('Шкала арены сохранена');
          }).catch(function(err) { showAlert(err.message || String(err)); });
        }));
      });
    });
  }

  function loadArenaLoad() {
    if (!state.arenaId) {
      renderArenaLoad({ load_character: 'steady', has_custom_rules: false, rules: [] });
      return Promise.resolve();
    }
    return getJson('/admin/arenas/' + state.arenaId + '/session-load').then(renderArenaLoad);
  }

  document.getElementById('arenaLoadCharacter').addEventListener('change', function() {
    if (!state.arenaId) return;
    sendJson('PUT', '/admin/arenas/' + state.arenaId + '/session-load/character', {
      load_character: this.value
    }).then(function(res) {
      renderArenaLoad(res);
      showToast('Характер катка сохранён');
    }).catch(function(err) { showAlert(err.message || String(err)); });
  });
  document.getElementById('btnResetArenaLoad').addEventListener('click', function() {
    if (!state.arenaId) return;
    sendJson('DELETE', '/admin/arenas/' + state.arenaId + '/session-load/rules')
      .then(function(res) {
        renderArenaLoad(res);
        showToast('Своя шкала сброшена');
      })
      .catch(function(err) { showAlert(err.message || String(err)); });
  });

  document.getElementById('citySelect').addEventListener('change', function() {
    state.cityId = Number(this.value) || null;
    state.arenaId = null;
    state.grid = null;
    updateSubtitle();
    loadArenas();
  });
  document.getElementById('arenaSelect').addEventListener('change', function() {
    state.arenaId = Number(this.value) || null;
    state.grid = null;
    state.priceHints = state.arenaId ? readStoredHints(state.arenaId) : {};
    state.activeKind = 'public_skate';
    updateSubtitle();
    loadWeek();
    loadArenaLoad();
  });
  document.getElementById('arenaSearch').addEventListener('input', function() {
    state.arenaQ = this.value;
    fillArenaSelect();
    updateSubtitle();
    if (state.arenaId) loadWeek();
  });
  document.getElementById('btnPrevWeek').addEventListener('click', function() {
    state.weekStart = shiftWeek(state.weekStart, -7);
    loadWeek();
  });
  document.getElementById('btnNextWeek').addEventListener('click', function() {
    state.weekStart = shiftWeek(state.weekStart, 7);
    loadWeek();
  });
  document.getElementById('btnToday').addEventListener('click', function() {
    state.weekStart = mondayIso(new Date());
    state.selectedDate = todayIso();
    loadWeek();
  });
  document.getElementById('btnCopyWeek').addEventListener('click', function() {
    if (!state.arenaId || !state.weekStart) return;
    sendJson('POST', '/admin/arenas/' + state.arenaId + '/ice-sessions/copy-week', { from_week_start: state.weekStart })
      .then(function(res) {
        showToast('Скопировано слотов: ' + (res.copied || 0));
        state.weekStart = shiftWeek(state.weekStart, 7);
        return loadWeek();
      })
      .catch(function(err) { showAlert(err.message || String(err)); });
  });
  document.getElementById('btnAddMk').addEventListener('click', function() {
    applyComposerPrices('public_skate');
    createSession('public_skate');
  });
  document.getElementById('btnAddOhm').addEventListener('click', function() {
    applyComposerPrices('hockey_practice');
    createSession('hockey_practice');
  });
  document.getElementById('btnAddCustom').addEventListener('click', function() {
    var kind = document.getElementById('addKind').value || 'public_skate';
    applyComposerPrices(kind);
    createSession(kind);
  });
  document.getElementById('addKind').addEventListener('change', function() {
    applyComposerPrices(this.value || 'public_skate');
  });
  document.getElementById('editCancel').addEventListener('click', closeEditSheet);
  document.getElementById('editSave').addEventListener('click', saveEdit);
  document.getElementById('editSheet').addEventListener('click', function(e) {
    if (e.target === document.getElementById('editSheet')) closeEditSheet();
  });

  var qp = queryParams();
  if (qp.city_id) state.cityId = Number(qp.city_id) || null;
  if (qp.arena_id) state.arenaId = Number(qp.arena_id) || null;
  state.weekStart = mondayIso(new Date());

  loadCities().then(function() {
    loadGlobalLoadRules();
    if (state.arenaId) {
      state.priceHints = readStoredHints(state.arenaId);
      var sel = document.getElementById('arenaSelect');
      if (sel) sel.value = String(state.arenaId);
      loadWeek();
    }
  });
})();
