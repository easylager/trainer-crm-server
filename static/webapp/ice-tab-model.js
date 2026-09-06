/**
 * TASK-053 Ice tab — pure view-model (no DOM).
 * Browser: window.IceTabModel. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.IceTabModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var ICE_STATE_KEY = 'tcb_ice_tab_v1';
  var INTENTS = { skate: 'skate', coach: 'coach', group: 'group' };

  function pluralRu(n, one, few, many) {
    var abs = Math.abs(n) % 100;
    if (abs >= 11 && abs <= 14) return many;
    var last = abs % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  function buildListUrl(opts) {
    opts = opts || {};
    var intent = opts.intent || INTENTS.skate;
    if (intent !== INTENTS.skate && intent !== INTENTS.coach && intent !== INTENTS.group) {
      intent = INTENTS.skate;
    }
    var params = ['intent=' + encodeURIComponent(intent)];
    if (opts.cityId != null && opts.cityId !== '') {
      params.push('city_id=' + encodeURIComponent(String(opts.cityId)));
    }
    if (opts.near) params.push('near=' + encodeURIComponent(opts.near));
    if (opts.bbox) params.push('bbox=' + encodeURIComponent(opts.bbox));
    if (opts.limit) params.push('limit=' + encodeURIComponent(String(opts.limit)));
    if (opts.cursor) params.push('cursor=' + encodeURIComponent(String(opts.cursor)));
    return '/api/public/ice/arenas?' + params.join('&');
  }

  function buildSearchUrl(q, limit) {
    var params = ['q=' + encodeURIComponent(String(q || '').trim())];
    if (limit) params.push('limit=' + encodeURIComponent(String(limit)));
    return '/api/public/search?' + params.join('&');
  }

  function catalogHref() {
    return 'catalog?tab=catalog';
  }

  function mapHref() {
    return '';
  }

  function trainerHref(item) {
    var id = item && item.id;
    return catalogHref() + '&trainer_id=' + encodeURIComponent(String(id));
  }

  function arenaHref(item) {
    var ref = (item && (item.slug || item.id)) || '';
    return 'arena?ref=' + encodeURIComponent(String(ref));
  }

  function intentChipAction(intent) {
    if (intent === INTENTS.coach) {
      return { type: 'catalog', href: catalogHref() };
    }
    if (intent === INTENTS.group) {
      return { type: 'list', intent: INTENTS.group };
    }
    return { type: 'list', intent: INTENTS.skate };
  }

  function trainersMovedHint() {
    return 'Каталог тренеров теперь здесь — чип «Тренеры», в один тап.';
  }

  function formatDistanceKm(km) {
    if (km == null || km === '' || isNaN(Number(km))) return '';
    var n = Number(km);
    var text = Number.isInteger(n) ? String(n) : n.toFixed(1).replace('.', ',');
    return text + ' км';
  }

  function formatMeta(item) {
    item = item || {};
    var parts = [];
    if (item.district) parts.push(String(item.district));
    var dist = formatDistanceKm(item.distance_km);
    if (dist) parts.push(dist);
    if (item.closes_at) parts.push('до ' + item.closes_at);
    return parts.join(' · ');
  }

  function liveTone(item) {
    var tier = String((item && item.tier) || 'C').toUpperCase();
    if (tier === 'A') return 'a';
    if (tier === 'B') return 'b';
    return 'c';
  }

  function formatSortCaption(opts) {
    opts = opts || {};
    var total = Number(opts.total);
    if (isNaN(total)) total = (opts.items || []).length;
    var word = pluralRu(total, 'каток', 'катка', 'катков');
    var items = opts.items || [];
    var hasA = items.some(function (it) {
      return String(it.tier || '').toUpperCase() === 'A';
    });
    if (hasA) return total + ' ' + word + ' · сначала с актуальным расписанием';
    if (total === 0) return 'Пока нет катков · смените город или чип';
    return total + ' ' + word + ' · расписание уточняется';
  }

  var SEARCH_LABELS = { arena: 'Катки', trainer: 'Тренеры', city: 'Города' };

  function groupSearchResults(payload) {
    var groups = (payload && payload.groups) || [];
    return groups.map(function (g) {
      return {
        type: g.type,
        label: SEARCH_LABELS[g.type] || g.type,
        items: g.items || [],
      };
    });
  }

  function pickFallbackCity(cities) {
    var list = (cities || []).slice();
    list.sort(function (a, b) {
      var sa = a.sort_order == null ? 9999 : Number(a.sort_order);
      var sb = b.sort_order == null ? 9999 : Number(b.sort_order);
      if (sa !== sb) return sa - sb;
      return Number(a.id) - Number(b.id);
    });
    return list[0] || null;
  }

  function saveIceState(state, storage) {
    if (!storage || typeof storage.setItem !== 'function') return;
    try {
      storage.setItem(
        ICE_STATE_KEY,
        JSON.stringify({
          intent: state.intent || INTENTS.skate,
          cityId: state.cityId || null,
          cityName: state.cityName || '',
          scrollY: state.scrollY || 0,
          view: state.view || 'list',
        })
      );
    } catch (e) {
      /* quota */
    }
  }

  function loadIceState(storage) {
    if (!storage || typeof storage.getItem !== 'function') return null;
    try {
      var raw = storage.getItem(ICE_STATE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      return parsed;
    } catch (e) {
      return null;
    }
  }

  return {
    ICE_STATE_KEY: ICE_STATE_KEY,
    INTENTS: INTENTS,
    buildListUrl: buildListUrl,
    buildSearchUrl: buildSearchUrl,
    catalogHref: catalogHref,
    mapHref: mapHref,
    trainerHref: trainerHref,
    arenaHref: arenaHref,
    intentChipAction: intentChipAction,
    trainersMovedHint: trainersMovedHint,
    formatMeta: formatMeta,
    formatDistanceKm: formatDistanceKm,
    liveTone: liveTone,
    formatSortCaption: formatSortCaption,
    groupSearchResults: groupSearchResults,
    pickFallbackCity: pickFallbackCity,
    saveIceState: saveIceState,
    loadIceState: loadIceState,
  };
});
