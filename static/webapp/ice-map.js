/**
 * TASK-054 Ice tab — in-place Yandex Maps (clusters, bbox, near-me, our sheet).
 * Never opens a Yandex org card. OSM/Leaflet are not a fallback.
 */
(function (global) {
  'use strict';

  var MM = global.IceMapModel;
  var ymapsLoad = null;
  var MINSK = [53.902496, 27.561481];

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

  function defaultGetKey() {
    var fromWindow = MM.resolveApiKey({ windowKey: global.YANDEX_MAPS_JS_API_KEY });
    if (fromWindow) return Promise.resolve(fromWindow);
    return fetch('/api/public/ice/map-config', { cache: 'no-store' })
      .then(function (r) {
        return r.ok ? r.json() : {};
      })
      .then(function (data) {
        return MM.resolveApiKey({
          env: { YANDEX_MAPS_JS_API_KEY: data && data.yandex_maps_js_api_key },
        });
      })
      .catch(function () {
        return '';
      });
  }

  function liveText(item) {
    return (item && item.live && item.live.text) || (item && item.live_line) || '';
  }

  function renderEmpty(el, state) {
    if (!el) return;
    el.hidden = false;
    el.innerHTML =
      '<div class="ice-empty"><b>' + esc(state.title) + '</b><p>' + esc(state.body) + '</p></div>';
  }

  function hideEmpty(el) {
    if (!el) return;
    el.hidden = true;
    el.innerHTML = '';
  }

  function sheetHtml(item, meta, href) {
    var tone = (global.IceTabModel && global.IceTabModel.liveTone(item)) || MM.pinView(item).tone;
    var tier = String(item.tier || 'C').toUpperCase();
    var thumb = item.thumb
      ? ' style="background-image:url(\'' + esc(item.thumb).replace(/'/g, '%27') + '\')"'
      : '';
    var phClass = 'ice-acard__ph' + (item.thumb ? '' : ' ice-acard__ph--empty');
    return (
      '<button type="button" class="ice-acard ice-acard--sheet" data-href="' +
      esc(href || '') +
      '"><span class="' +
      phClass +
      '"' +
      thumb +
      '></span><span class="ice-acard__body"><span class="ice-acard__name">' +
      esc(item.name) +
      '<span class="ice-tier ice-tier--' +
      tone +
      '">' +
      esc(tier) +
      '</span></span><span class="ice-acard__meta">' +
      esc(meta) +
      '</span><span class="ice-live ice-live--' +
      tone +
      '">' +
      esc(liveText(item)) +
      '</span></span></button>'
    );
  }

  function mount(opts) {
    opts = opts || {};
    var canvas = opts.canvas;
    var emptyEl = opts.emptyEl;
    var sheetEl = opts.sheetEl;
    var nearBtn = opts.nearBtn;
    var offMapEl = opts.offMapEl;
    var stageEl = opts.stageEl;
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
    var boundsTimer = null;
    var ignoreBounds = false;
    var started = false;
    var userPlacemark = null;

    function getIntent() {
      return opts.getIntent ? opts.getIntent() : 'skate';
    }

    function getCityId() {
      return opts.getCityId ? opts.getCityId() : null;
    }

    function listUrl(extra) {
      return opts.listUrl(extra);
    }

    function fetchJson(url) {
      return opts.fetchJson(url);
    }

    function arenaHref(item) {
      if (opts.arenaHref) return opts.arenaHref(item);
      if (global.IceTabModel) return global.IceTabModel.arenaHref(item);
      return '';
    }

    function showStage(on) {
      if (stageEl) stageEl.hidden = !on;
      if (nearBtn) nearBtn.hidden = !on;
    }

    function setOffMapNote() {
      if (!offMapEl) return;
      var split = MM.splitMapAndList(listItems);
      var note = MM.formatOffMapNote(split.offMapCount);
      offMapEl.textContent = note;
      offMapEl.hidden = !note;
    }

    function paintSheet(item, asNearest) {
      selected = item || null;
      nearestMode = !!asNearest;
      if (!sheetEl) return;
      if (!item) {
        sheetEl.innerHTML = '';
        return;
      }
      var meta = MM.formatSheetMeta(item, { nearest: asNearest });
      if (!meta && global.IceTabModel) meta = global.IceTabModel.formatMeta(item);
      sheetEl.innerHTML = sheetHtml(item, meta, arenaHref(item));
    }

    function defaultSheet() {
      if (selected && mapItems.some(function (it) { return it.id === selected.id; })) {
        paintSheet(selected, nearestMode);
        return;
      }
      var nearest = MM.pickNearest(mapItems.length ? mapItems : MM.splitMapAndList(listItems).onMap);
      paintSheet(nearest, !!(nearest && nearest.distance_km != null));
    }

    function syncObjects() {
      if (!clusterer || !ymaps) return;
      clusterer.removeAll();
      var marks = MM.splitMapAndList(mapItems).onMap.map(function (item) {
        var view = MM.pinView(item);
        var pm = new ymaps.Placemark(
          [Number(item.latitude), Number(item.longitude)],
          {
            tone: view.tone,
            label: view.label,
            muted: view.muted,
            arenaId: item.id,
          },
          {
            iconLayout: PinLayout,
            iconOffset: [-8, -28],
            iconShape: {
              type: 'Rectangle',
              coordinates: [
                [-70, -36],
                [70, 6],
              ],
            },
            hasBalloon: false,
            openBalloonOnClick: false,
            hasHint: false,
          }
        );
        pm.events.add('click', function (ev) {
          if (ev && ev.preventDefault) ev.preventDefault();
          paintSheet(item, false);
        });
        return pm;
      });
      clusterer.add(marks);
    }

    function fetchViewport() {
      if (!map || !opts.listUrl) return;
      var bbox = MM.boundsToBbox(map.getBounds());
      var plan = MM.planBboxFetch(bboxState, bbox);
      if (!plan.fetch) return;
      bboxState = plan;
      var extra = { bbox: bbox, intent: getIntent(), limit: 50 };
      var cityId = getCityId();
      if (cityId != null) extra.cityId = cityId;
      fetchJson(listUrl(extra)).then(function (data) {
        mapItems = (data && data.items) || [];
        syncObjects();
        defaultSheet();
      });
    }

    function onBoundsChange() {
      if (ignoreBounds) return;
      global.clearTimeout(boundsTimer);
      boundsTimer = global.setTimeout(fetchViewport, 320);
    }

    function fitCity() {
      if (!map) return;
      var onMap = MM.splitMapAndList(listItems).onMap;
      ignoreBounds = true;
      var done = function () {
        global.setTimeout(function () {
          ignoreBounds = false;
          fetchViewport();
        }, 80);
      };
      if (onMap.length >= 2) {
        var bounds = onMap.map(function (it) {
          return [Number(it.latitude), Number(it.longitude)];
        });
        map.setBounds(bounds, { checkZoomRange: true, zoomMargin: 48 }).then(function () {
          if (map.getZoom() > 14) map.setZoom(14);
          done();
        }, done);
        return;
      }
      if (onMap.length === 1) {
        map.setCenter([Number(onMap[0].latitude), Number(onMap[0].longitude)], 13);
        done();
        return;
      }
      map.setCenter(MINSK, 12);
      done();
    }

    function buildLayouts() {
      PinLayout = ymaps.templateLayoutFactory.createClass(
        '<div class="ice-ypin ice-ypin--$[properties.tone]">' +
          '<b class="ice-ypin__label">$[properties.label]</b>' +
          '<i class="ice-ypin__dot"></i></div>'
      );
      ClusterLayout = ymaps.templateLayoutFactory.createClass(
        '<div class="ice-ycluster">{{ properties.geoObjects.length }}</div>'
      );
    }

    function createMap() {
      if (map || !canvas) return;
      buildLayouts();
      map = new ymaps.Map(
        canvas,
        {
          center: MINSK,
          zoom: 12,
          controls: ['zoomControl'],
        },
        {
          yandexMapDisablePoiInteractivity: true,
          suppressMapOpenBlock: true,
          suppressObsoleteBrowserNotifier: true,
        }
      );
      if (map.controls && map.controls.get('zoomControl')) {
        map.controls.get('zoomControl').options.set({ size: 'small', position: { right: 10, top: 54 } });
      }
      clusterer = new ymaps.Clusterer({
        minClusterSize: 2,
        gridSize: 64,
        clusterDisableClickZoom: false,
        clusterOpenBalloonOnClick: false,
        hasBalloon: false,
        clusterHasBalloon: false,
        groupByCoordinates: false,
        clusterIconLayout: ClusterLayout,
        clusterIconOffset: [-19, -19],
        clusterIconShape: { type: 'Circle', coordinates: [0, 0], radius: 19 },
      });
      clusterer.options.set({ hasBalloon: false, clusterOpenBalloonOnClick: false });
      map.geoObjects.add(clusterer);
      map.events.add('boundschange', onBoundsChange);
    }

    function showMissing() {
      showStage(false);
      renderEmpty(emptyEl, MM.missingKeyState());
    }

    function start() {
      if (started) {
        if (map) {
          map.container.fitToViewport();
          fetchViewport();
        }
        return Promise.resolve();
      }
      started = true;
      var getKey = opts.getKey || defaultGetKey;
      return Promise.resolve(getKey())
        .then(function (key) {
          var resolved = MM.resolveApiKey({ key: key });
          if (!resolved) {
            showMissing();
            return;
          }
          return loadYmaps(resolved).then(function (api) {
            ymaps = api;
            hideEmpty(emptyEl);
            showStage(true);
            createMap();
            mapItems = MM.splitMapAndList(listItems).onMap.slice();
            syncObjects();
            fitCity();
          });
        })
        .catch(function () {
          showMissing();
        });
    }

    function onNearClick() {
      if (!nearMePolicyOk()) return;
      if (!navigator.geolocation) {
        paintGeoNote(MM.geoDeniedState());
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
            var items = (data && data.items) || [];
            if (typeof opts.onNearList === 'function') opts.onNearList(data);
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
          paintGeoNote(MM.geoDeniedState());
        },
        { timeout: 8000, maximumAge: 30000 }
      );
    }

    function nearMePolicyOk() {
      return MM.nearMePolicy.geolocateOnButton && !MM.nearMePolicy.geolocateOnStart;
    }

    function paintGeoNote(state) {
      if (!sheetEl) return;
      sheetEl.innerHTML =
        '<div class="ice-empty"><b>' + esc(state.title) + '</b><p>' + esc(state.body) + '</p></div>';
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
        if (typeof opts.onOpenArena === 'function') {
          opts.onOpenArena(selected, href);
        }
      });
    }

    return {
      start: start,
      setListItems: function (items) {
        listItems = items || [];
        setOffMapNote();
        if (map && !mapItems.length) {
          mapItems = MM.splitMapAndList(listItems).onMap.slice();
          syncObjects();
        }
      },
      refresh: function () {
        bboxState = null;
        if (map) fetchViewport();
        else if (started) start();
      },
      resize: function () {
        if (map) map.container.fitToViewport();
      },
    };
  }

  global.IceMap = { mount: mount, loadYmaps: loadYmaps };
})(typeof window !== 'undefined' ? window : this);
