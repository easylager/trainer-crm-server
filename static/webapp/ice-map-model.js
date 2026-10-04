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
      body: 'Смотрите список. Карта площадок остаётся у чипов «Где заниматься» и «Группы».',
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
    var onMap = splitMapAndList(items).onMap;
    if (!onMap.length) {
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
      cityId: opts.cityId != null && opts.cityId !== '' ? opts.cityId : null,
    };
  }

  function pinSheetTarget(item) {
    // id важнее slug: slug уникален только в городе (TASK-146).
    var ref = (item && (item.id != null ? item.id : item.slug)) || '';
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

  /*
   * City-wide bounds come from /api/public/ice/cities (min/max lat/lon over ALL
   * geocoded arenas in the city, independent of session status) — same shape the
   * backend returns: { min_lat, max_lat, min_lon, max_lon }. Anything else (missing
   * keys, non-finite, inverted) is treated as "no city bounds available".
   */
  function normalizeCityBounds(raw) {
    if (!raw) return null;
    var minLat = Number(raw.min_lat);
    var maxLat = Number(raw.max_lat);
    var minLon = Number(raw.min_lon);
    var maxLon = Number(raw.max_lon);
    if (![minLat, maxLat, minLon, maxLon].every(isFinite)) return null;
    if (minLat > maxLat || minLon > maxLon) return null;
    return { minLat: minLat, maxLat: maxLat, minLon: minLon, maxLon: maxLon };
  }

  function cityCameraFromItems(items, opts) {
    opts = opts || {};
    var pad = Number(opts.padDeg);
    if (!isFinite(pad) || pad <= 0) pad = 0.08;
    // Floor ≈ Minsk (~24×27 km). Only kicks in when neither the pin hull nor the
    // city-wide bounds below produce anything bigger — e.g. a brand new city with
    // zero (or one) geocoded arenas. For Moscow/SPb the city-wide bounds already
    // dwarf this floor, so it stops winning there — see TASK city-wide-camera-bounds.
    var minLatSpan = 0.22;
    var minLonSpan = 0.42;
    var onMap = splitMapAndList(items).onMap;
    var fallback = opts.fallbackCenter;
    if (!fallback || !isFinite(Number(fallback[0])) || !isFinite(Number(fallback[1]))) {
      fallback = null;
    }
    var cityBounds = normalizeCityBounds(opts.cityBounds);
    var minLat;
    var maxLat;
    var minLon;
    var maxLon;
    var haveBox = false;
    if (onMap.length) {
      var lats = onMap.map(function (it) {
        return Number(it.latitude);
      });
      var lons = onMap.map(function (it) {
        return Number(it.longitude);
      });
      minLat = Math.min.apply(null, lats) - pad;
      maxLat = Math.max.apply(null, lats) + pad;
      minLon = Math.min.apply(null, lons) - pad;
      maxLon = Math.max.apply(null, lons) + pad;
      haveBox = true;
    }
    if (cityBounds) {
      // City-wide bounds are the camera's FRAMING only — what pins actually render
      // stays exactly the intent-filtered `onMap` list above. Padded the same way,
      // then unioned with the (possibly empty) pin hull so pins are never clipped.
      var cMinLat = cityBounds.minLat - pad;
      var cMaxLat = cityBounds.maxLat + pad;
      var cMinLon = cityBounds.minLon - pad;
      var cMaxLon = cityBounds.maxLon + pad;
      if (haveBox) {
        minLat = Math.min(minLat, cMinLat);
        maxLat = Math.max(maxLat, cMaxLat);
        minLon = Math.min(minLon, cMinLon);
        maxLon = Math.max(maxLon, cMaxLon);
      } else {
        minLat = cMinLat;
        maxLat = cMaxLat;
        minLon = cMinLon;
        maxLon = cMaxLon;
        haveBox = true;
      }
    }
    if (!haveBox) {
      if (fallback) {
        minLat = Number(fallback[0]) - minLatSpan / 2;
        maxLat = Number(fallback[0]) + minLatSpan / 2;
        minLon = Number(fallback[1]) - minLonSpan / 2;
        maxLon = Number(fallback[1]) + minLonSpan / 2;
      } else {
        return null;
      }
    }
    if (maxLat - minLat < minLatSpan) {
      var midLat = (minLat + maxLat) / 2;
      minLat = midLat - minLatSpan / 2;
      maxLat = midLat + minLatSpan / 2;
    }
    if (maxLon - minLon < minLonSpan) {
      var midLon = (minLon + maxLon) / 2;
      minLon = midLon - minLonSpan / 2;
      maxLon = midLon + minLonSpan / 2;
    }
    return {
      center: [(minLat + maxLat) / 2, (minLon + maxLon) / 2],
      zoom: 10,
      restrict: [
        [minLat, minLon],
        [maxLat, maxLon],
      ],
      minZoom: 9,
      maxZoom: 16,
    };
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

  /**
   * Карусель шторки пуста, но выдача есть — объясняем почему и даём выход в список.
   */
  function sheetRailEmptyState(opts) {
    opts = opts || {};
    var list = opts.listItems || [];
    var pins = opts.mapItems || [];
    if (splitMapAndList(pins).onMap.length > 0) return null;

    var catalog = String(opts.catalogScope || 'places');
    var listSplit = splitMapAndList(list);
    var pinSplit = splitMapAndList(pins);
    var total = Math.max(list.length, pins.length);
    if (total <= 0) {
      return {
        title: 'Нет мест на карте',
        body: 'Попробуйте другой фильтр или город',
        action: null,
      };
    }

    if (listSplit.onMap.length === 0 && listSplit.offMapCount > 0) {
      return {
        title: 'На карте пока нет точек',
        body: 'Адреса уточняем — смотрите в списке',
        action: { label: 'Открыть список', kind: 'list' },
      };
    }

    if (pins.length > 0 && pinSplit.onMap.length === 0) {
      return {
        title: 'В этой области пусто',
        body: 'Сдвиньте карту или откройте список',
        action: { label: 'Списком', kind: 'list' },
      };
    }

    if (catalog === 'shop') {
      return {
        title: 'Магазины без координат',
        body: 'Откройте список — там полные адреса',
        action: { label: 'Открыть список', kind: 'list' },
      };
    }

    return {
      title: 'Подвиньте карту',
      body: 'Здесь нет мест из вашего фильтра',
      action: { label: 'Списком', kind: 'list' },
    };
  }

  function pinLayerSignature(onMap) {
    return (onMap || [])
      .map(function (item) {
        var live = (item && item.live) || {};
        return (
          String(item.id) +
          ':' +
          String(live.starts_at_local || live.text || '') +
          ':' +
          String((item && item.tier) || '')
        );
      })
      .sort()
      .join('|');
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

  /*
   * TASK-147 (хвост к макету 02): тип места = цвет пина и точка легенды.
   * Ключи и подписи — словарь сервера (src/shared/venue_types.py); подпись
   * с сервера (item.venue_chip) важнее, таблица — запас для старого ответа API.
   * Цвета — только токены theme.css: новых hex нет. Улица (outdoor) — это ЛЁД
   * (SKATING_VENUE_TYPES на сервере: «уличный каток — тоже лёд»), поэтому цвет льда,
   * а в легенде она сводится с льдом в одну запись «Лёд»: две одинаковые точки
   * ничего не объясняют. Хореозал делит цвет с залом, «другое» — графит.
   * «Трассы» отдельным типом в данных нет — её нет и в легенде.
   */
  var VENUE_ORDER = ['ice', 'gym', 'choreo', 'pool', 'shop', 'other'];
  var VENUE_LABEL = {
    ice: 'Лёд',
    outdoor: 'Улица',
    gym: 'Зал',
    choreo: 'Хореография',
    pool: 'Бассейн',
    shop: 'Магазин',
    other: 'Другое',
  };
  var VENUE_TOKEN = {
    ice: '--app-venue-ice',
    outdoor: '--app-venue-ice',
    gym: '--app-venue-gym',
    choreo: '--app-venue-gym',
    pool: '--app-venue-pool',
    shop: '--app-venue-shop',
    other: '--app-venue-service',
  };
  // Где бывают публичные сеансы льда (SKATING_VENUE_TYPES на сервере).
  var SESSION_VENUES = ['ice', 'outdoor'];

  /* Неизвестный или пустой тип — лёд, как на сервере (normalize_venue_type). */
  function venueKey(item) {
    var raw = trimStr(item && item.venue_type).toLowerCase();
    return VENUE_LABEL.hasOwnProperty(raw) ? raw : 'ice';
  }

  /* Запись легенды: улица сводится ко льду (тот же цвет — одна точка на оба типа). */
  function legendKey(item) {
    var key = venueKey(item);
    return key === 'outdoor' ? 'ice' : key;
  }

  /*
   * Легенда карты: только типы, что реально есть среди нарисованных пинов.
   * Меньше двух записей — легенда не нужна (одна точка ничего не объясняет), поэтому
   * show=false. Порядок фиксированный, чтобы легенда не прыгала от пана к пану.
   * Подпись записи «Лёд» берётся у настоящего льда, а не у улицы («Улица» ≠ «Лёд»).
   */
  function legendView(items) {
    var seen = {};
    splitMapAndList(items).onMap.forEach(function (item) {
      var key = legendKey(item);
      var own = venueKey(item) === key ? trimStr(item.venue_chip) : '';
      if (!seen.hasOwnProperty(key) || (own && seen[key] === VENUE_LABEL[key])) {
        seen[key] = own || VENUE_LABEL[key];
      }
    });
    var entries = VENUE_ORDER.filter(function (key) {
      return seen.hasOwnProperty(key);
    }).map(function (key) {
      return { key: key, label: seen[key], token: VENUE_TOKEN[key] };
    });
    return { show: entries.length >= 2, entries: entries };
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

  /*
   * TASK-147: время СЕАНСА В ВЫБРАННОМ ОКНЕ. Сеанс вне окна не считается
   * ответом ни для пина, ни для кластера, ни для карусели — иначе «19:30»
   * под чипом «Завтра» читается как завтрашние 19:30 (урок TASK-146).
   */
  function liveTime(item) {
    if (item && item.live && item.live.outside_window) return '';
    // TASK-147: время — только у льда. У зала/магазина live.text — часы работы
    // («10:00–20:00»), а не сеанс; вытащенное регэкспом «10:00» выдавало бы
    // график за расписание.
    if (SESSION_VENUES.indexOf(venueKey(item)) < 0) return '';
    return sessionTime(item);
  }

  function pinTone(item) {
    var tier = String((item && item.tier) || 'C').toUpperCase();
    if (tier === 'A') return 'a';
    if (tier === 'B') return 'b';
    return 'c';
  }

  function pinView(item, opts) {
    opts = opts || {};
    var tone = pinTone(item);
    var off = !!(item && item.live && item.live.outside_window);
    var time = liveTime(item);
    var shortName = shortArenaName(item && item.name);
    var venue = venueKey(item);
    // Магазины: не «сеанс в окне», а точка на карте. Полая серая точка — для льда.
    if (venue === 'shop') {
      return {
        tone: tone,
        muted: false,
        when: 'in',
        kind: 'place',
        time: '',
        shortName: shortName,
        venue: venue,
        selected: !!opts.selected,
        label: shortName,
      };
    }
    // Пилюля как у магазинов: время сеанса или короткое имя; цвет — тип места.
    var label = time || shortName;
    return {
      tone: tone,
      muted: (tone === 'c' && !time) || off,
      when: off ? 'off' : 'in',
      kind: 'place',
      time: time,
      shortName: shortName,
      venue: venue,
      selected: !!opts.selected,
      label: label,
    };
  }

  function clusterSummary(items) {
    var list = items || [];
    if (
      list.length &&
      list.every(function (item) {
        return venueKey(item) === 'shop';
      })
    ) {
      return {
        count: list.length,
        hasHits: true,
        minTime: '',
        label: 'магазины',
      };
    }
    var hits = 0;
    var minTime = '';
    list.forEach(function (item) {
      var t = liveTime(item);
      if (t && /^\d{1,2}:\d{2}$/.test(t)) {
        hits++;
        if (!minTime || t < minTime) minTime = t;
      }
    });
    return {
      count: list.length,
      hasHits: hits > 0,
      minTime: minTime,
      label: minTime ? 'с ' + minTime : hits ? 'места' : 'нет сеансов',
    };
  }

  function railOrder(items) {
    var list = items || [];
    var hits = [];
    var rest = [];
    list.forEach(function (item) {
      var t = liveTime(item);
      if (t && /^\d{1,2}:\d{2}$/.test(t)) hits.push(item);
      else rest.push(item);
    });
    hits.sort(function (a, b) {
      return liveTime(a).localeCompare(liveTime(b));
    });
    return hits.concat(rest);
  }

  function sheetSummary(items, window) {
    var list = items || [];
    var venues = list.filter(function (item) {
      return String(item.venue_type || 'ice') !== 'shop';
    });
    var shopCount = list.length - venues.length;
    var sessions = 0;
    venues.forEach(function (item) {
      var t = liveTime(item);
      if (t && /^\d{1,2}:\d{2}$/.test(t)) sessions++;
    });
    var whenLabel = '';
    if (window && window.label) whenLabel = window.label;
    else if (window && window.key) {
      var labels = {
        now: 'сейчас',
        evening: 'сегодня вечером',
        tomorrow: 'завтра',
        weekend: 'в выходные',
      };
      whenLabel = labels[window.key] || '';
    }
    var parts = [];
    if (venues.length) {
      var placeWord = pluralRu(venues.length, 'место', 'места', 'мест');
      parts.push(venues.length + ' ' + placeWord + (whenLabel ? ' ' + whenLabel : ''));
    }
    if (sessions) {
      var sessionWord = pluralRu(sessions, 'сеанс', 'сеанса', 'сеансов');
      parts.push(sessions + ' ' + sessionWord);
    }
    if (shopCount) {
      var shopWord = pluralRu(shopCount, 'магазин', 'магазина', 'магазинов');
      if (venues.length || sessions) {
        parts.push('ещё ' + shopCount + ' ' + shopWord);
      } else {
        parts.push(shopCount + ' ' + shopWord);
      }
    }
    return parts.join(' · ');
  }

  function snapFor(heightPx, snaps) {
    var best = null;
    var bestDist = Infinity;
    Object.keys(snaps || {}).forEach(function (key) {
      var dist = Math.abs(snaps[key] - heightPx);
      if (dist < bestDist) {
        bestDist = dist;
        best = key;
      }
    });
    return best;
  }

  function fmtCoord(n) {
    var x = Number(n);
    if (!isFinite(x)) return '';
    return String(x);
  }

  function bboxExceedsCity(bbox) {
    var parts = String(bbox || '').split(',');
    if (parts.length < 4) return false;
    var minLat = Number(parts[0]);
    var minLon = Number(parts[1]);
    var maxLat = Number(parts[2]);
    var maxLon = Number(parts[3]);
    if (![minLat, minLon, maxLat, maxLon].every(isFinite)) return false;
    return maxLat - minLat > 2 || maxLon - minLon > 3;
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


  /**
   * Тап по кластеру. Стандартный зум Яндекса вписывает в экран сами точки и не знает,
   * что над точкой висит ярлык «Название · 19:30» (~140px), а поверх карты — «Рядом со
   * мной» и +/−. Поэтому крайние места кластера уезжали за край или под кнопки.
   *
   * Решение: вписываем с полями под ярлыки и кнопки и не зумим глубже `maxZoom`.
   * Если места стоят почти в одной точке (ТЦ, один комплекс), зум их всё равно не
   * разведёт: возвращаем `list` — показать места карточками, камеру не трогать.
   */
  var CLUSTER_SAME_SPOT_DEG = 0.0006; // ≈ 60 м: один комплекс, зумом не развести
  var CLUSTER_MAX_ZOOM = 16;
  var SINGLE_PLACE_PAD_DEG = 0.0018;

  function singlePlaceFocus(place, opts) {
    opts = opts || {};
    if (!place || !hasCoords(place)) return null;
    var lat = Number(place.latitude);
    var lon = Number(place.longitude);
    if (!isFinite(lat) || !isFinite(lon)) return null;
    var d = SINGLE_PLACE_PAD_DEG;
    return {
      bounds: [[lat - d, lon - d], [lat + d, lon + d]],
      margin: opts.margin || [110, 80, 48, 80],
    };
  }

  function clusterFocus(points, opts) {
    opts = opts || {};
    var pts = (points || []).filter(function (p) {
      return p && isFinite(Number(p[0])) && isFinite(Number(p[1]));
    });
    if (!pts.length) return { mode: 'none' };
    var lats = pts.map(function (p) { return Number(p[0]); });
    var lons = pts.map(function (p) { return Number(p[1]); });
    var minLat = Math.min.apply(null, lats);
    var maxLat = Math.max.apply(null, lats);
    var minLon = Math.min.apply(null, lons);
    var maxLon = Math.max.apply(null, lons);
    if (maxLat - minLat < CLUSTER_SAME_SPOT_DEG && maxLon - minLon < CLUSTER_SAME_SPOT_DEG) {
      return { mode: 'list' };
    }
    var cap = Number(opts.maxZoom);
    return {
      mode: 'zoom',
      bounds: [[minLat, minLon], [maxLat, maxLon]],
      // [top, right, bottom, left]: сверху ярлык пина, снизу — шторка (TASK-147
      // передаёт свою высоту через opts.margin), справа/слева — края экрана.
      margin: opts.margin || [110, 80, 48, 80],
      maxZoom: isFinite(cap) && cap > 0 ? Math.min(cap, CLUSTER_MAX_ZOOM) : CLUSTER_MAX_ZOOM,
    };
  }

  return {
    clusterFocus: clusterFocus,
    singlePlaceFocus: singlePlaceFocus,
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
    sheetRailEmptyState: sheetRailEmptyState,
    pinLayerSignature: pinLayerSignature,
    cellDegForZoom: cellDegForZoom,
    clusterArenas: clusterArenas,
    shortArenaName: shortArenaName,
    pinView: pinView,
    venueKey: venueKey,
    legendView: legendView,
    VENUE_TOKEN: VENUE_TOKEN,
    clusterSummary: clusterSummary,
    railOrder: railOrder,
    sheetSummary: sheetSummary,
    snapFor: snapFor,
    pluralRu: pluralRu,
    boundsToBbox: boundsToBbox,
    normalizeCityBounds: normalizeCityBounds,
    cityCameraFromItems: cityCameraFromItems,
    bboxExceedsCity: bboxExceedsCity,
    planBboxFetch: planBboxFetch,
    formatDistanceKm: formatDistanceKm,
    formatSheetMeta: formatSheetMeta,
    sortByDistance: sortByDistance,
    pickNearest: pickNearest,
  };
});
