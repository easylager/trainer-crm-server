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

  function mapShowsArenas(intent) {
    return intent !== INTENTS.coach;
  }

  function buildMapListUrl(opts) {
    opts = opts || {};
    if (!mapShowsArenas(opts.intent)) return '';
    return buildListUrl(opts);
  }

  function formatCoachMapEmpty() {
    return {
      title: 'Тренеров на карте нет',
      body: 'Смотрите список. Карта катков остаётся у чипов «Покататься» и «Группы».',
    };
  }

  function buildSearchUrl(q, limit) {
    var params = ['q=' + encodeURIComponent(String(q || '').trim())];
    if (limit) params.push('limit=' + encodeURIComponent(String(limit)));
    return '/api/public/search?' + params.join('&');
  }

  function buildTrainersUrl(opts) {
    opts = opts || {};
    var params = ['order_by=rating'];
    if (opts.cityId != null && opts.cityId !== '') {
      params.push('city_id=' + encodeURIComponent(String(opts.cityId)));
    }
    if (opts.serviceId != null && opts.serviceId !== '') {
      params.push('service_id=' + encodeURIComponent(String(opts.serviceId)));
    }
    params.push('limit=' + encodeURIComponent(String(opts.limit || 50)));
    if (opts.offset != null && opts.offset !== '') {
      params.push('offset=' + encodeURIComponent(String(opts.offset)));
    }
    return '/api/public/trainers?' + params.join('&');
  }

  function buildServicesUrl(opts) {
    opts = opts || {};
    if (opts.cityId == null || opts.cityId === '') return '/api/public/services';
    return '/api/public/services?city_id=' + encodeURIComponent(String(opts.cityId));
  }

  function buildIceCitiesUrl() {
    return '/api/public/ice/cities';
  }

  function filterIceCities(cities) {
    return (cities || []).filter(function (c) {
      return (Number(c.skate_count) || 0) > 0 || (Number(c.trainer_count) || 0) > 0;
    });
  }

  function pickCityIntent(city, currentIntent) {
    var skate = Number(city && city.skate_count);
    var trainers = Number(city && city.trainer_count);
    var known = city && (city.skate_count != null || city.trainer_count != null);
    if (!known) return currentIntent === INTENTS.coach ? INTENTS.coach : INTENTS.skate;
    if (currentIntent === INTENTS.coach && trainers > 0) return INTENTS.coach;
    if (skate > 0) return INTENTS.skate;
    if (trainers > 0) return INTENTS.coach;
    return currentIntent === INTENTS.coach ? INTENTS.coach : INTENTS.skate;
  }

  function serviceChipLabel(name) {
    var raw = String(name || '').trim();
    if (!raw) return 'Все';
    var lower = raw.toLowerCase();
    if (/охм/.test(lower)) return 'ОХМ';
    if (/с нуля/.test(lower)) return 'С нуля';
    if (/ролик/.test(lower)) return 'Ролики';
    if (/фигурн/.test(lower)) return 'Фигурное';
    if (/совершенств/.test(lower)) return 'Техника';
    if (/хокке/.test(lower)) return 'Хоккей';
    if (/офп|офк/.test(lower)) return 'ОФП';
    var cut = raw.replace(/\s*\([^)]*\)\s*/g, '').replace(/[«»]/g, '').trim();
    if (cut.length > 16) cut = cut.slice(0, 15) + '…';
    return cut || raw;
  }

  function cityCountryLabel(code) {
    var c = String(code || '').trim().toUpperCase();
    if (c === 'BY') return 'Беларусь';
    if (c === 'RU') return 'Россия';
    return '';
  }

  function coerceIntent(intent) {
    if (intent === INTENTS.coach) return INTENTS.coach;
    return INTENTS.skate;
  }

  function catalogHref() {
    return 'catalog?tab=catalog';
  }

  function iceCoachHref() {
    return 'ice?intent=coach';
  }

  function intentFromSearch(search) {
    var raw = String(search || '');
    if (raw.charAt(0) === '?') raw = raw.slice(1);
    var params;
    try {
      params = new URLSearchParams(raw);
    } catch (e) {
      return null;
    }
    var intent = String(params.get('intent') || '').trim();
    if (intent === INTENTS.skate || intent === INTENTS.coach || intent === INTENTS.group) {
      return intent;
    }
    return null;
  }

  function mapHref() {
    return '';
  }

  function trainerHref(item) {
    var id = item && item.id;
    return 'catalog?trainer_id=' + encodeURIComponent(String(id));
  }

  function arenaHref(item) {
    var ref = (item && (item.slug || item.id)) || '';
    return 'arena?ref=' + encodeURIComponent(String(ref));
  }

  var SKATE_SLOT_KINDS = { public_skate: true, open_ice: true };

  function slotKind(raw) {
    return String(raw || '').trim();
  }

  function hasFutureSkateSlot(item) {
    var live = (item && item.live) || {};
    var kind = slotKind(live.kind);
    if (kind === 'session' || SKATE_SLOT_KINDS[kind]) return true;
    if (SKATE_SLOT_KINDS[slotKind(item && item.next_kind)]) return true;
    var slots = (item && (item.sessions || item.upcoming_sessions)) || [];
    var i;
    for (i = 0; i < slots.length; i++) {
      if (SKATE_SLOT_KINDS[slotKind(slots[i] && slots[i].kind)]) return true;
    }
    return false;
  }

  function filterSkateLens(items, intent) {
    var list = items || [];
    if (intent !== INTENTS.skate) return list.slice();
    return list.filter(hasFutureSkateSlot);
  }

  function listRowCta() {
    return null;
  }

  function intentChipAction(intent) {
    if (intent === INTENTS.coach) {
      return { type: 'list', intent: INTENTS.coach };
    }
    if (intent === INTENTS.group) {
      return { type: 'list', intent: INTENTS.group };
    }
    return { type: 'list', intent: INTENTS.skate };
  }

  function trainerPhotoUrl(item) {
    var photos = (item && item.photos) || [];
    var ph = photos[0] || {};
    if (ph.list_url) return ph.list_url;
    if (ph.url) return ph.url;
    var fk = ph.file_key_list || ph.file_key;
    if (fk) return '/api/public/photos/' + encodeURIComponent(fk);
    if (item && item.thumb) return item.thumb;
    return '';
  }

  function trainerDisplayName(item) {
    if (!item) return 'Тренер';
    if (item.name) return String(item.name);
    var p = item.profile || {};
    var name = [p.first_name, p.last_name].filter(Boolean).join(' ').trim();
    return name || 'Тренер';
  }

  /** Первая буква имени для плашки без фото. Эмодзи в имени пропускаем. */
  function initialOf(name) {
    var clean = String(name || '')
      .replace(/[^\p{L}\p{N}]+/gu, ' ')
      .trim();
    return clean ? clean.charAt(0).toUpperCase() : '?';
  }

  function trainerCardView(item) {
    item = item || {};
    var p = item.profile || {};
    var parts = [];
    if (item.primary_arena_name) parts.push(String(item.primary_arena_name));
    var rating = p.rating_avg;
    var count = Number(p.rating_count) || 0;
    if (rating != null && count > 0) {
      parts.push('★ ' + Number(rating).toFixed(1));
    }
    var live = item.can_book ? 'Записаться' : 'Открыть профиль';
    var slots = Number(item.free_slots_14d);
    if (slots > 0) {
      live += ' · ' + slots + ' ' + pluralRu(slots, 'слот', 'слота', 'слотов');
    }
    var displayName = trainerDisplayName(item);
    return {
      kind: 'trainer',
      name: displayName,
      href: trainerHref(item),
      thumb: trainerPhotoUrl(item),
      // TASK-090 / AC-006: без фото была мёртвая заливка. Монограмма — тот же
      // приём, что у катка без кадра: пустое место должно что-то говорить.
      initial: initialOf(displayName),
      meta: parts.join(' · '),
      live: live,
      tone: 'a',
    };
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

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function isoDayUtc(d) {
    return d.toISOString().slice(0, 10);
  }

  function addDaysIso(iso, days) {
    var bits = String(iso).split('-');
    if (bits.length < 3) return iso;
    var dt = new Date(Date.UTC(Number(bits[0]), Number(bits[1]) - 1, Number(bits[2]) + days));
    return dt.getUTCFullYear() + '-' + pad2(dt.getUTCMonth() + 1) + '-' + pad2(dt.getUTCDate());
  }

  function formatMinorAmount(minor) {
    if (minor == null || minor === '' || isNaN(Number(minor))) return '';
    var major = Number(minor) / 100;
    return Number.isInteger(major) ? String(major) : major.toFixed(2).replace(/\.00$/, '');
  }

  function formatThreePrices(live) {
    live = live || {};
    var parts = [];
    var adult = formatMinorAmount(live.price_adult_minor);
    var child = formatMinorAmount(live.price_child_minor);
    var rental = formatMinorAmount(live.price_rental_minor);
    if (adult) parts.push('взр. ' + adult);
    if (child) parts.push('дет. ' + child);
    if (rental) parts.push('прокат +' + rental);
    return parts.join(' · ');
  }

  function sessionDayLabel(live, now) {
    live = live || {};
    var localDate = String(live.local_date || '').slice(0, 10);
    if (!localDate) return '';
    var today = isoDayUtc(now instanceof Date ? now : new Date());
    if (localDate === today) return 'Сегодня';
    if (localDate === addDaysIso(today, 1)) return 'Завтра';
    return localDate.slice(8, 10) + '.' + localDate.slice(5, 7);
  }

  function sessionWhenLabel(live, now) {
    live = live || {};
    var time = String(live.starts_at_local || '').slice(0, 5);
    return [sessionDayLabel(live, now), time].filter(Boolean).join(' ');
  }

  function formatLiveLine(item, now) {
    item = item || {};
    var live = item.live || {};
    var kind = String(live.kind || '');
    if (kind === 'trainers' || kind === 'groups') {
      return String(live.text || '').trim();
    }
    if (kind === 'session') {
      var parts = [];
      var when = sessionWhenLabel(live, now);
      var prices = formatThreePrices(live);
      var more = Number(live.more_count);
      if (when) parts.push(when);
      if (prices) parts.push(prices);
      if (more > 0) {
        parts.push('ещё ' + more + ' ' + pluralRu(more, 'сеанс', 'сеанса', 'сеансов'));
      }
      return parts.join(' · ');
    }
    var tier = String(item.tier || '').toUpperCase();
    if (tier === 'C') return 'Есть в справочнике · данных пока нет';
    if (tier === 'B') return 'Расписание уточняется · есть телефон и сайт';
    return String(live.text || item.live_line || 'Расписание уточняется').trim();
  }

  /**
   * TASK-090. Карточка «Льда» — табло, а не строка списка: кадр во всю ширину,
   * время как якорь, глубина предложения отдельной строкой. Функция чистая:
   * решает, ЧТО написано в каждом слоте, разметку собирает ice-tab.js.
   */
  function boardCardView(item, now) {
    item = item || {};
    var live = item.live || {};
    var isSession = String(live.kind || '') === 'session';
    var name = String(item.name || '');
    var currency = live.currency_code || item.currency_code || '';
    var prices = isSession ? formatThreePrices(live) : '';
    if (prices && currency) prices += ' ' + currency;
    var more = Number(live.more_count);
    var depth;
    if (isSession && more > 0) {
      // more_count — все будущие сеансы, а не «за неделю»: обещать окно нельзя.
      depth = 'Ещё ' + more + ' ' + pluralRu(more, 'сеанс', 'сеанса', 'сеансов') + ' в расписании';
    } else if (isSession) {
      depth = 'Расписание и цены';
    } else {
      depth = 'Открыть карточку катка';
    }
    return {
      href: arenaHref(item),
      photo: item.card || item.thumb || '',
      initial: initialOf(name),
      isSession: isSession,
      day: isSession ? sessionDayLabel(live, now) : '',
      time: isSession ? String(live.starts_at_local || '').slice(0, 5) : '',
      name: name,
      where: formatMeta(item),
      prices: prices,
      status: isSession ? '' : formatLiveLine(item, now),
      depth: depth,
      tone: liveTone(item),
    };
  }

  function formatEmptyList(intent, opts) {
    opts = opts || {};
    if (intent === INTENTS.skate) {
      return {
        title: 'Сейчас нет массового катания',
        body: 'В этом городе нет будущих сеансов. Смените город или откройте чип «Тренеры».',
      };
    }
    if (intent === INTENTS.group) {
      return {
        title: 'Групп с набором нет',
        body: 'Площадки появятся, когда откроется набор. Чип «Тренеры» — список тренеров города.',
      };
    }
    if (intent === INTENTS.coach) {
      if (opts.serviceName) {
        return {
          title: 'Нет тренеров по этой услуге',
          body: 'Снимите фильтр или смените город.',
        };
      }
      return {
        title: 'В этом городе пока нет тренеров',
        body: 'Смените город или вернитесь к чипу «Покататься».',
      };
    }
    return {
      title: 'В этом городе пока нет катков',
      body: 'Смените город или откройте чип «Тренеры».',
    };
  }

  function formatSortCaption(opts) {
    opts = opts || {};
    var total = Number(opts.total);
    if (isNaN(total)) total = (opts.items || []).length;
    if (opts.intent === INTENTS.coach) {
      var coachWord = pluralRu(total, 'тренер', 'тренера', 'тренеров');
      var svc = opts.serviceLabel ? ' · ' + opts.serviceLabel : '';
      if (total === 0) return 'Пока нет тренеров' + svc;
      return total + ' ' + coachWord + svc;
    }
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
          intent: coerceIntent(state.intent),
          cityId: state.cityId || null,
          cityName: state.cityName || '',
          serviceId: state.serviceId || null,
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
    buildMapListUrl: buildMapListUrl,
    mapShowsArenas: mapShowsArenas,
    formatCoachMapEmpty: formatCoachMapEmpty,
    buildSearchUrl: buildSearchUrl,
    buildTrainersUrl: buildTrainersUrl,
    buildServicesUrl: buildServicesUrl,
    buildIceCitiesUrl: buildIceCitiesUrl,
    filterIceCities: filterIceCities,
    pickCityIntent: pickCityIntent,
    serviceChipLabel: serviceChipLabel,
    cityCountryLabel: cityCountryLabel,
    coerceIntent: coerceIntent,
    catalogHref: catalogHref,
    iceCoachHref: iceCoachHref,
    intentFromSearch: intentFromSearch,
    mapHref: mapHref,
    trainerHref: trainerHref,
    arenaHref: arenaHref,
    intentChipAction: intentChipAction,
    trainerCardView: trainerCardView,
    hasFutureSkateSlot: hasFutureSkateSlot,
    filterSkateLens: filterSkateLens,
    listRowCta: listRowCta,
    trainersMovedHint: trainersMovedHint,
    formatMeta: formatMeta,
    formatDistanceKm: formatDistanceKm,
    liveTone: liveTone,
    formatThreePrices: formatThreePrices,
    formatLiveLine: formatLiveLine,
    sessionDayLabel: sessionDayLabel,
    boardCardView: boardCardView,
    formatEmptyList: formatEmptyList,
    formatSortCaption: formatSortCaption,
    groupSearchResults: groupSearchResults,
    pickFallbackCity: pickFallbackCity,
    saveIceState: saveIceState,
    loadIceState: loadIceState,
  };
});
