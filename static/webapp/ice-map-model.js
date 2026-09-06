/**
 * TASK-054 Ice tab Yandex map — pure view-model (no DOM, no ymaps).
 * Browser: window.IceMapModel. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.IceMapModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var PLACEHOLDER_API_KEY = 'YOUR_YANDEX_MAPS_JS_API_KEY';
  var YMAPS_SCRIPT = 'https://api-maps.yandex.ru/2.1/';
  var nearMePolicy = { geolocateOnStart: false, geolocateOnButton: true };

  function pluralRu(n, one, few, many) {
    var abs = Math.abs(n) % 100;
    if (abs >= 11 && abs <= 14) return many;
    var last = abs % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  function trimStr(v) {
    return v == null ? '' : String(v).trim();
  }

  function resolveApiKey(sources) {
    sources = sources || {};
    var query = sources.query || {};
    var env = sources.env || {};
    var candidates = [sources.key, query.apikey, sources.windowKey, env.YANDEX_MAPS_JS_API_KEY];
    var i;
    for (i = 0; i < candidates.length; i++) {
      var v = trimStr(candidates[i]);
      if (v && v !== PLACEHOLDER_API_KEY) return v;
    }
    return '';
  }

  function scriptUrl(apiKey) {
    var key = trimStr(apiKey);
    if (!key || key === PLACEHOLDER_API_KEY) return '';
    return YMAPS_SCRIPT + '?apikey=' + encodeURIComponent(key) + '&lang=ru_RU';
  }

  function missingKeyState() {
    return {
      canRenderMap: false,
      fallback: 'none',
      title: 'Карта недоступна',
      body:
        'Нет ключа Yandex Maps JS API. Задайте переменную YANDEX_MAPS_JS_API_KEY ' +
        'или откройте прототип с ?apikey=… Запасной карты нет.',
    };
  }

  function chooseMapProvider(sources) {
    var key = resolveApiKey(sources);
    if (!key) {
      var empty = missingKeyState();
      return {
        provider: 'none',
        fallback: empty.fallback,
        canRenderMap: false,
        title: empty.title,
        body: empty.body,
      };
    }
    return { provider: 'yandex', fallback: 'none', canRenderMap: true };
  }

  function cityWithoutArenasState() {
    return {
      title: 'В этом городе пока нет катков',
      body: 'Смените город или откройте чип «Тренеры» — пустую карту не показываем как «всё в порядке».',
    };
  }

  function coachMapEmptyState() {
    return {
      title: 'Тренеров на карте нет',
      body: 'Смотрите список. Карта катков остаётся у чипов «Покататься» и «Группы».',
    };
  }

  function mapStartDecision(opts) {
    opts = opts || {};
    var provider = chooseMapProvider({ key: opts.key, query: opts.query, env: opts.env, windowKey: opts.windowKey });
    if (provider.provider !== 'yandex') {
      return {
        kind: 'missing-key',
        showMap: false,
        provider: 'none',
        fallback: 'none',
        empty: missingKeyState(),
      };
    }
    if (trimStr(opts.intent) === 'coach') {
      return {
        kind: 'coach',
        showMap: false,
        provider: 'yandex',
        fallback: 'none',
        empty: coachMapEmptyState(),
      };
    }
    var items = opts.listItems || [];
    if (!items.length) {
      return {
        kind: 'no-arenas',
        showMap: false,
        provider: 'yandex',
        fallback: 'none',
        empty: cityWithoutArenasState(),
      };
    }
    return { kind: 'map', showMap: true, provider: 'yandex', fallback: 'none' };
  }

  function geoDeniedState() {
    return {
      blocksMap: false,
      title: 'Геолокация недоступна',
      body: 'Карта остаётся полезной — выберите каток на пине. Разрешите геолокацию, чтобы найти ближайший.',
    };
  }

  function afterGeoDenied(view) {
    view = view || {};
    var denied = geoDeniedState();
    return {
      blocksMap: false,
      keepStage: true,
      keepPins: true,
      keepSheet: view.sheetOpen !== false,
      fallback: 'none',
      title: denied.title,
      body: denied.body,
      pinCount: view.pinCount != null ? Number(view.pinCount) : 0,
    };
  }

  function noArenasNearState() {
    return {
      title: 'Рядом нет катков',
      body: 'В этой точке мы пока не нашли арен. Сдвиньте карту или смените город — пустую карту не показываем как «всё в порядке».',
    };
  }

  function bboxFetchPayload(opts) {
    opts = opts || {};
    var bbox = trimStr(opts.bbox);
    if (!bbox) return { fetch: false };
    var intent = trimStr(opts.intent) || 'skate';
    if (intent === 'coach') return { fetch: false };
    var limit = Number(opts.limit);
    if (!isFinite(limit) || limit <= 0) limit = 50;
    return {
      fetch: true,
      bbox: bbox,
      intent: intent,
      limit: limit,
    };
  }

  function pinSheetTarget(item) {
    var ref = (item && (item.slug || item.id)) || '';
    return {
      href: 'arena?ref=' + encodeURIComponent(String(ref)),
      opens: 'arena-card',
      yandexOrgCard: false,
    };
  }

  function hasCoords(item) {
    if (!item || item.on_map === false) return false;
    var lat = item.latitude;
    var lon = item.longitude;
    return lat != null && lon != null && isFinite(Number(lat)) && isFinite(Number(lon));
  }

  function splitMapAndList(items) {
    var list = items || [];
    var onMap = list.filter(hasCoords);
    return {
      list: list.slice(),
      onMap: onMap,
      offMapCount: list.length - onMap.length,
    };
  }

  function formatOffMapNote(count) {
    var n = Number(count) || 0;
    if (n <= 0) return '';
    var word = pluralRu(n, 'каток', 'катка', 'катков');
    return n + ' ' + word + ' без координат — только в списке';
  }

  function cellDegForZoom(zoom) {
    var z = Number(zoom);
    if (!isFinite(z)) z = 12;
    return 360 / Math.pow(2, z + 1);
  }

  function clusterArenas(items, opts) {
    opts = opts || {};
    var cell = Number(opts.cellDeg);
    if (!isFinite(cell) || cell <= 0) cell = cellDegForZoom(12);
    var buckets = {};
    var order = [];
    (items || []).forEach(function (item) {
      if (!hasCoords(item)) return;
      var lat = Number(item.latitude);
      var lon = Number(item.longitude);
      var key = Math.round(lat / cell) + ':' + Math.round(lon / cell);
      if (!buckets[key]) {
        buckets[key] = [];
        order.push(key);
      }
      buckets[key].push(item);
    });
    return order.map(function (key) {
      var group = buckets[key];
      if (group.length === 1) {
        return { type: 'pin', item: group[0], count: 1, latitude: Number(group[0].latitude), longitude: Number(group[0].longitude) };
      }
      var sumLat = 0;
      var sumLon = 0;
      group.forEach(function (it) {
        sumLat += Number(it.latitude);
        sumLon += Number(it.longitude);
      });
      return {
        type: 'cluster',
        count: group.length,
        items: group,
        latitude: sumLat / group.length,
        longitude: sumLon / group.length,
      };
    });
  }

  function shortArenaName(name) {
    var s = trimStr(name);
    var quoted = s.match(/[«"]([^»"]+)[»"]/);
    if (quoted && quoted[1]) return quoted[1];
    return s.replace(/^Каток\s+/i, '').slice(0, 18);
  }

  function sessionTime(item) {
    var live = (item && item.live) || {};
    var fromLive = trimStr(live.starts_at_local);
    if (fromLive) return fromLive;
    var text = trimStr(live.text || (item && item.live_line));
    var m = text.match(/\b(\d{1,2}:\d{2})\b/);
    return m ? m[1] : '';
  }

  function pinTone(item) {
    var tier = String((item && item.tier) || 'C').toUpperCase();
    if (tier === 'A') return 'a';
    if (tier === 'B') return 'b';
    return 'c';
  }

  function pinView(item) {
    var tone = pinTone(item);
    var label = '';
    if (tone === 'a') {
      var short = shortArenaName(item && item.name);
      var time = sessionTime(item);
      if (short && time) label = short + ' · ' + time;
      else label = short;
    }
    return {
      tone: tone,
      muted: tone === 'c',
      label: label,
      shortName: shortArenaName(item && item.name),
    };
  }

  function fmtCoord(n) {
    var x = Number(n);
    if (!isFinite(x)) return '';
    return String(x);
  }

  function boundsToBbox(bounds) {
    var minLat;
    var minLon;
    var maxLat;
    var maxLon;
    if (!bounds) return '';
    if (Array.isArray(bounds) && bounds.length >= 2 && Array.isArray(bounds[0])) {
      minLat = Number(bounds[0][0]);
      minLon = Number(bounds[0][1]);
      maxLat = Number(bounds[1][0]);
      maxLon = Number(bounds[1][1]);
    } else if (bounds.minLat != null) {
      minLat = Number(bounds.minLat);
      minLon = Number(bounds.minLon);
      maxLat = Number(bounds.maxLat);
      maxLon = Number(bounds.maxLon);
    } else {
      return '';
    }
    if (minLat > maxLat) {
      var tLat = minLat;
      minLat = maxLat;
      maxLat = tLat;
    }
    if (minLon > maxLon) {
      var tLon = minLon;
      minLon = maxLon;
      maxLon = tLon;
    }
    return [fmtCoord(minLat), fmtCoord(minLon), fmtCoord(maxLat), fmtCoord(maxLon)].join(',');
  }

  function bboxKey(bbox) {
    return String(bbox || '')
      .split(',')
      .map(function (p) {
        var n = Number(p);
        return isFinite(n) ? n.toFixed(4) : String(p);
      })
      .join(',');
  }

  function planBboxFetch(prev, bbox) {
    var next = trimStr(bbox);
    if (!next) return { fetch: false, bbox: prev && prev.bbox ? prev.bbox : '', prev: prev };
    if (prev && prev.bbox && bboxKey(prev.bbox) === bboxKey(next)) {
      return { fetch: false, bbox: prev.bbox, prev: prev };
    }
    return { fetch: true, bbox: next, prev: prev || null };
  }

  function formatDistanceKm(km) {
    if (km == null || km === '' || isNaN(Number(km))) return '';
    var n = Number(km);
    var text = Number.isInteger(n) ? String(n) : n.toFixed(1).replace('.', ',');
    return text + ' км';
  }

  function sortByDistance(items) {
    return (items || []).slice().sort(function (a, b) {
      var da = a && a.distance_km;
      var db = b && b.distance_km;
      var aMiss = da == null || isNaN(Number(da));
      var bMiss = db == null || isNaN(Number(db));
      if (aMiss && bMiss) return 0;
      if (aMiss) return 1;
      if (bMiss) return -1;
      return Number(da) - Number(db);
    });
  }

  function formatSheetMeta(item, opts) {
    opts = opts || {};
    var parts = [];
    if (item && item.district) parts.push(String(item.district));
    var dist = formatDistanceKm(item && item.distance_km);
    if (dist) parts.push(dist);
    if (opts.nearest) parts.push('ближайший каток');
    return parts.join(' · ');
  }

  function pickNearest(items) {
    var mapped = (items || []).filter(hasCoords);
    var withDist = mapped.filter(function (it) {
      return it.distance_km != null && !isNaN(Number(it.distance_km));
    });
    var best = withDist.length ? sortByDistance(withDist)[0] : mapped[0] || null;
    if (!best) return null;
    return Object.assign({}, best, { sheetMeta: formatSheetMeta(best, { nearest: true }) });
  }

  return {
    PLACEHOLDER_API_KEY: PLACEHOLDER_API_KEY,
    nearMePolicy: nearMePolicy,
    resolveApiKey: resolveApiKey,
    scriptUrl: scriptUrl,
    missingKeyState: missingKeyState,
    chooseMapProvider: chooseMapProvider,
    cityWithoutArenasState: cityWithoutArenasState,
    coachMapEmptyState: coachMapEmptyState,
    mapStartDecision: mapStartDecision,
    geoDeniedState: geoDeniedState,
    afterGeoDenied: afterGeoDenied,
    noArenasNearState: noArenasNearState,
    bboxFetchPayload: bboxFetchPayload,
    pinSheetTarget: pinSheetTarget,
    hasCoords: hasCoords,
    splitMapAndList: splitMapAndList,
    formatOffMapNote: formatOffMapNote,
    cellDegForZoom: cellDegForZoom,
    clusterArenas: clusterArenas,
    shortArenaName: shortArenaName,
    pinView: pinView,
    boundsToBbox: boundsToBbox,
    planBboxFetch: planBboxFetch,
    formatDistanceKm: formatDistanceKm,
    formatSheetMeta: formatSheetMeta,
    sortByDistance: sortByDistance,
    pickNearest: pickNearest,
  };
});
