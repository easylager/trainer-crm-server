/**
 * Mini App: зимние катки и коробки внутри фасета «Зимой» (TASK-343, волна 2).
 * Блок встаёт над обычной лентой закрытого сезона; Немига (закреп) идёт первой.
 * Статусы и отметки — те же, что на сайте: /api/public/winter/… и /api/webapp/winter/….
 * Логика подписей и сортировки — static/shared/winter-model.js.
 */
(function (global) {
  'use strict';
  var W = global.GlideWinter;
  if (!W) return;

  var ctx = null;
  var host = null;
  var sheet = null;
  var cache = { key: '', data: null };
  var f = { flooded: false, kind: '', district: '', origin: null };
  var districtsOpen = false;
  var geoNote = '';
  var seq = 0;
  var pending = '';
  var report = W.reportInit();
  var idem = W.newIdemKey();
  var current = null;
  var opener = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function headers(json) {
    var h = ctx && ctx.authHeaders ? ctx.authHeaders() : {};
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }
  function openExternal(url) {
    var tg = global.Telegram && global.Telegram.WebApp;
    try {
      if (/^https:\/\/t\.me\//.test(url) && tg && tg.openTelegramLink) return tg.openTelegramLink(url);
      if (tg && tg.openLink) return tg.openLink(url, { try_instant_view: false });
    } catch (e) { /* ниже */ }
    global.open(url, '_blank', 'noopener,noreferrer');
  }

  function remove() {
    if (host && host.parentNode) host.parentNode.removeChild(host);
    host = null;
  }
  function ensureHost() {
    if (host && host.isConnected) return host;
    var list = document.getElementById('iceList');
    if (!list || !list.parentNode) return null;
    host = document.createElement('div');
    host.id = 'iceWinter';
    host.className = 'w-app';
    list.parentNode.insertBefore(host, list);
    host.addEventListener('click', onClick);
    return host;
  }

  /* Каток без фото: тот же рисунок, что на сайте (слева тип, не пустая плашка). */
  var MOTIF =
    '<svg class="w-thumb__motif" viewBox="0 0 230 120" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false" ' +
    'fill="none" stroke="rgba(255,255,255,.28)" stroke-width="2">' +
    '<rect x="-30" y="14" width="290" height="92" rx="40"/><line x1="115" y1="14" x2="115" y2="106"/>' +
    '<circle cx="115" cy="60" r="20"/></svg>';

  function pill(p) {
    var v = W.stateView(p);
    return '<span class="w-pill w-pill--' + v.tone + '">' + (ICON[v.tone] || '') + esc(v.label) + '</span>';
  }

  function card(p) {
    var tags = W.liveTags(p, new Date()).map(function (t) { return '<span class="w-tag">' + esc(t) + '</span>'; }).join('');
    var checked = W.checkedLine(p, new Date());
    var dispute = W.disputeNote(p);
    var dist = W.distanceLabel(p.distance_km);
    var photo = p.photos && p.photos[0] && p.photos[0].variants && (p.photos[0].variants.card || p.photos[0].variants.thumb);
    var thumb = '<span class="w-thumb w-thumb--type">' + MOTIF + '<span class="w-thumb__glyph">' + esc(W.kindLabel(p.kind, true)) + '</span></span>';
    if (photo && /^(https?:)?\//.test(photo)) {
      thumb = '<span class="w-thumb"><img src="' + esc(photo) + '" alt="" loading="lazy"><span class="w-thumb__label">' +
        p.photos.length + ' фото</span></span>';
    } else if (p.static_map_url && /^(https?:)?\//.test(p.static_map_url)) {
      thumb = '<span class="w-thumb"><img src="' + esc(p.static_map_url) + '" alt="" loading="lazy"></span>';
    }
    return '<a class="w-card" href="#" data-w-open="' + p.id + '" aria-label="' + esc(p.name + ', ' + W.stateView(p).label) + '">' + thumb +
      '<span class="w-card__body"><span class="w-card__top"><span>' + esc(W.kindLabel(p.kind, true)) + '</span><span>' + esc(dist) + '</span></span>' +
      '<span class="w-card__name">' + esc(W.cardTitle(p)) + '</span><span class="w-card__tags">' + pill(p) + tags + '</span>' +
      '<span class="w-card__meta">' + esc(W.cardMeta(p)) + '</span>' +
      (checked ? '<span class="w-card__meta">' + esc(checked) + '</span>' : '') +
      (dispute ? '<span class="w-card__meta">' + esc(dispute) + '</span>' : '') + '</span></a>';
  }

  var ICON = {
    wait: '<svg class="w-pill__i" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    ok: '<svg class="w-pill__i" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  };
  var BELL = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 16V11a6 6 0 0112 0v5l1.5 2h-15z"/><path d="M10 21h4"/></svg>';

  function segHtml(active) {
    function b(v, label) {
      return '<button type="button" data-w-view="' + v + '" aria-pressed="' + (active === v) + '">' + label + '</button>';
    }
    return '<div class="w-seg" role="group" aria-label="Вид">' + b('list', 'Список') + b('map', 'Карта') + '</div>';
  }

  function chipsHtml(data, points, origin, withDistricts) {
    var districts = withDistricts ? W.districtList(points) : [];
    return '<div class="w-chips" role="group" aria-label="Фильтры">' +
      '<button type="button" class="w-chip" data-w-f="near" aria-pressed="' + !!origin + '">Ближе ко мне</button>' +
      '<button type="button" class="w-chip" data-w-f="flooded" aria-pressed="' + f.flooded + '">Залиты · ' + (data.flooded || 0) + '</button>' +
      '<button type="button" class="w-chip" data-w-f="rink" aria-pressed="' + (f.kind === 'rink') + '">Катки</button>' +
      '<button type="button" class="w-chip" data-w-f="hockey_box" aria-pressed="' + (f.kind === 'hockey_box') + '">Коробки</button>' +
      (districts.length
        ? '<button type="button" class="w-chip" data-w-f="district" aria-pressed="' + (districtsOpen || !!f.district) + '">Район</button>'
        : '') + '</div>' +
      (districts.length && districtsOpen
        ? '<div class="w-chips" role="group" aria-label="Район">' + districts.map(function (d) {
            return '<button type="button" class="w-chip w-chip--sub" data-w-d="' + esc(d.name) + '" aria-pressed="' +
              (f.district === d.name) + '">' + esc(d.name) + ' · ' + d.count + '</button>';
          }).join('') + '</div>'
        : '');
  }

  function render() {
    var h = ensureHost();
    var data = cache.data;
    if (!h || !data) return;
    var points = data.items || [];
    var origin = f.origin || ctx.origin;
    var list = W.applyFilters(points, { flooded: f.flooded, kind: f.kind, district: f.district, origin: origin });
    var head = W.headline(points.length, data.flooded || 0);
    var bell = data.bell_near_link;
    /* Колокольчик — после списка: карточки должны быть над сгибом. */
    var bellHtml = bell
      ? '<div class="w-bell"><span class="w-bell__text"><span class="w-bell__title">Лёд рядом с вами</span>' +
        '<span class="w-bell__hint">Напишем, когда зальют лёд в 2 км от вас</span></span>' +
        '<button type="button" class="w-btn w-btn--tg" data-w-near>' + BELL + 'Подписаться</button></div>'
      : '';
    var lead = head.title
      ? '<b>' + esc(head.title) + '.</b> ' + esc(head.hint)
      : esc(W.summaryLine(points.length, data.flooded || 0));
    h.innerHTML =
      '<div class="w-page" style="padding:0 0 12px">' +
      '<h2 class="w-title">' + esc(data.where ? 'Зимой в ' + data.where : 'Зимой') + '</h2>' +
      '<p class="w-lead">' + lead + '</p>' +
      segHtml('list') + chipsHtml(data, points, origin, true) +
      '<p class="w-note">' + esc(geoNote || W.sortNote({ flooded: f.flooded, kind: f.kind, district: f.district, origin: origin })) + '</p>' +
      (list.length ? '<ul class="w-list" style="padding:0;margin:0">' + list.map(function (p) { return '<li>' + card(p) + '</li>'; }).join('') + '</ul>'
        : '<p class="w-empty">' + esc(W.emptyFilterText({ flooded: f.flooded })) + '</p>') +
      bellHtml +
      '</div>';
    if (ctx.onData) ctx.onData();
  }

  function status(text, retry) {
    var h = ensureHost();
    if (!h) return;
    h.innerHTML = '<div class="w-page" style="padding:0 0 12px"><p class="w-empty">' + esc(text) + '</p>' +
      (retry ? '<button type="button" class="w-btn w-btn--soft w-btn--wide" data-w-retry>Повторить</button>' : '') + '</div>';
  }

  function load() {
    var key = ctx.cityId + '|' + (ctx.near || '');
    if (cache.key === key && cache.data) return render();
    if (pending === key) return;
    pending = key;
    /* Другой город: прошлый список не показываем, пока не пришёл новый. */
    cache = { key: '', data: null };
    status('Загружаем зимние точки…');
    var my = ++seq;
    var url = '/api/public/winter/cities/' + encodeURIComponent(ctx.cityId) + '/points';
    if (ctx.near) {
      var ll = String(ctx.near).split(',');
      if (ll.length === 2) url += '?lat=' + encodeURIComponent(ll[0]) + '&lon=' + encodeURIComponent(ll[1]);
    }
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (my !== seq) return;
        pending = '';
        if (!d) return status('Не получилось загрузить зимние точки.', true);
        cache = { key: key, data: d };
        render();
      })
      .catch(function () { if (my === seq) { pending = ''; status('Не получилось загрузить зимние точки.', true); } });
  }

  /** ctx: {season, cityId, near, facet, authHeaders, openArena(ref)}. Возвращает true, если блок занят. */
  function sync(c) {
    ctx = c;
    ctx.origin = null;
    if (c.near) {
      var ll = String(c.near).split(',');
      if (ll.length === 2 && isFinite(+ll[0]) && isFinite(+ll[1])) ctx.origin = { lat: +ll[0], lon: +ll[1] };
    }
    var wp = c.facet && c.facet.winter_points;
    if (c.season !== 'winter' || !(wp > 0) || !c.cityId) {
      seq++;
      pending = '';
      remove();
      hideMap();
      return false;
    }
    load();
    return true;
  }

  /* «Ближе ко мне»: геолокацию просим только по тапу; второй тап выключает. */
  function toggleNear() {
    if (f.origin || ctx.origin) {
      f.origin = null;
      ctx.origin = null;
      geoNote = '';
      return render();
    }
    if (!global.navigator || !global.navigator.geolocation) {
      geoNote = 'Геолокация недоступна — показываем по районам.';
      return render();
    }
    geoNote = 'Ищем, где вы…';
    render();
    global.navigator.geolocation.getCurrentPosition(
      function (pos) {
        f.origin = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        geoNote = '';
        render();
      },
      function () {
        geoNote = 'Геолокация выключена — показываем по районам.';
        render();
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }
    );
  }

  /* ───── карта: те же точки и пины, что на сайте ───── */
  var GLYPH = { ok: '✓', wait: '•', quiet: '–', dispute: '!' };
  var mapState = { sec: null, host: null, ym: null, map: null, clusterer: null, loading: null };

  function filtered() {
    var data = cache.data;
    if (!data) return [];
    return W.applyFilters(data.items || [], { flooded: f.flooded, kind: f.kind, district: f.district, origin: f.origin || ctx.origin });
  }

  /** Есть ли что рисовать на карте зимой: тогда общая карта каталога (только закрытые арены) не нужна. */
  function mapWanted() {
    return !!(cache.data && W.mapPoints(cache.data.items || []).length);
  }

  function mapHost(sec) {
    if (mapState.host && mapState.host.isConnected) return mapState.host;
    var h = document.createElement('div');
    h.id = 'iceWinterMap';
    h.className = 'w-app w-fullmap';
    h.innerHTML = '<div class="w-map__canvas"></div><p class="w-map__msg" hidden></p><div class="w-fullmap__bar"></div><div class="w-mapcard" hidden></div>' +
      '<p class="w-fullmap__attrib">© Яндекс · <a href="https://yandex.ru/legal/maps_termsofuse/" target="_blank" rel="noopener">Условия</a></p>';
    sec.appendChild(h);
    h.addEventListener('click', onClick);
    mapState.host = h;
    mapState.map = null;
    mapState.clusterer = null;
    return h;
  }

  function mapSay(text) {
    var m = mapState.host && mapState.host.querySelector('.w-map__msg');
    if (!m) return;
    m.textContent = text;
    m.hidden = !text;
  }

  function mapCard(p) {
    var card = mapState.host.querySelector('.w-mapcard');
    var v = W.stateView(p);
    var note = W.checkedLine(p, new Date());
    card.hidden = false;
    card.innerHTML = '<a class="w-mapcard__name" href="#" data-w-open="' + p.id + '">' + esc(W.cardTitle(p)) + '</a>' +
      '<span class="w-card__tags"><span class="w-pill w-pill--' + v.tone + '">' + esc(v.label) + '</span></span>' +
      (note ? '<span class="w-card__meta">' + esc(note) + '</span>' : '') +
      '<a class="w-btn w-btn--soft" href="#" data-w-open="' + p.id + '">Открыть</a>';
  }

  function drawMap() {
    var ym = mapState.ym;
    if (!ym || !mapState.host) return;
    var pts = W.mapPoints(filtered());
    var canvas = mapState.host.querySelector('.w-map__canvas');
    if (!mapState.map) {
      var first = pts[0] || { lat: 53.9, lon: 27.56 };
      mapState.map = new ym.Map(canvas, { center: [first.lat, first.lon], zoom: 11, controls: ['zoomControl'] });
      mapState.map.events.add('click', function () { mapState.host.querySelector('.w-mapcard').hidden = true; });
    }
    var map = mapState.map;
    if (mapState.clusterer) map.geoObjects.remove(mapState.clusterer);
    var Layout = ym.templateLayoutFactory.createClass('<div class="w-pin w-pin--$[properties.pin]"><i>$[properties.glyph]</i></div>');
    var cl = new ym.Clusterer({ preset: 'islands#invertedDarkBlueClusterIcons', groupByCoordinates: false, hasBalloon: false });
    cl.add(pts.map(function (p) {
      var v = W.stateView(p);
      var pm = new ym.Placemark([p.lat, p.lon], { pin: v.pin, glyph: GLYPH[v.pin] || '', hintContent: p.name },
        { iconLayout: Layout, iconShape: { type: 'Circle', coordinates: [0, -6], radius: 22 }, hasBalloon: false });
      pm.events.add('click', function () { mapCard(p); });
      return pm;
    }));
    map.geoObjects.add(cl);
    mapState.clusterer = cl;
    if (pts.length) {
      var b = cl.getBounds();
      if (b) map.setBounds(b, { checkZoomRange: true, zoomMargin: 40 });
    }
    mapSay(pts.length ? '' : 'На карте пока нечего показать: точный адрес известен не у всех точек.');
    mapState.host.querySelector('.w-mapcard').hidden = true;
    map.container.fitToViewport();
  }

  /** Рисует зимнюю карту в секции карты каталога. false — тогда остаётся обычная карта. */
  function showMap(sec) {
    if (!sec || !mapWanted()) return false;
    sec.classList.add('ice-map-wrap--winter');
    mapState.sec = sec;
    mapHost(sec).hidden = false;
    /* Верх карты: «Список | Карта» и те же фильтры, что в списке. */
    mapState.host.querySelector('.w-fullmap__bar').innerHTML =
      segHtml('map') + chipsHtml(cache.data, cache.data.items || [], f.origin || ctx.origin, false);
    if (mapState.ym) {
      drawMap();
      return true;
    }
    mapSay('Загружаем карту…');
    if (!mapState.loading) {
      mapState.loading = (global.IceMap && global.IceMap.loadYmapsDefault
        ? global.IceMap.loadYmapsDefault()
        : Promise.reject(new Error('no-map'))
      ).then(
        function (y) { mapState.ym = y; mapState.loading = null; return y; },
        function (e) { mapState.loading = null; throw e; }
      );
    }
    mapState.loading.then(
      function () { if (mapState.host && !mapState.host.hidden) drawMap(); },
      function () { mapSay('Карта не загрузилась. Список работает как обычно.'); }
    );
    return true;
  }

  function hideMap() {
    if (mapState.sec) mapState.sec.classList.remove('ice-map-wrap--winter');
    if (mapState.host) mapState.host.hidden = true;
  }

  /* ───── карточка точки (шторка) ───── */
  function closeSheet() {
    var had = !!sheet;
    if (sheet && sheet.parentNode) sheet.parentNode.removeChild(sheet);
    sheet = null;
    document.body.style.overflow = '';
    if (had) {
      W.tgVerticalSwipes(true);
      if (opener && opener.isConnected && opener.focus) opener.focus({ preventScroll: true });
    }
  }
  function say(el, text, bad) {
    if (!el) return;
    el.textContent = text;
    el.hidden = !text;
    el.className = bad ? 'w-error' : 'w-thanks';
  }

  function openPoint(id) {
    var p = ((cache.data && cache.data.items) || []).filter(function (x) { return x.id === id; })[0];
    if (!p) return;
    if (!p.own_page) {
      /* Немига и другие арены каталога: обычная карточка со своим расписанием. */
      if (ctx.openArena) ctx.openArena(p.slug || String(p.id));
      return;
    }
    current = p;
    report = W.reportInit();
    idem = W.newIdemKey();
    var from = document.activeElement;
    closeSheet();
    opener = from && from !== document.body ? from : opener;
    sheet = document.createElement('div');
    sheet.className = 'w-sheet';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.innerHTML = '<button type="button" class="w-sheet__back" data-w-x aria-label="Закрыть"></button><div class="w-sheet__panel"></div>';
    document.body.appendChild(sheet);
    document.body.style.overflow = 'hidden';
    sheet.addEventListener('click', onSheetClick);
    W.tgVerticalSwipes(false);
    W.attachSwipe({ panel: sheet.querySelector('.w-sheet__panel'), back: sheet.querySelector('.w-sheet__back'), onClose: closeSheet });
    paintSheet(p, null);
    fetch('/api/public/winter/points/' + p.id, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && sheet && current && current.id === p.id) paintSheet(d, d); })
      .catch(function () {});
  }

  function paintSheet(p, full) {
    var panel = sheet.querySelector('.w-sheet__panel');
    var v = W.stateView(p);
    var map = '';
    if (full && full.static_map_url) {
      var open = 'https://yandex.ru/maps/?pt=' + full.lon + ',' + full.lat + '&z=16&l=map';
      map = '<a href="' + esc(open) + '" data-w-ext class="w-hero__map" style="position:relative;display:block;height:160px;border-radius:14px;overflow:hidden">' +
        '<img src="' + esc(full.static_map_url) + '" alt="Карта" style="width:100%;height:100%;object-fit:cover" onerror="this.parentNode.remove()">' +
        '<span class="w-hero__open">Открыть в Картах</span></a>';
    } else if (p.locating) {
      map = '<p class="w-empty">Точку на карте уточняем</p>';
    }
    var tags = W.liveTags(p, new Date()).map(function (t) { return '<span class="w-tag">' + esc(t) + '</span>'; }).join('');
    var checked = W.checkedLine(p, new Date());
    function rows(list) {
      return list.filter(function (r) { return r[1]; }).map(function (r) {
        var val = r[0] === 'Телефон' ? '<a href="tel:' + esc(String(p.phone).split(/[;,]/)[0].replace(/[^\d+]/g, '')) + '" data-w-ext>' + esc(p.phone_display || p.phone) + '</a>' : esc(r[1]);
        return '<dt>' + r[0] + '</dt><dd>' + val + '</dd>';
      }).join('');
    }
    /* Часы и цена — из таблицы прошлой зимы: отдельный блок с подписью сезона из данных. */
    var season = W.dataSeason(p);
    var dataRows = rows([['Часы', W.hoursLabel(p)], ['Цена', W.priceLabel(p)]]);
    var restRows = rows([['Телефон', p.phone_display || p.phone || ''], ['Важно', p.often_hockey_note || '']]);
    var known = '<p class="w-lbl">' + (season ? 'ПРОШЛОЙ ЗИМОЙ · ' + esc(season) : 'ЧТО ИЗВЕСТНО') + '</p>' +
      (dataRows ? '<dl class="w-kv">' + dataRows + '</dl>' : '') +
      (restRows ? '<dl class="w-kv w-kv--rest">' + restRows + '</dl>' : '');
    var dispute = W.disputeNote(p);
    var waiting = p.state === 'waiting' || p.state === 'stale';
    panel.innerHTML =
      '<span class="w-sheet__grab" aria-hidden="true"></span><button type="button" class="w-sheet__close" data-w-x aria-label="Закрыть">×</button>' +
      '<div><span class="w-kindbadge">' + esc(W.kindLabel(p.kind)) + '</span><h2 class="w-sheet__title" style="margin-top:8px">' + esc(p.name) + '</h2>' +
      '<p class="w-sheet__sub">' + esc([p.address, p.district].filter(Boolean).join(' · ')) + '</p></div>' + map +
      '<div class="w-card2 ' + (v.tone === 'ok' ? 'w-card2--ok' : v.tone === 'wait' ? 'w-card2--wait' : '') + '">' +
      '<p class="w-status">' + esc(v.label) + '</p>' + (checked ? '<p class="w-note">' + esc(checked) + '</p>' : '') +
      (dispute ? '<p class="w-note">' + esc(dispute) + '</p>' : '') +
      (tags ? '<span class="w-card__tags">' + tags + '</span>' : '') + '<div data-w-body></div>' +
      '<p class="w-thanks" data-w-msg hidden role="status"></p></div>' +
      (waiting ? '<button type="button" class="w-btn w-btn--tg w-btn--wide" data-w-bell>Сообщить, когда зальют</button>' : '') +
      '<div class="w-card2">' + known + '</div>' +
      (p.route_url ? '<a class="w-btn w-btn--soft w-btn--wide" href="' + esc(p.route_url) + '" data-w-ext data-w-route>Маршрут</a>' : '') +
      '<button type="button" class="w-foot" data-w-gone style="background:none;border:0;color:var(--g-accent-ink)">Точки больше нет или ошибка? Сообщить</button>';
    paintBody(p);
  }

  function paintBody(p) {
    var body = sheet.querySelector('[data-w-body]');
    if (!body) return;
    var qs = W.questionsView(report, { flooded: p.state === 'flooded' }).map(function (q) {
      return '<fieldset class="w-q"><legend>' + esc(q.label) + '</legend><div class="w-q__row">' + q.opts.map(function (o) {
        return '<button type="button" class="w-opt" data-w-q="' + q.key + '" data-w-o="' + o.id + '" aria-pressed="' + o.selected + '">' + esc(o.label) + '</button>';
      }).join('') + '</div></fieldset>';
    }).join('');
    body.innerHTML = '<p class="w-ask" style="margin:0;font-weight:700">Как там сейчас?</p>' + qs +
      '<button type="button" class="w-btn w-btn--dark w-btn--wide" data-w-send aria-disabled="' + !W.reportCanSend(report) + '">' + esc(W.reportSendLabel(report)) + '</button>';
  }

  function onSheetClick(ev) {
    var t = ev.target;
    if (t.closest('[data-w-x]')) return closeSheet();
    var ext = t.closest('[data-w-ext]');
    if (ext) {
      ev.preventDefault();
      if (ext.hasAttribute('data-w-route') && current) {
        fetch('/api/webapp/winter/points/' + current.id + '/route-click', { method: 'POST', headers: headers(), cache: 'no-store' }).catch(function () {});
      }
      return openExternal(ext.getAttribute('href'));
    }
    var msg = sheet.querySelector('[data-w-msg]');
    var opt = t.closest('[data-w-o]');
    if (opt) {
      report = W.reportToggle(report, opt.getAttribute('data-w-q'), opt.getAttribute('data-w-o'));
      return paintBody(current);
    }
    if (t.closest('[data-w-send]')) {
      if (!W.reportCanSend(report)) return;
      var payload = W.reportPayload(report, { idem_key: idem });
      fetch('/api/webapp/winter/points/' + current.id + '/marks', { method: 'POST', headers: headers(true), body: JSON.stringify(payload) })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { status: r.status, body: j, retry: Number(r.headers.get('Retry-After')) || 0 }; }); })
        .then(function (res) {
          if (res.status === 200) {
            var out = W.reportOutcome(report, res.body, 'miniapp');
            sheet.querySelector('[data-w-body]').innerHTML = '<div class="w-result"><b>Ваша отметка:</b><strong>' + esc(out.summary) + '</strong><span>' + esc(out.rule) + '</span></div>';
            cache.key = '';
          } else {
            say(msg, W.reportErrorText(res.status, res.retry), true);
          }
        })
        .catch(function () { say(msg, W.reportErrorText(0), true); });
      return;
    }
    if (t.closest('[data-w-bell]')) {
      fetch('/api/webapp/winter/subscriptions/point', { method: 'POST', headers: headers(true), body: JSON.stringify({ arena_id: current.id }) })
        .then(function (r) { return r.ok; })
        .then(function (ok) { say(msg, ok ? 'Готово. Напишем в Telegram, когда зальют.' : 'Не получилось подписаться. Попробуйте ещё раз.', !ok); });
      return;
    }
    if (t.closest('[data-w-gone]')) {
      fetch('/api/webapp/winter/points/' + current.id + '/gone', { method: 'POST', headers: headers(), cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          say(msg, j && j.counted ? 'Спасибо, передали. Проверим точку.' :
            (j ? 'Спасибо, мы уже учли ваш сигнал.' : 'Не получилось отправить.'), !j);
        });
    }
  }

  function onClick(ev) {
    var open = ev.target.closest('[data-w-open]');
    if (open) {
      ev.preventDefault();
      return openPoint(Number(open.getAttribute('data-w-open')));
    }
    var view = ev.target.closest('[data-w-view]');
    if (view) {
      if (ctx.setView) ctx.setView(view.getAttribute('data-w-view'));
      return;
    }
    if (ev.target.closest('[data-w-retry]')) {
      cache = { key: '', data: null };
      pending = '';
      return load();
    }
    var dist = ev.target.closest('[data-w-d]');
    if (dist) {
      var dn = dist.getAttribute('data-w-d');
      f.district = f.district === dn ? '' : dn;
      return render();
    }
    var fl = ev.target.closest('[data-w-f]');
    if (fl) {
      var k = fl.getAttribute('data-w-f');
      if (k === 'near') return toggleNear();
      if (k === 'district') {
        districtsOpen = !districtsOpen;
        if (!districtsOpen) f.district = '';
        return render();
      }
      if (k === 'flooded') f.flooded = !f.flooded;
      else f.kind = f.kind === k ? '' : k;
      return render();
    }
    if (ev.target.closest('[data-w-near]')) {
      /* Подписка «рядом»: нужны координаты; без них отправляем в бота, он спросит геопозицию. */
      var go = function (lat, lon) {
        fetch('/api/webapp/winter/subscriptions/near', { method: 'POST', headers: headers(true), body: JSON.stringify({ lat: lat, lon: lon }) })
          .then(function (r) { return r.ok; })
          .then(function (ok) {
            if (ok) {
              var b = host.querySelector('[data-w-near]');
              if (b) { b.textContent = 'Включено'; b.setAttribute('aria-disabled', 'true'); }
            } else if (cache.data && cache.data.bell_near_link) openExternal(cache.data.bell_near_link);
          });
      };
      if (ctx.origin) return go(ctx.origin.lat, ctx.origin.lon);
      if (cache.data && cache.data.bell_near_link) return openExternal(cache.data.bell_near_link);
    }
  }

  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && sheet) closeSheet(); });
  global.IceWinter = { sync: sync, showMap: showMap, hideMap: hideMap, mapWanted: mapWanted, ready: function () { return !!cache.data; } };
})(window);
