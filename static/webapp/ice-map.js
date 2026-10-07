/**
 * TASK-054 Ice tab — in-place Yandex Maps (clusters, bbox, near-me, our sheet).
 * TASK-147: карта на весь экран. Плавающий верх рисует вкладка (ice.html/css);
 * здесь живут слои карты и шторка: пин = время сеанса, кластер = «N · с HH:MM»,
 * нижняя шторка peek/half (full = списочный вид через opts.onSheetFull),
 * карусель синхронна с пинами в обе стороны.
 * Never opens a Yandex org card. OSM/Leaflet are not a fallback.
 */
(function (global) {
  'use strict';

  var MM = global.IceMapModel;
  var ymapsLoad = null;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function loadYmaps(apiKey) {
    if (ymapsLoad) return ymapsLoad;
    var url = MM.scriptUrl(apiKey);
    if (!url) {
      return Promise.reject(new Error('no-key'));
    }
    ymapsLoad = new Promise(function (resolve, reject) {
      if (global.ymaps && typeof global.ymaps.ready === 'function') {
        global.ymaps.ready(function () {
          resolve(global.ymaps);
        });
        return;
      }
      var s = document.createElement('script');
      s.src = url;
      s.async = true;
      s.onload = function () {
        if (!global.ymaps || typeof global.ymaps.ready !== 'function') {
          ymapsLoad = null;
          reject(new Error('ymaps'));
          return;
        }
        global.ymaps.ready(function () {
          resolve(global.ymaps);
        });
      };
      s.onerror = function () {
        ymapsLoad = null;
        reject(new Error('ymaps-load'));
      };
      document.head.appendChild(s);
    });
    return ymapsLoad;
  }

  function readMetaMapKey() {
    if (!global.document || typeof global.document.querySelector !== 'function') return '';
    var el = global.document.querySelector('meta[name="ymaps-key"]');
    return el ? el.getAttribute('content') || '' : '';
  }

  function defaultGetKey() {
    var fromMeta = MM.resolveApiKey({ metaKey: readMetaMapKey() });
    if (fromMeta) {
      return Promise.resolve(MM.mapKeyResult(fromMeta, { reason: 'meta', status: 200, missingKey: false }));
    }
    var fromWindow = MM.resolveApiKey({ windowKey: global.YANDEX_MAPS_JS_API_KEY });
    if (fromWindow) {
      return Promise.resolve(MM.mapKeyResult(fromWindow, { reason: 'window', status: 200, missingKey: false }));
    }
    return MM.fetchMapConfigKey(global.fetch);
  }

  function normalizeKeyResult(raw) {
    if (raw && typeof raw === 'object' && 'key' in raw) return raw;
    var key = MM.resolveApiKey({ key: raw });
    return MM.mapKeyResult(key, {
      reason: key ? 'legacy' : 'config-failed',
      status: key ? 200 : 0,
      missingKey: false,
    });
  }

  function liveText(item) {
    if (global.IceTabModel && typeof global.IceTabModel.formatLiveLine === 'function') {
      return global.IceTabModel.formatLiveLine(item);
    }
    return (item && item.live && item.live.text) || (item && item.live_line) || '';
  }

  function renderEmpty(el, state) {
    if (!el) return;
    el.hidden = false;
    var actions = '';
    if (state.retryLabel || state.listLabel) {
      actions =
        '<div class="ice-map-unavail__actions">' +
        (state.retryLabel
          ? '<button type="button" class="ice-map-unavail__btn" data-map-unavail-action="retry">' +
            esc(state.retryLabel) +
            '</button>'
          : '') +
        (state.listLabel
          ? '<button type="button" class="ice-map-unavail__btn ice-map-unavail__btn--soft" data-map-unavail-action="list">' +
            esc(state.listLabel) +
            '</button>'
          : '') +
        '</div>';
    }
    el.innerHTML =
      '<div class="ice-empty ice-map-unavail"><b>' +
      esc(state.title) +
      '</b><p>' +
      esc(state.body) +
      '</p>' +
      actions +
      '</div>';
  }

  function hideEmpty(el) {
    if (!el) return;
    el.hidden = true;
    el.innerHTML = '';
  }

  function sheetHtml(item, meta, href) {
    var tone = (global.IceTabModel && global.IceTabModel.liveTone(item)) || MM.pinView(item).tone;
    var tier = String(item.tier || 'C').toUpperCase();
    var venueType = String((item && item.venue_type) || 'ice');
    var thumb = item.thumb
      ? ' style="background-image:url(\'' + esc(item.thumb).replace(/'/g, '%27') + '\')"'
      : '';
    var phClass = 'ice-acard__ph' + (item.thumb ? '' : ' ice-acard__ph--empty');
    /* TASK-148 (AC-2): нет фото — нет фото-блока и нет серой заглушки.
       Плашка типа места: иконка приезжает с сервером (venue_icon), фолбэк —
       первая буква имени. */
    var phInner = item.thumb
      ? ''
      : '<span class="ice-acard__icon" aria-hidden="true">' +
        esc(item.venue_icon || String(item.name || '').charAt(0).toUpperCase() || '?') +
        '</span>';
    var live = liveText(item);
    var liveHtml = live
      ? '<span class="ice-live ice-live--' +
        tone +
        '"><i class="ice-live__dot"></i>' +
        esc(live) +
        '</span>'
      : '';
    return (
      '<button type="button" class="ice-acard ice-acard--sheet ice-acard--type-' + esc(venueType) +
      '" data-id="' + esc(item.id) +
      '" data-href="' + esc(href || '') +
      '"><span class="' + phClass + '"' + thumb +
      '>' + phInner + '</span><span class="ice-acard__body"><span class="ice-acard__name">' +
      esc(item.name) +
      '<span class="ice-tier ice-tier--' + tone + '">' + esc(tier) + '</span></span>' +
      '<span class="ice-acard__meta">' + esc(meta) + '</span>' +
      liveHtml +
      '</span></button>'
    );
  }

  /* --- Шторка: высоты положений (прототип 2026-10-02) --- */
  var SHEET_PEEK = 96;
  var SHEET_HALF = 222;

  function mount(opts) {
    opts = opts || {};
    var canvas = opts.canvas;
    var emptyEl = opts.emptyEl;
    var sheetEl = opts.sheetEl;
    var nearBtn = opts.nearBtn;
    var offMapEl = opts.offMapEl;
    var stageEl = opts.stageEl;
    var loaderEl = opts.loaderEl;
    var attribEl = opts.attribEl;
    /* TASK-147: легенда типов под чипами окна. ice-tab.js опцию не передаёт —
       берём узел из разметки по id. */
    var legendEl = opts.legendEl || (global.document && global.document.getElementById('iceMapLegend'));
    var stageOn = false;      // сцена карты показана: без неё легенде нечего объяснять
    var listItems = [];
    var mapItems = [];
    var selected = null;
    var nearestMode = false;
    var map = null;
    var clusterer = null;
    var PinLayout = null;
    var ClusterLayout = null;
    var ymaps = null;
    var bboxState = null;
    var bboxFetchGen = 0;
    var boundsTimer = null;
    var ignoreBounds = false;
    var started = false;
    var starting = false;
    var missingKey = false;
    var keyResolved = '';
    var lastUnavailableReason = 'config-failed';
    var userPlacemark = null;

    /* Шторка (TASK-147). full-положения внутри шторки нет: тяга вверх или
       кнопка «Списком» переключают вкладку в списочный вид (opts.onSheetFull). */
    var snap = 'half';        // 'peek' | 'half'
    var railMode = 'all';     // 'all' | 'cluster'
    var railItems = null;     // места открытой карусели кластера
    var chrome = null;        // { grab, title, sub, toggle, rail }
    var railLock = false;     // лок на время программного скролла карусели
    var railUnlockTimer = null;
    var railTimer = null;
    var lastPinLayerSig = '';

    function getIntent() {
      return opts.getIntent ? opts.getIntent() : 'skate';
    }

    function isShopCatalog() {
      return opts.getCatalogScope ? opts.getCatalogScope() === 'shop' : false;
    }

    function getCityId() {
      return opts.getCityId ? opts.getCityId() : null;
    }

    function getCityBounds() {
      return opts.getCityBounds ? opts.getCityBounds() : null;
    }

    function getFallbackCenter() {
      return opts.getCityCenter ? opts.getCityCenter() : null;
    }

    function cameraOpts() {
      return { cityBounds: getCityBounds(), fallbackCenter: getFallbackCenter() };
    }

    function getWhen() {
      return opts.getWindow ? opts.getWindow() : null;
    }

    function listUrl(extra) {
      return opts.listUrl(extra);
    }

    function fetchJson(url) {
      return opts.fetchJson(url);
    }

    function arenaHref(item) {
      var target = MM.pinSheetTarget(item);
      if (target && target.href && target.yandexOrgCard === false) return target.href;
      if (opts.arenaHref) return opts.arenaHref(item);
      if (global.IceTabModel) return global.IceTabModel.arenaHref(item);
      return '';
    }

    function setLoading(on) {
      if (loaderEl) loaderEl.hidden = !on;
    }

    function showStage(on) {
      stageOn = !!on;
      if (stageEl) stageEl.hidden = !on;
      if (nearBtn) nearBtn.hidden = !on;
      setLoading(false);
      paintLegend();
    }

    /* Легенда: типы мест из текущей выдачи карты (те же места, что пины).
       Меньше двух типов или нет сцены — блока нет вообще. Цвет точки задаёт
       CSS по ключу типа (токены --app-venue-*), здесь только разметка. */
    function paintLegend() {
      if (!legendEl) return;
      if (!stageOn) {
        legendEl.hidden = true;
        legendEl.innerHTML = '';
        return;
      }
      if (isShopCatalog()) {
        var cap = typeof opts.getShopMapCaption === 'function' ? String(opts.getShopMapCaption() || '') : '';
        var n = catalogOnMap().length;
        if (!cap) {
          cap = n + ' ' + MM.pluralRu(n, 'магазин', 'магазина', 'магазинов');
        }
        legendEl.innerHTML =
          '<span class="ice-map-legend__item ice-map-legend__item--shop">' +
          '<i class="ice-map-legend__dot" aria-hidden="true"></i>' +
          esc(cap) +
          '</span>';
        legendEl.hidden = false;
        return;
      }
      var view = MM.legendView(catalogOnMap());
      if (!view.show) {
        legendEl.hidden = true;
        legendEl.innerHTML = '';
        return;
      }
      legendEl.innerHTML = view.entries
        .map(function (e) {
          return (
            '<span class="ice-map-legend__item ice-map-legend__item--' + esc(e.key) + '">' +
            '<i class="ice-map-legend__dot" aria-hidden="true"></i>' + esc(e.label) +
            '</span>'
          );
        })
        .join('');
      legendEl.hidden = false;
    }

    function setOffMapNote() {
      if (!offMapEl) return;
      var split = MM.splitMapAndList(listItems);
      var note = MM.formatOffMapNote(split.offMapCount);
      offMapEl.textContent = note;
      offMapEl.hidden = !note;
    }

    /* ─── Шторка: каркас собирается один раз и живёт до конца вкладки ───
       Карусель — единственная динамическая часть: перерисовывается только
       innerHTML рельсы, поэтому слушатели скролла не умирают при repaint. */
    function buildChrome() {
      if (!sheetEl || chrome) return;
      sheetEl.innerHTML =
        '<div class="ice-map-sheet__grab">' +
          '<div class="ice-map-sheet__handle"></div>' +
          '<div class="ice-map-sheet__head">' +
            '<div class="ice-map-sheet__titles">' +
              '<div class="ice-map-sheet__title"></div>' +
              '<div class="ice-map-sheet__sub"></div>' +
            '</div>' +
            '<button type="button" class="ice-map-sheet__toggle">Списком</button>' +
          '</div>' +
        '</div>' +
        '<div class="ice-map-sheet__body">' +
          '<div class="ice-map-rail" role="list"></div>' +
        '</div>';
      chrome = {
        grab: sheetEl.querySelector('.ice-map-sheet__grab'),
        title: sheetEl.querySelector('.ice-map-sheet__title'),
        sub: sheetEl.querySelector('.ice-map-sheet__sub'),
        toggle: sheetEl.querySelector('.ice-map-sheet__toggle'),
        rail: sheetEl.querySelector('.ice-map-rail'),
      };
      chrome.toggle.addEventListener('click', function () {
        if (typeof opts.onSheetFull === 'function') opts.onSheetFull();
      });
      bindSheetDrag();
      bindRail();
      bindSheetEmptyActions();
      setSnap(snap);
    }

    function bindSheetEmptyActions() {
      if (!sheetEl || sheetEl.__emptyBound) return;
      sheetEl.__emptyBound = true;
      sheetEl.addEventListener('click', function (ev) {
        var btn = ev.target.closest('[data-map-empty-action]');
        if (!btn) return;
        if (btn.getAttribute('data-map-empty-action') === 'list' && typeof opts.onSheetFull === 'function') {
          opts.onSheetFull();
        }
      });
    }

    function railEmptyHtml(state) {
      if (!state) return '';
      var btn = state.action
        ? '<button type="button" class="ice-map-rail-empty__btn" data-map-empty-action="' +
          esc(state.action.kind) +
          '">' +
          esc(state.action.label) +
          '</button>'
        : '';
      return (
        '<div class="ice-map-rail-empty">' +
        '<b>' +
        esc(state.title) +
        '</b><p>' +
        esc(state.body) +
        '</p>' +
        btn +
        '</div>'
      );
    }

    function sheetVisiblePx() {
      return snap === 'peek' ? SHEET_PEEK : SHEET_HALF;
    }

    /** Карусель и пины: выдача вкладки, не срез bbox после зума к одной арене. */
    function catalogOnMap() {
      if (!listItems.length) return MM.splitMapAndList(mapItems).onMap.slice();
      return mapItemsFromList(listItems);
    }

    function railPlaceCount() {
      return catalogOnMap().length;
    }

    function setSnap(next) {
      snap = next;
      if (!sheetEl) return;
      sheetEl.dataset.snap = snap;
      sheetEl.style.height = sheetVisiblePx() + 'px';
      syncChromeBottom();
    }

    /* FAB «Где я» и копирайт едут вместе со шторкой. FAB лежит внутри сцены (она уже
       поднята над таб-баром), а копирайт — fixed от низа окна, как и шторка, поэтому ему
       нужен тот же отступ таб-бара. Без него копирайт оказывался ПОД шторкой (TASK-147). */
    function syncChromeBottom() {
      var h = sheetVisiblePx();
      if (nearBtn) nearBtn.style.bottom = (h + 12) + 'px';
      if (attribEl) attribEl.style.bottom = 'calc(var(--client-shell-tab-inset, 80px) + ' + (h + 8) + 'px)';
    }

    function showSheet(on) {
      if (!sheetEl) return;
      buildChrome();
      sheetEl.hidden = !on;
    }

    /* ─── Шапка шторки ─── */
    function renderSummary() {
      if (!chrome) return;
      if (railMode === 'cluster' && railItems) {
        var n = railItems.length;
        chrome.title.innerHTML =
          '<b>' + n + ' ' + MM.pluralRu(n, 'место', 'места', 'мест') + '</b> рядом';
        chrome.sub.textContent = 'Тапните по карте, чтобы вернуться ко всем';
        return;
      }
      var s = MM.sheetSummary(catalogOnMap(), getWhen());
      if (!s) s = 'Места города';
      var cut = s.indexOf(' · ');
      if (cut >= 0) {
        chrome.title.innerHTML = '<b>' + esc(s.slice(0, cut)) + '</b>';
        chrome.sub.textContent = s.slice(cut + 3);
      } else {
        chrome.title.innerHTML = '<b>' + esc(s) + '</b>';
        chrome.sub.textContent = '';
      }
    }

    function railCardsHtml(items) {
      return items
        .map(function (item) {
          var meta = MM.formatSheetMeta(item, { nearest: false });
          if (!meta && global.IceTabModel) meta = global.IceTabModel.formatMeta(item);
          return sheetHtml(item, meta, arenaHref(item));
        })
        .join('');
    }

    /* Текущий набор карусели: все места карты или подмножество кластера.
       После перезапроса bbox кластер, который зум развёл, схлопывается сам. */
    function currentRailSet() {
      if (railMode === 'cluster' && railItems) {
        var ids = railItems.map(function (it) {
          return it.id;
        });
        var pool = catalogOnMap();
        var still = pool.filter(function (it) {
          return ids.indexOf(it.id) >= 0;
        });
        if (still.length > 1) return still;
        if (still.length === 1) railMode = 'all';
      }
      railItems = null;
      railMode = 'all';
      return catalogOnMap();
    }

    function renderSheet() {
      if (!sheetEl) return;
      buildChrome();
      var items = MM.railOrder(currentRailSet());
      if (!items.length) {
        chrome.rail.innerHTML = railEmptyHtml(
          MM.sheetRailEmptyState({
            listItems: listItems,
            mapItems: mapItems,
            catalogScope: isShopCatalog() ? 'shop' : 'places',
          })
        );
      } else {
        chrome.rail.innerHTML = railCardsHtml(items);
      }
      renderSummary();
      applyRailSelection();
      if (selected && items.some(function (it) { return it.id === selected.id; })) {
        scrollToCard(selected, { instant: true });
      }
    }

    /* ─── Выделение: пин ↔ карточка ─── */
    /* Template-layout 2.1 перестраивает DOM на каждое properties.set —
       трогаем только плейсмарки, чьё состояние реально поменялось. */
    function setPinSelection(item) {
      if (!clusterer) return;
      var objs = clusterer.getGeoObjects();
      objs.forEach(function (obj) {
        var want = !!(item && obj.properties.get('arenaId') === item.id);
        if (obj.properties.get('sel') !== want) obj.properties.set('sel', want);
        var dim = !isShopCatalog() && !!(item && !want);
        if (obj.properties.get('dim') !== dim) obj.properties.set('dim', dim);
      });
    }

    function applyRailSelection() {
      if (!chrome || !chrome.rail) return;
      var selId = selected ? Number(selected.id) : null;
      Array.prototype.forEach.call(chrome.rail.children, function (card) {
        card.classList.toggle('is-sel', selId != null && Number(card.getAttribute('data-id')) === selId);
      });
    }

    function scrollToCard(item, o) {
      o = o || {};
      if (!chrome || !chrome.rail) return;
      var card = chrome.rail.querySelector('.ice-acard[data-id="' + item.id + '"]');
      if (!card) return;
      railLock = true;
      chrome.rail.scrollTo({
        left: Math.max(0, card.offsetLeft - 22),
        behavior: o.instant ? 'auto' : 'smooth',
      });
      global.clearTimeout(railUnlockTimer);
      railUnlockTimer = global.setTimeout(function () {
        railLock = false;
      }, o.instant ? 80 : 480);
    }

    /* Карусель → пин: доводим камеру, если место съехало за плавающий верх
       или уехало под шторку. На виду — не дёргаем. */
    function panToItem(item) {
      if (!map || !stageEl) return;
      var coords = [Number(item.latitude), Number(item.longitude)];
      var b = map.getBounds();
      if (!b) return;
      var hpx = stageEl.offsetHeight || 1;
      var topPx = 150;                       // плавающий верх
      var bottomPx = sheetVisiblePx() + 12;  // шторка
      var latSpan = b[1][0] - b[0][0];
      var lonSpan = b[1][1] - b[0][1];
      var nLat = b[1][0] - latSpan * (topPx / hpx);
      var sLat = b[0][0] + latSpan * (bottomPx / hpx);
      var wLon = b[0][1] + lonSpan * 0.08;
      var eLon = b[1][1] - lonSpan * 0.08;
      var lat = coords[0];
      var lon = coords[1];
      if (lat > sLat && lat < nLat && lon > wLon && lon < eLon) return;
      ignoreBounds = true;
      map.setCenter(coords, map.getZoom(), { duration: 320 });
      global.setTimeout(function () {
        ignoreBounds = false;
      }, 380);
    }

    /* Карусель / тап по пину: карта отвечает «где это» — зум к точке, не только если уехала за край. */
    function focusSelectedOnMap(item) {
      if (!map || !item) return;
      var focus = MM.singlePlaceFocus(item, {
        margin: [150, 70, sheetVisiblePx() + 24, 70],
      });
      if (!focus) return;
      ignoreBounds = true;
      map
        .setBounds(focus.bounds, { checkZoomRange: true, zoomMargin: focus.margin, duration: 320 })
        .then(function () {
          var cap = map.options.get('maxZoom');
          if (map.getZoom() > cap) map.setZoom(cap, { duration: 150 });
        })
        .then(function () {
          global.setTimeout(function () {
            ignoreBounds = false;
            setPinSelection(selected);
          }, 380);
        }, function () {
          ignoreBounds = false;
        });
    }

    function select(item, o) {
      o = o || {};
      if (!item) return;
      selected = item;
      nearestMode = false;
      setPinSelection(item);
      if (sheetEl && sheetEl.hidden) showSheet(true);
      applyRailSelection();
      /* peek→half только по жесту человека (пин / явный expand).
         Пан и зум карты зовут defaultSheet → select без expand — шторку не трогаем. */
      if ((o.expand || o.fromPin) && snap === 'peek') setSnap('half');
      if (o.fromPin) scrollToCard(item);
      if (o.pan || o.fromPin || o.expand) focusSelectedOnMap(item);
    }

    /* ─── Кластер ─── */
    function openClusterRail(items) {
      railMode = 'cluster';
      railItems = items;
      selected = null;
      nearestMode = false;
      showSheet(true);
      if (snap === 'peek') setSnap('half');
      renderSheet();
    }

    function resetClusterRail() {
      if (railMode !== 'cluster') return;
      railMode = 'all';
      railItems = null;
      selected = null;
      renderSheet();
    }

    function onClusterClick(ev) {
      var target = ev && ev.get && ev.get('target');
      if (!target || typeof target.getGeoObjects !== 'function') return;
      var objs = target.getGeoObjects();
      var points = objs.map(function (o) {
        return o.geometry.getCoordinates();
      });
      var ids = objs.map(function (o) {
        return o.properties.get('arenaId');
      });
      var items = catalogOnMap().filter(function (it) {
        return ids.indexOf(it.id) >= 0;
      });
      if (!items.length) return;
      /* Свой зум по тапу: стандартный вписывает точки без учёта ярлыков (~110px
         сверху) и шторки (снизу). Поля передаём с текущей высотой шторки. */
      var focus = MM.clusterFocus(points, {
        maxZoom: map.options.get('maxZoom'),
        margin: [150, 70, sheetVisiblePx() + 24, 70],
      });
      openClusterRail(items);
      if (focus.mode !== 'zoom') return;
      map
        .setBounds(focus.bounds, { checkZoomRange: true, zoomMargin: focus.margin, duration: 300 })
        .then(function () {
          if (map.getZoom() > focus.maxZoom) map.setZoom(focus.maxZoom, { duration: 150 });
        });
    }

    /* ─── Шторка: что показывать по умолчанию ─── */
    function defaultSheet() {
      if (railMode === 'cluster' && railItems) {
        var ids = railItems.map(function (it) {
          return it.id;
        });
        var pool = catalogOnMap();
        var still = pool.filter(function (it) {
          return ids.indexOf(it.id) >= 0;
        });
        if (still.length > 1) {
          railItems = still;
          renderSheet();
          return;
        }
        if (still.length === 1) {
          railMode = 'all';
          railItems = null;
        }
      }
      var onCatalog = catalogOnMap();
      if (selected && onCatalog.some(function (it) { return it.id === selected.id; })) {
        showSheet(true);
        renderSheet();
        select(selected, {});
        return;
      }
      selected = null;
      var nearest = MM.pickNearest(onCatalog.length ? onCatalog : MM.splitMapAndList(listItems).onMap);
      if (nearest) {
        railMode = 'all';
        railItems = null;
        showSheet(true);
        renderSheet();
        nearestMode = nearest.distance_km != null;
        select(nearest, isShopCatalog() ? { pan: true } : {});
      } else if (listItems.length || mapItems.length) {
        selected = null;
        showSheet(true);
        renderSheet();
      } else {
        showSheet(false);
        selected = null;
      }
    }

    /* paintSheet(item) = «показать шторку с этим местом»; null = скрыть. */
    function paintSheet(item, asNearest) {
      if (!item) {
        selected = null;
        showSheet(false);
        return;
      }
      railMode = 'all';
      railItems = null;
      showSheet(true);
      renderSheet();
      nearestMode = !!asNearest;
      select(item, { expand: true });
    }

    /* ─── Слои карты ─── */
    function pinCompact() {
      if (!map) return false;
      return map.getZoom() < 14;
    }

    function syncObjects(force) {
      if (!clusterer || !ymaps) return;
      var onMapCount = catalogOnMap().length;
      var minCluster = isShopCatalog() || onMapCount <= 28 ? 100 : 2;
      if (clusterer.options.get('minClusterSize') !== minCluster) {
        clusterer.options.set('minClusterSize', minCluster);
        force = true;
      }
      var onMap = catalogOnMap();
      var sig = MM.pinLayerSignature(onMap) + '|z' + (pinCompact() ? 'c' : 'n');
      if (!force && sig === lastPinLayerSig && clusterer.getGeoObjects().length) {
        setPinSelection(selected);
        paintLegend();
        return;
      }
      lastPinLayerSig = sig;
      clusterer.removeAll();
      var marks = onMap.map(function (item) {
        var view = MM.pinView(item);
        var pm = new ymaps.Placemark(
          [Number(item.latitude), Number(item.longitude)],
          {
            tone: view.tone,
            label: view.label,
            shortName: view.shortName,
            muted: view.muted,
            when: view.when,
            venue: view.venue,
            kind: view.kind,
            sel: false,
            dim: false,
            compact: pinCompact(),
            arenaId: item.id,
            item: item,
          },
          {
            iconLayout: PinLayout,
            iconShape: {
              type: 'Rectangle',
              coordinates: [
                [-80, -40],
                [80, 2],
              ],
            },
            hasBalloon: false,
            openBalloonOnClick: false,
            hasHint: false,
          }
        );
        pm.events.add('click', function (ev) {
          if (ev && ev.preventDefault) ev.preventDefault();
          select(item, { fromPin: true, pan: true });
        });
        return pm;
      });
      clusterer.add(marks);
      paintLegend();
    }

    function mapItemsFromList(source) {
      source = source || listItems;
      if (typeof opts.filterMapItems === 'function') {
        source = opts.filterMapItems(source);
      }
      return MM.splitMapAndList(source).onMap.slice();
    }

    function showCoachEmpty() {
      listItems = [];
      mapItems = [];
      selected = null;
      nearestMode = false;
      bboxState = null;
      if (clusterer) syncObjects();
      paintSheet(null);
      showStage(false);
      if (offMapEl) {
        offMapEl.hidden = true;
        offMapEl.textContent = '';
      }
      renderEmpty(emptyEl, MM.coachMapEmptyState());
    }

    function fetchViewport() {
      if (getIntent() === 'coach') {
        showCoachEmpty();
        return;
      }
      /* Магазины: полный набор уже в listItems + клиентские фильтры; bbox-перезапрос
         дёргает шторку, сбрасывает выделение и даёт пустую карусель вне вьюпорта. */
      if (isShopCatalog()) return;
      /* Каталог уже в listItems (фильтры вкладки). Bbox после focusSelectedOnMap
         подменял mapItems одной ареной и ломал карусель. */
      if (listItems.length > 0) return;
      if (!map || !opts.listUrl) return;
      var bbox = MM.boundsToBbox(map.getBounds());
      if (MM.bboxExceedsCity(bbox)) {
        applyCityCamera();
        return;
      }
      var payload = MM.bboxFetchPayload({
        bbox: bbox,
        intent: getIntent(),
        cityId: getCityId(),
        limit: 50,
      });
      if (!payload.fetch) return;
      var plan = MM.planBboxFetch(bboxState, payload.bbox);
      if (!plan.fetch) return;
      var url = listUrl({
        bbox: payload.bbox,
        intent: payload.intent,
        limit: payload.limit,
        cityId: payload.cityId != null ? payload.cityId : getCityId(),
      });
      if (!url) return;
      bboxState = plan;
      bboxFetchGen += 1;
      var gen = bboxFetchGen;
      fetchJson(url)
        .then(function (data) {
          if (gen !== bboxFetchGen) return;
          var raw = (data && data.items) || [];
          mapItems = mapItemsFromList(raw);
          syncObjects();
          defaultSheet();
        })
        .catch(function () {
          /* Оставляем предыдущие пины; шторку не ломаем. */
        });
    }

    function applyCityCamera() {
      if (!map) return;
      var cam = MM.cityCameraFromItems(listItems, cameraOpts());
      if (!cam) return;
      ignoreBounds = true;
      bboxState = null;
      map.options.set('restrictMapArea', cam.restrict);
      map.options.set('minZoom', cam.minZoom);
      map.options.set('maxZoom', cam.maxZoom);
      var done = function () {
        global.setTimeout(function () {
          ignoreBounds = false;
          fetchViewport();
        }, 120);
      };
      map.setBounds(cam.restrict, { checkZoomRange: true, zoomMargin: 72 }).then(function () {
        var z = map.getZoom();
        if (z < cam.minZoom) map.setZoom(cam.minZoom);
        if (z > cam.maxZoom) map.setZoom(cam.maxZoom);
        done();
      }, done);
    }

    function onBoundsChange() {
      if (ignoreBounds) return;
      if (map && clusterer) syncObjects();
      global.clearTimeout(boundsTimer);
      boundsTimer = global.setTimeout(fetchViewport, 320);
    }

    function fitCity() {
      applyCityCamera();
    }

    function buildLayouts() {
      /* Пин собирается в build(): template-engine 2.1 не умеет условные классы,
         а DOM-управление даёт полный контроль. Перестройка происходит при
         properties.set — в том числе на выделение. */
      PinLayout = ymaps.templateLayoutFactory.createClass(
        '<div class="ice-ypin"><span class="ice-ypin__body">' +
            '<span class="ice-ypin__dot"></span>' +
            '<span class="ice-ypin__label"></span>' +
            '<span class="ice-ypin__name"></span>' +
          '</span><span class="ice-ypin__tail"></span></div>',
        {
          build: function () {
            PinLayout.superclass.build.call(this);
            var root = this.getParentElement() && this.getParentElement().querySelector('.ice-ypin');
            if (!root) return;
            var props = this.getData().properties;
            root.className =
              'ice-ypin' +
              ' ice-ypin--' + String(props.get('tone') || 'c') +
              ' ice-ypin--' + String(props.get('when') || 'in') +
              ' ice-ypin--' + String(props.get('venue') || 'ice') +
              ' ice-ypin--' + String(props.get('kind') || 'dot') +
              (props.get('sel') ? ' ice-ypin--sel' : '') +
              (props.get('dim') ? ' ice-ypin--dim' : '') +
              (props.get('compact') ? ' ice-ypin--compact' : '');
            var label = root.querySelector('.ice-ypin__label');
            var labelText = String(props.get('label') || '');
            if (label) label.textContent = labelText;
            var name = root.querySelector('.ice-ypin__name');
            if (name) {
              var sn = String(props.get('shortName') || '');
              var venue = String(props.get('venue') || 'ice');
              if (venue === 'shop' || labelText === sn) name.textContent = '';
              else if (props.get('sel') && labelText && labelText !== sn) name.textContent = sn;
              else name.textContent = '';
            }
          },
        }
      );
      /* Кластер — только круг с числом. Подпись («с 18:15» / «нет сеансов»)
         жила вторым овалом и читалась как чужая метка; время — в шторке. */
      ClusterLayout = ymaps.templateLayoutFactory.createClass(
        '<div class="ice-ycluster"></div>',
        {
          build: function () {
            ClusterLayout.superclass.build.call(this);
            var root = this.getParentElement() && this.getParentElement().querySelector('.ice-ycluster');
            if (!root) return;
            var data = this.getData();
            var objs = (data.properties && data.properties.get('geoObjects')) || [];
            var items = [];
            objs.forEach(function (o) {
              var it = o.properties.get('item');
              if (it) items.push(it);
            });
            var s = MM.clusterSummary(items);
            root.textContent = String(s.count);
            root.setAttribute('aria-label', s.count + ' · ' + s.label);
            var sel = objs.some(function (o) {
              return o.properties.get('sel');
            });
            root.classList.toggle('ice-ycluster--sel', sel);
            root.classList.toggle('ice-ycluster--quiet', !s.hasHits);
            root.classList.toggle(
              'ice-ycluster--shops',
              items.length && items.every(function (it) {
                return MM.venueKey(it) === 'shop';
              })
            );
          },
        }
      );
    }

    function createMap() {
      if (map || !canvas) return;
      buildLayouts();
      var cam = MM.cityCameraFromItems(listItems, cameraOpts());
      if (!cam) return;
      map = new ymaps.Map(
        canvas,
        {
          center: cam.center,
          zoom: cam.zoom,
          controls: [],
        },
        {
          yandexMapDisablePoiInteractivity: true,
          suppressMapOpenBlock: true,
          suppressObsoleteBrowserNotifier: true,
          restrictMapArea: cam.restrict,
          minZoom: cam.minZoom,
          maxZoom: cam.maxZoom,
        }
      );
      clusterer = new ymaps.Clusterer({
        minClusterSize: 2,
        gridSize: 64,
        // Свой зум по тапу (onClusterClick): стандартный не учитывает ярлыки и шторку.
        clusterDisableClickZoom: true,
        clusterOpenBalloonOnClick: false,
        hasBalloon: false,
        clusterHasBalloon: false,
        groupByCoordinates: false,
        clusterIconLayout: ClusterLayout,
        clusterIconShape: {
          type: 'Circle',
          coordinates: [0, 0],
          radius: 18,
        },
      });
      clusterer.options.set({ hasBalloon: false, clusterOpenBalloonOnClick: false });
      map.geoObjects.add(clusterer);
      clusterer.events.add('click', onClusterClick);
      map.events.add('boundschange', onBoundsChange);
      // Тап по пустой карте — назад ко всем местам.
      map.events.add('click', function () {
        resetClusterRail();
      });
    }

    /* ─── Взаимодействие шторки ─── */
    function bindSheetDrag() {
      if (!sheetEl || sheetEl.__sheetBound) return;
      sheetEl.__sheetBound = true;
      var on = false;
      var y0 = 0;
      var h0 = 0;
      var moved = false;
      var dyMax = 0;
      sheetEl.addEventListener('pointerdown', function (e) {
        if (!e.target.closest('.ice-map-sheet__grab')) return;
        if (e.target.closest('.ice-map-sheet__toggle')) return;
        on = true;
        moved = false;
        dyMax = 0;
        y0 = e.clientY;
        h0 = sheetEl.getBoundingClientRect().height || SHEET_HALF;
        sheetEl.classList.add('ice-map-sheet--drag');
        try {
          sheetEl.setPointerCapture(e.pointerId);
        } catch (err) {
          /* ignore */
        }
      });
      sheetEl.addEventListener('pointermove', function (e) {
        if (!on) return;
        var dy = y0 - e.clientY;
        if (Math.abs(dy) > 5) moved = true;
        dyMax = Math.max(dyMax, dy);
        /* Полные пределы не тянут: выше half — это уже «хочу список». */
        var h = Math.max(SHEET_PEEK, Math.min(SHEET_HALF, h0 + dy));
        sheetEl.style.height = h + 'px';
      });
      function end() {
        if (!on) return;
        on = false;
        sheetEl.classList.remove('ice-map-sheet--drag');
        if (!moved) {
          setSnap(snap === 'peek' ? 'half' : 'peek');
          return;
        }
        setSnap(MM.snapFor(sheetEl.getBoundingClientRect().height, { peek: SHEET_PEEK, half: SHEET_HALF }));
      }
      sheetEl.addEventListener('pointerup', end);
      sheetEl.addEventListener('pointercancel', end);
    }

    /* Карусель → пин: какая карточка по центру, та и выбрана. */
    function bindRail() {
      if (!chrome || !chrome.rail || chrome.rail.__railBound) return;
      chrome.rail.__railBound = true;
      chrome.rail.addEventListener('scroll', function () {
        if (railLock) return;
        global.clearTimeout(railTimer);
        railTimer = global.setTimeout(function () {
          var rail = chrome.rail;
          var mid = rail.scrollLeft + rail.clientWidth / 2;
          var best = null;
          var bestDist = Infinity;
          Array.prototype.forEach.call(rail.children, function (card) {
            var m = card.offsetLeft + card.offsetWidth / 2;
            var d = Math.abs(m - mid);
            if (d < bestDist) {
              bestDist = d;
              best = card;
            }
          });
          if (!best) return;
          var id = Number(best.getAttribute('data-id'));
          if (selected && Number(selected.id) === id) return;
          var source = railMode === 'cluster' && railItems ? railItems : catalogOnMap();
          var item = source.filter(function (it) {
            return Number(it.id) === id;
          })[0];
          if (item) select(item, { pan: true });
        }, 140);
      });
    }

    /* ─── Запуск ─── */
    function bindUnavailableActions() {
      if (!emptyEl || emptyEl.__unavailBound) return;
      emptyEl.__unavailBound = true;
      emptyEl.addEventListener('click', function (ev) {
        var btn = ev.target.closest('[data-map-unavail-action]');
        if (!btn) return;
        var action = btn.getAttribute('data-map-unavail-action');
        if (action === 'retry') {
          if (starting || missingKey || btn.disabled) return;
          start();
          return;
        }
        if (action === 'list' && typeof opts.onShowList === 'function') opts.onShowList();
      });
    }

    function showUnavailable(reason) {
      reason = reason || lastUnavailableReason || 'config-failed';
      lastUnavailableReason = reason;
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('[ice-map]', reason);
      }
      showStage(false);
      showSheet(false);
      bindUnavailableActions();
      var view = MM.mapUnavailableState(reason);
      if (reason === 'no-key') view = Object.assign({}, view, { retryLabel: '' });
      renderEmpty(emptyEl, view);
    }

    function setRetryDisabled(on) {
      if (!emptyEl || !emptyEl.querySelector) return;
      var retryBtn = emptyEl.querySelector('[data-map-unavail-action="retry"]');
      if (retryBtn) retryBtn.disabled = !!on;
    }

    function start() {
      if (starting) return Promise.resolve();
      if (getIntent() === 'coach') {
        showCoachEmpty();
        return Promise.resolve();
      }
      if (missingKey) {
        showUnavailable('no-key');
        return Promise.resolve();
      }
      if (map) {
        var existing = MM.mapStartDecision({
          key: keyResolved || 'live',
          listItems: listItems,
          intent: getIntent(),
        });
        if (existing.kind === 'coach') {
          showCoachEmpty();
          return Promise.resolve();
        }
        if (existing.kind === 'no-arenas') {
          if (typeof opts.listReady === 'function' && !opts.listReady()) {
            showStage(false);
            hideEmpty(emptyEl);
            mapItems = [];
            selected = null;
            if (clusterer) syncObjects();
            paintSheet(null);
            return Promise.resolve();
          }
          showStage(false);
          renderEmpty(emptyEl, existing.empty);
          mapItems = [];
          selected = null;
          if (clusterer) syncObjects();
          paintSheet(null);
          return Promise.resolve();
        }
        hideEmpty(emptyEl);
        showStage(true);
        map.container.fitToViewport();
        mapItems = mapItemsFromList(listItems);
        syncObjects();
        defaultSheet();
        applyCityCamera();
        return Promise.resolve();
      }
      var getKey = opts.getKey || defaultGetKey;
      starting = true;
      setRetryDisabled(true);
      var keyPromise = keyResolved
        ? Promise.resolve(MM.mapKeyResult(keyResolved, { reason: 'cached', status: 200, missingKey: false }))
        : Promise.resolve(getKey());
      return keyPromise.then(function (raw) {
          var result = normalizeKeyResult(raw);
          if (!result.key) {
            if (result.missingKey) {
              missingKey = true;
              showUnavailable('no-key');
            } else {
              showUnavailable(result.reason || 'config-failed');
            }
            return;
          }
          keyResolved = result.key;
          started = true;
          var decision = MM.mapStartDecision({
            key: keyResolved,
            listItems: listItems,
            intent: getIntent(),
          });
          if (decision.kind === 'unavailable') {
            missingKey = true;
            showUnavailable(decision.empty && decision.empty.reason ? decision.empty.reason : 'no-key');
            return;
          }
          if (decision.kind === 'coach') {
            showCoachEmpty();
            return;
          }
          if (decision.kind === 'no-arenas') {
            if (typeof opts.listReady === 'function' && !opts.listReady()) {
              return;
            }
            showStage(false);
            renderEmpty(emptyEl, decision.empty);
            showSheet(false);
            return;
          }
          // Единственная по-настоящему долгая ветка: тянем SDK Яндекса по сети.
          // Всё выше решается синхронно и лоадера не заслуживает.
          setLoading(true);
          return loadYmaps(keyResolved).then(function (api) {
            ymaps = api;
            hideEmpty(emptyEl);
            showStage(true);
            createMap();
            if (map && map.container && typeof map.container.fitToViewport === 'function') {
              map.container.fitToViewport();
            }
            mapItems = mapItemsFromList(listItems);
            syncObjects();
            defaultSheet();
            fitCity();
          });
        })
        .catch(function (err) {
          var tag = err && err.message === 'no-key' ? 'no-key' : 'sdk-failed';
          if (typeof console !== 'undefined' && console.warn) {
            console.warn('[ice-map]', tag, err && err.message);
          }
          if (tag === 'no-key') missingKey = true;
          showUnavailable(tag);
        })
        .then(function () {
          starting = false;
          setRetryDisabled(false);
        }, function () {
          starting = false;
          setRetryDisabled(false);
        });
    }

    function onNearClick() {
      if (getIntent() === 'coach') return;
      if (!nearMePolicyOk()) return;
      if (!navigator.geolocation) {
        paintGeoDenied();
        return;
      }
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          var lat = pos.coords.latitude;
          var lon = pos.coords.longitude;
          var near = lat + ',' + lon;
          var extra = { near: near, intent: getIntent(), limit: 50 };
          var cityId = getCityId();
          if (cityId != null) extra.cityId = cityId;
          fetchJson(listUrl(extra)).then(function (data) {
            var raw = (data && data.items) || [];
            var items =
              typeof opts.filterMapItems === 'function' ? opts.filterMapItems(raw) : raw;
            if (typeof opts.onNearList === 'function') opts.onNearList({ items: raw, total: raw.length });
            listItems = items.length ? items : listItems;
            var mapped = MM.splitMapAndList(items).onMap;
            if (!mapped.length) {
              paintGeoNote(MM.noArenasNearState());
              return;
            }
            hideEmpty(emptyEl);
            mapItems = mapped;
            var nearest = MM.pickNearest(mapped);
            syncObjects();
            paintSheet(nearest, true);
            setOffMapNote();
            if (map) {
              ignoreBounds = true;
              map.setCenter([lat, lon], 13);
              if (ymaps) {
                if (userPlacemark) map.geoObjects.remove(userPlacemark);
                userPlacemark = new ymaps.Placemark(
                  [lat, lon],
                  {},
                  { preset: 'islands#geolocationIcon', hasBalloon: false }
                );
                map.geoObjects.add(userPlacemark);
              }
              global.setTimeout(function () {
                ignoreBounds = false;
              }, 200);
            }
          });
        },
        function () {
          paintGeoDenied();
        },
        { timeout: 8000, maximumAge: 30000 }
      );
    }

    function nearMePolicyOk() {
      return MM.nearMePolicy.geolocateOnButton && !MM.nearMePolicy.geolocateOnStart;
    }

    function paintGeoDenied() {
      var outcome = MM.afterGeoDenied({
        pinCount: mapItems.length,
        sheetOpen: !!selected,
      });
      if (outcome.keepStage) showStage(true);
      // Заметка живёт в шапке шторки: карта остаётся полезной (AC geo-denied).
      paintGeoNote(outcome);
    }

    /* Заметки (гео-отказ, пустой near) живут в шапке шторки: отдельного
       «тела под картой» больше нет. */
    function paintGeoNote(state) {
      if (!sheetEl) return;
      buildChrome();
      showSheet(true);
      if (chrome.title) chrome.title.innerHTML = '<b>' + esc(state.title) + '</b>';
      if (chrome.sub) chrome.sub.textContent = state.body || '';
      chrome.rail.innerHTML = '';
      setSnap('half');
    }

    if (nearBtn && nearMePolicyOk()) {
      nearBtn.addEventListener('click', onNearClick);
    }

    if (sheetEl) {
      sheetEl.addEventListener('click', function (ev) {
        var card = ev.target.closest('[data-href]');
        if (!card) return;
        var href = card.getAttribute('data-href') || '';
        if (!href) return;
        var id = card.getAttribute('data-id');
        var item =
          mapItems.filter(function (it) {
            return String(it.id) === id;
          })[0] || selected;
        if (typeof opts.onOpenArena === 'function') {
          opts.onOpenArena(item, href);
        }
      });
    }

    return {
      start: start,
      leaveCity: function () {
        bboxState = null;
        listItems = [];
        mapItems = [];
        selected = null;
        nearestMode = false;
        lastPinLayerSig = '';
        if (clusterer) syncObjects(true);
        paintSheet(null);
        showStage(false);
        hideEmpty(emptyEl);
      },
      setListItems: function (items) {
        listItems = items || [];
        setOffMapNote();
        if (getIntent() === 'coach') return;
        var decision = MM.mapStartDecision({
          key: keyResolved || 'live',
          listItems: listItems,
          intent: getIntent(),
        });
        if (decision.kind === 'no-arenas') {
          if (typeof opts.listReady === 'function' && !opts.listReady()) {
            showStage(false);
            hideEmpty(emptyEl);
            if (map) {
              mapItems = [];
              selected = null;
              syncObjects();
              paintSheet(null);
            }
            return;
          }
          showStage(false);
          renderEmpty(emptyEl, decision.empty);
          if (map) {
            mapItems = [];
            selected = null;
            syncObjects();
            paintSheet(null);
          }
          return;
        }
        if (map) {
          hideEmpty(emptyEl);
          showStage(true);
          mapItems = mapItemsFromList(listItems);
          syncObjects();
          defaultSheet();
          applyCityCamera();
        }
        if (!map && started && !missingKey && listItems.length && getIntent() !== 'coach') {
          start();
        }
      },
      refresh: function () {
        bboxState = null;
        if (!missingKey) start();
      },
      snapPeek: function () {
        if (!sheetEl || sheetEl.hidden) return;
        setSnap('peek');
      },
      resize: function () {
        if (map) map.container.fitToViewport();
      },
    };
  }

  global.IceMap = { mount: mount, loadYmaps: loadYmaps };
})(typeof window !== 'undefined' ? window : this);
