/* Фикс-пак B5: экран «Сервис» — заточка и магазины города (поверхность redesign_s4).
   Данные — публичный список /api/public/ice/arenas: ?svc=service (места с заточкой)
   и ?venue_type=shop (магазины). «Открыто сейчас» — window.OpeningHours, как в старом
   каталоге. Тап по строке — страница места arena.html. */
(function () {
  'use strict';
  var global = window;

  var TABS = [
    { key: 'service', label: 'Заточка', noun: ['место', 'места', 'мест'] },
    { key: 'shop', label: 'Магазины', noun: ['магазин', 'магазина', 'магазинов'] },
  ];
  var state = { cityId: null, tab: 'service', cities: null, data: null, reqSeq: 0 };
  var els = {};

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function plural(n, one, few, many) {
    var n10 = n % 10, n100 = n % 100;
    if (n10 === 1 && n100 !== 11) return one;
    if (n10 >= 2 && n10 <= 4 && !(n100 >= 12 && n100 <= 14)) return few;
    return many;
  }
  function initData() {
    var t = global.Telegram && global.Telegram.WebApp;
    return (t && t.initData) || '';
  }
  function headersJson() {
    var h = { 'Content-Type': 'application/json' };
    var init = initData();
    if (init) h['X-Telegram-Init-Data'] = init;
    return h;
  }
  function navigate(path) {
    if (global.ClientShell && typeof global.ClientShell.navigate === 'function') {
      global.ClientShell.navigate(path);
    } else {
      global.location.href = '/webapp/' + path;
    }
  }

  /* ── параметры адреса: ?tab=service|shop, ?city_id=N; также старые intent/venue ── */
  function readParams() {
    var q = new URLSearchParams(location.search);
    var tab = (q.get('tab') || '').toLowerCase();
    if (tab !== 'shop' && (q.get('venue') || '').toLowerCase() === 'shop') tab = 'shop';
    if (tab !== 'service' && tab !== 'shop') {
      tab = (q.get('intent') || q.get('svc') || 'service').toLowerCase() === 'service' ? 'service' : 'shop';
    }
    state.tab = tab;
    var cid = parseInt(q.get('city_id') || '', 10);
    if (cid > 0) state.cityId = cid;
  }
  function writeParams() {
    try {
      var q = new URLSearchParams(location.search);
      q.set('tab', state.tab);
      if (state.cityId) q.set('city_id', String(state.cityId));
      history.replaceState(null, '', location.pathname + '?' + q.toString());
    } catch (e) { /* */ }
  }

  /* ── город: ?city_id → сохранённая сессия → первый из списка (как в ice-v2) ── */
  function resolveCity() {
    if (state.cityId) return Promise.resolve(state.cityId);
    return fetch('/api/webapp/client/session', { headers: headersJson(), cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var cid = d && (d.city_id != null ? d.city_id : (d.city && d.city.id));
        if (cid != null) { state.cityId = Number(cid); return state.cityId; }
        return fetch('/api/public/ice/cities', { cache: 'no-store' })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d2) {
            var list = (d2 && d2.items) || [];
            if (list.length) { state.cityId = Number(list[0].id); return state.cityId; }
            return null;
          });
      })
      .catch(function () { return null; });
  }

  /* ── загрузка списка ── */
  function fetchPlaces() {
    var url = '/api/public/ice/arenas?city_id=' + encodeURIComponent(state.cityId) +
      '&limit=100&when=any';
    if (state.tab === 'shop') url += '&venue_type=shop';
    else url += '&svc=service';
    return fetch(url, { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('places ' + r.status);
        return r.json();
      });
  }

  /* ── «открыто сейчас» — та же модель часов, что у старого каталога ── */
  var OH = global.OpeningHours || null;
  function hoursLine(hours) {
    if (!OH || !hours || typeof hours !== 'object') return '';
    try {
      var now = new Date();
      var wd = (now.getDay() + 6) % 7; /* 0 = пн */
      var mins = now.getHours() * 60 + now.getMinutes();
      var ivs = OH.intervalsForWeekday(hours, wd) || [];
      if (OH.isOpenAt(hours, wd, mins)) {
        var iv = OH.openIntervalAt(hours, wd, mins);
        return iv ? 'Открыто · до ' + iv[1] : 'Открыто сейчас';
      }
      for (var i = 0; i < ivs.length; i++) {
        var ivm = OH.intervalMinutes(ivs[i][0], ivs[i][1]);
        if (ivm && ivm[0] > mins) return 'Откроется в ' + ivs[i][0];
      }
      return 'Закрыто сегодня';
    } catch (e) { return ''; }
  }

  /* ── рендер ── */
  function tabMeta() { return TABS.filter(function (t) { return t.key === state.tab; })[0] || TABS[0]; }

  function kindsHtml() {
    return TABS.map(function (t) {
      return '<button type="button" class="sv2-kind ga-press' + (t.key === state.tab ? ' sv2-kind--on' : '') +
        '" data-tab="' + esc(t.key) + '">' + esc(t.label) + '</button>';
    }).join('');
  }

  function rowHtml(a) {
    var img = a.thumb || a.card || '';
    var bits = [];
    if (a.district) bits.push(a.district);
    if (a.address && a.address !== a.district) bits.push(a.address);
    if (a.distance_km != null) bits.push(Number(a.distance_km).toFixed(1).replace('.', ',') + ' км');
    var hl = hoursLine(a.opening_hours);
    var phone = a.phone ? '<span class="sv2-row__phone">' + esc(a.phone) + '</span>' : '';
    return '<a class="sv2-row ga-press" href="arena?ref=' + esc(a.id) + '" data-id="' + esc(a.id) + '">' +
      (img
        ? '<img class="sv2-row__img" src="' + esc(img) + '" width="56" height="56" loading="lazy" decoding="async" alt="">'
        : '<div class="sv2-row__ph"></div>') +
      '<div class="sv2-row__txt">' +
        '<div class="sv2-row__name">' + esc(a.name || 'Место') + '</div>' +
        (bits.length ? '<div class="sv2-row__sub">' + esc(bits.join(' · ')) + '</div>' : '') +
        (hl ? '<div class="sv2-row__hours' + (/^Открыто/.test(hl) ? ' sv2-row__hours--open' : '') + '">' + esc(hl) + '</div>' : '') +
        phone +
      '</div>' +
      '<svg class="sv2-row__chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>' +
    '</a>';
  }

  function render(data) {
    var items = (data && data.items) || [];
    var meta = tabMeta();
    els.kinds.innerHTML = kindsHtml();
    $('sv2Title').textContent = meta.label;
    var sub = '';
    if (items.length) {
      sub = items.length + ' ' + plural(items.length, meta.noun[0], meta.noun[1], meta.noun[2]);
      var city = (items[0] && items[0].city_name) || '';
      if (city) sub += ' · ' + city;
    } else {
      sub = 'Пока ничего не нашлось';
    }
    els.sub.textContent = sub;
    els.list.innerHTML = items.length
      ? items.map(rowHtml).join('')
      : '<div class="sv2-empty"><div class="sv2-empty__t">Пока пусто</div>' +
        '<div class="sv2-empty__s">В этом городе ещё не отметили места с этой услугой.</div></div>';
  }
  function errorHtml() {
    els.list.innerHTML = '<div class="sv2-empty"><div class="sv2-empty__t">Нет сети</div>' +
      '<div class="sv2-empty__s">Проверьте подключение — покажем список, как только интернет вернётся.</div>' +
      '<button type="button" class="sv2-btn ga-press" data-retry="1">Повторить</button></div>';
  }

  function load() {
    var seq = ++state.reqSeq;
    fetchPlaces().then(function (data) {
      if (seq !== state.reqSeq) return;
      state.data = data;
      render(data);
      writeParams();
    }).catch(function () {
      if (seq !== state.reqSeq) return;
      errorHtml();
    });
  }

  function bind() {
    els.kinds.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-tab]');
      if (b && b.getAttribute('data-tab') !== state.tab) {
        state.tab = b.getAttribute('data-tab');
        load();
      }
    });
    els.list.addEventListener('click', function (ev) {
      var retry = ev.target.closest('[data-retry]');
      if (retry) { ev.preventDefault(); load(); return; }
      var a = ev.target.closest('a.sv2-row');
      if (a) {
        ev.preventDefault();
        navigate(a.getAttribute('href'));
      }
    });
  }

  function init() {
    els.list = $('sv2List');
    els.kinds = $('sv2Kinds');
    els.sub = $('sv2Sub');
    readParams();
    bind();
    resolveCity().then(function (cid) {
      if (!cid) { errorHtml(); return; }
      load();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
