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
  var MINSK_TZ = 'Europe/Minsk';

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
    /* Тип площадки — список ключей через запятую; пусто = все типы. */
    var venue = venueTypeParam(opts.venueTypes);
    if (venue) params.push('venue_type=' + encodeURIComponent(venue));
    if (opts.limit) params.push('limit=' + encodeURIComponent(String(opts.limit)));
    if (opts.cursor) params.push('cursor=' + encodeURIComponent(String(opts.cursor)));
    if (opts.when) params.push('when=' + encodeURIComponent(String(opts.when)));
    return '/api/public/ice/arenas?' + params.join('&');
  }

  /**
   * Нормализовать выбор типов площадок в параметр запроса.
   * Пустой массив и массив со всеми типами одинаково означают «без фильтра»:
   * слать все ключи бессмысленно, а пустой venue_type сервер и так игнорирует.
   */
  function venueTypeParam(venueTypes) {
    if (!venueTypes || !venueTypes.length) return '';
    var clean = [];
    for (var i = 0; i < venueTypes.length; i++) {
      var key = String(venueTypes[i] || '').trim().toLowerCase();
      if (key && clean.indexOf(key) < 0) clean.push(key);
    }
    return clean.join(',');
  }

  /**
   * Чипы типов площадок из фасетов ответа. Фасеты считаются ДО фильтра, поэтому
   * выбранный чип остаётся в списке — иначе из фильтра некуда было бы выйти.
   *
   * TASK-148 (AC-1): чип рендерится только при данных. Фасет со счётчиком 0 (или
   * отрицательным — мусор из ответа) не попадает в чипы, а если живых категорий
   * не осталось — ленты нет вовсе. Сервер и так не шлёт пустые фасеты
   * (arena_public_use_cases._venue_type_facets), этот фильтр — защита клиента.
   */
  function venueChipsView(facets, selected) {
    facets = facets || [];
    selected = selected || [];
    var live = [];
    for (var i = 0; i < facets.length; i++) {
      var f = facets[i] || {};
      if (Number(f.count) > 0) live.push(f);
    }
    if (live.length < 2) return [];
    var out = [{ key: '', label: 'Все', active: selected.length === 0 }];
    for (var j = 0; j < live.length; j++) {
      var f2 = live[j];
      var key = String(f2.key || '');
      if (!key) continue;
      out.push({
        key: key,
        label: String(f2.chip || key),
        count: Number(f2.count) || 0,
        active: selected.indexOf(key) >= 0,
      });
    }
    return out;
  }

  var PLACE_TAB_KEYS = ['ice', 'gym', 'outdoor'];
  var PLACE_MENU_KEYS = ['ice', 'gym', 'outdoor', 'choreo', 'pool', 'other'];

  function facetCount(facets, key) {
    facets = facets || [];
    for (var i = 0; i < facets.length; i++) {
      if (String((facets[i] || {}).key) === key) return Math.max(0, Number(facets[i].count) || 0);
    }
    return 0;
  }

  function liveFacetsForKeys(facets, keys) {
    facets = facets || [];
    keys = keys || [];
    var out = [];
    for (var i = 0; i < facets.length; i++) {
      var f = facets[i] || {};
      var key = String(f.key || '');
      if (keys.indexOf(key) < 0) continue;
      if (Number(f.count) > 0) out.push(f);
    }
    return out;
  }

  /** Род каталога в шапке: места (смешанная лента), тренеры или только магазины. */
  function catalogScope(intent, venueTypes) {
    if (coerceIntent(intent) === INTENTS.coach) return 'coach';
    var v = venueTypes || [];
    if (v.length === 1 && v[0] === 'shop') return 'shop';
    return 'places';
  }

  function sumFacetCounts(facets, keys) {
    var n = 0;
    for (var i = 0; i < keys.length; i++) n += facetCount(facets, keys[i]);
    return n;
  }

  /**
   * Верхний сегмент «Места · Тренеры · Магазины». До первого ответа arenas — подсказки
   * из объекта города (skate_count, trainer_count, place_count).
   */
  function catalogModesView(opts) {
    opts = opts || {};
    var facets = opts.facets || [];
    var scope = catalogScope(opts.intent, opts.venueTypes);
    var modes = [];
    var placesN = sumFacetCounts(facets, PLACE_MENU_KEYS);
    if (!facets.length) {
      placesN =
        (Number(opts.skateCount) || 0) +
        (Number(opts.placeCountHint) || 0);
    }
    if (placesN > 0) {
      modes.push({ id: 'places', label: 'Места', active: scope === 'places' });
    }
    var trainers = Number(opts.trainerCount);
    if (isNaN(trainers)) trainers = 0;
    if (trainers > 0) {
      modes.push({ id: 'coach', label: 'Тренеры', active: scope === 'coach' });
    }
    if (facetCount(facets, 'shop') > 0) {
      modes.push({ id: 'shop', label: 'Магазины', active: scope === 'shop' });
    }
    return modes;
  }

  /** Хореография/бассейн — в меню, не в underline-ряду из трёх типов. */
  function placeMenuNeeded(facets) {
    var menu = liveFacetsForKeys(facets, PLACE_MENU_KEYS);
    if (menu.length < 2) return false;
    for (var i = 0; i < menu.length; i++) {
      if (PLACE_TAB_KEYS.indexOf(String(menu[i].key || '')) < 0) return true;
    }
    return false;
  }

  function selectionVenueKey(selected) {
    selected = selected || [];
    return selected.length === 1 ? String(selected[0] || '') : '';
  }

  function placeTabsView(facets, selected) {
    if (placeMenuNeeded(facets)) return [];
    facets = facets || [];
    selected = selected || [];
    var live = liveFacetsForKeys(facets, PLACE_TAB_KEYS);
    if (live.length < 2) return [];
    var key = selectionVenueKey(selected);
    var out = [{ key: '', label: 'Все', active: !key }];
    for (var j = 0; j < live.length; j++) {
      var f2 = live[j];
      var k = String(f2.key || '');
      out.push({
        key: k,
        label: String(f2.chip || k),
        count: Number(f2.count) || 0,
        active: key === k,
      });
    }
    return out;
  }

  function placeMenuView(facets, selected) {
    if (!placeMenuNeeded(facets)) return [];
    facets = facets || [];
    selected = selected || [];
    var live = liveFacetsForKeys(facets, PLACE_MENU_KEYS);
    if (live.length < 2) return [];
    var key = selectionVenueKey(selected);
    var total = sumFacetCounts(facets, PLACE_MENU_KEYS);
    var out = [{ key: '', label: 'Все места', count: total, active: !key }];
    for (var j = 0; j < live.length; j++) {
      var f2 = live[j];
      var k = String(f2.key || '');
      out.push({
        key: k,
        label: String(f2.chip || k),
        count: Number(f2.count) || 0,
        active: key === k,
      });
    }
    return out;
  }

  function placeMenuLabel(facets, selected) {
    var key = selectionVenueKey(selected);
    if (!key) return 'Все места';
    var live = liveFacetsForKeys(facets, PLACE_MENU_KEYS);
    for (var i = 0; i < live.length; i++) {
      if (String(live[i].key) === key) return String(live[i].chip || key);
    }
    return 'Все места';
  }

  function applyCatalogMode(mode) {
    if (mode === 'coach') return { intent: INTENTS.coach, venueTypes: [] };
    if (mode === 'shop') return { intent: INTENTS.skate, venueTypes: ['shop'] };
    return { intent: INTENTS.skate, venueTypes: [] };
  }

  function catalogSearchPlaceholder(scope) {
    if (scope === 'coach') return 'Имя тренера';
    if (scope === 'shop') return 'Магазин или заточка';
    return 'Каток, зал или трасса';
  }

  /** Сообщение, когда «Ближе» не получило геолокацию. reason: unsupported | denied */
  function formatNearGeoBlockedMessage(opts) {
    opts = opts || {};
    var hasCity = opts.cityId != null && opts.cityId !== '';
    var city = String(opts.cityName || '').trim();
    var cityBit = city ? ' Город «' + city + '» уже выбран — менять его не нужно.' : '';
    var reason = opts.reason === 'unsupported' ? 'unsupported' : 'denied';
    if (hasCity) {
      if (reason === 'unsupported') {
        return (
          '«Ближе» ставит сверху места, которые ближе к вам. На этом устройстве геолокация недоступна, порядок списка не изменится.' +
          cityBit
        );
      }
      return (
        '«Ближе» ставит сверху места, которые ближе к вам. Разрешите геолокацию для Telegram в настройках телефона и нажмите снова.' +
        cityBit
      );
    }
    if (reason === 'unsupported') {
      return 'Не получилось определить, где вы. Выберите город — покажем места в нём.';
    }
    return 'Разрешите доступ к геолокации — или выберите город вручную.';
  }

  function whenPickerLabel(selected, resolvedKey) {
    var chips = whenChipsView(selected, resolvedKey);
    for (var i = 0; i < chips.length; i++) {
      if (chips[i].active) return chips[i].label;
    }
    return 'Любое время';
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
      body: 'Смотрите список. Карта площадок остаётся у чипов «Где заниматься» и «Группы».',
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
    var ids = (opts.serviceIds || []).filter(function (x) { return x != null && x !== ''; });
    if (ids.length) {
      // Несколько услуг — «любая из»: тренер подходит, если ведёт хотя бы одну.
      params.push('service_ids=' + ids.map(encodeURIComponent).join(','));
    } else if (opts.serviceId != null && opts.serviceId !== '') {
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
      return (
        (Number(c.skate_count) || 0) > 0 ||
        (Number(c.trainer_count) || 0) > 0 ||
        (Number(c.map_rink_count) || 0) > 0 ||
        // TASK-146: город с одними магазинами (ещё без координат) — тоже город каталога.
        (Number(c.place_count) || 0) > 0
      );
    });
  }

  function buildIceInterestUrl() {
    return '/api/public/ice/interest';
  }

  function buildGroupsProbeUrl(opts) {
    opts = opts || {};
    var params = ['limit=1'];
    if (opts.cityId != null && opts.cityId !== '') {
      params.push('city_id=' + encodeURIComponent(String(opts.cityId)));
    }
    return '/api/public/training-groups?' + params.join('&');
  }

  function shouldShowGroupChip(count) {
    return Number(count) > 0;
  }

  function shouldShowSkateChip(count) {
    return count == null || Number(count) > 0;
  }

  function sanitizeIntent(intent, opts) {
    opts = opts || {};
    var hasSkate = opts.hasSkate !== false;
    if (intent === INTENTS.group && !opts.hasGroups) intent = INTENTS.skate;
    if (intent === INTENTS.coach) return INTENTS.coach;
    if (intent === INTENTS.group) return INTENTS.group;
    return hasSkate ? INTENTS.skate : INTENTS.coach;
  }

  function rankServiceChips(services) {
    return (services || [])
      .filter(function (s) {
        return Number(s.trainer_count) > 0;
      })
      .sort(function (a, b) {
        var sa = a.sort_order == null ? 9999 : Number(a.sort_order);
        var sb = b.sort_order == null ? 9999 : Number(b.sort_order);
        if (sa !== sb) return sa - sb;
        return Number(a.id) - Number(b.id);
      });
  }

  function rankPopularCities(cities, limit) {
    var list = (cities || []).slice();
    var cap = limit == null ? 8 : Number(limit);
    list.sort(function (a, b) {
      var wa =
        (Number(a.map_rink_count) || 0) +
        (Number(a.skate_count) || 0) +
        (Number(a.trainer_count) || 0);
      var wb =
        (Number(b.map_rink_count) || 0) +
        (Number(b.skate_count) || 0) +
        (Number(b.trainer_count) || 0);
      if (wa !== wb) return wb - wa;
      var sa = a.sort_order == null ? 9999 : Number(a.sort_order);
      var sb = b.sort_order == null ? 9999 : Number(b.sort_order);
      if (sa !== sb) return sa - sb;
      return Number(a.id) - Number(b.id);
    });
    return list.slice(0, cap);
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

  /**
   * TASK-146: диплинк «каталог города» (catalog_<city>[_<intent>]) приходит сюда как
   * ?city_id=…&intent=…|venue=…. Город из ссылки важнее сохранённого и города из
   * профиля: человек открыл ссылку на Брест — он хочет Брест, а не свой Минск.
   */
  function cityIdFromSearch(search) {
    var raw = String(search || '');
    if (raw.charAt(0) === '?') raw = raw.slice(1);
    try {
      var value = String(new URLSearchParams(raw).get('city_id') || '').trim();
      return /^[1-9][0-9]*$/.test(value) ? Number(value) : null;
    } catch (e) {
      return null;
    }
  }

  var VENUE_KEYS = ['ice', 'gym', 'choreo', 'pool', 'outdoor', 'other', 'shop'];

  function venueFromSearch(search) {
    var raw = String(search || '');
    if (raw.charAt(0) === '?') raw = raw.slice(1);
    try {
      var value = String(new URLSearchParams(raw).get('venue') || '').trim().toLowerCase();
      return VENUE_KEYS.indexOf(value) >= 0 ? value : null;
    } catch (e) {
      return null;
    }
  }

  /**
   * TASK-146 (Q-006): чипы окна времени. По умолчанию — «auto»: сервер сам выбирает окно
   * по дню и часу и возвращает его ключ; подсвечиваем ровно то, что применено.
   */
  var WHEN_CHIPS = [
    ['today_evening', 'Сегодня вечером'],
    ['tomorrow', 'Завтра'],
    ['weekend', 'Выходные'],
    ['any', 'Любое время'],
  ];

  function whenChipsView(selected, resolvedKey) {
    var active = selected && selected !== 'auto' ? selected : resolvedKey || 'any';
    return WHEN_CHIPS.map(function (c) {
      return { key: c[0], label: c[1], active: c[0] === active };
    });
  }

  /**
   * TASK-149: окно времени из ссылки — ?when=<ключ>. Допустимы ровно ключи сервера
   * (WHEN_KEYS в src/application/ice_time_windows.py); сервер так же обрезает пробелы и
   * приводит к нижнему регистру. Мусор, пустое и неизвестное — null: молча, поведение
   * как без параметра (state.when остаётся 'auto'). Применимость к режиму («Тренеры»
   * окна не имеют) проверяет вызывающий через whenChipsVisible, не эта функция.
   */
  var WHEN_KEYS = ['auto', 'today_evening', 'today', 'tomorrow', 'weekend', 'any'];

  function whenFromSearch(search) {
    var raw = String(search || '');
    if (raw.charAt(0) === '?') raw = raw.slice(1);
    try {
      var value = String(new URLSearchParams(raw).get('when') || '').trim().toLowerCase();
      return WHEN_KEYS.indexOf(value) >= 0 ? value : null;
    } catch (e) {
      return null;
    }
  }

  /** Окно времени — только когда в выборе есть лёд с сеансами. */
  function whenPickerVisible(intent, venueTypes, facets) {
    if (coerceIntent(intent) !== INTENTS.skate) return false;
    var v = venueTypes || [];
    if (v.length === 1 && v[0] === 'shop') return false;
    if (v.length === 1 && v[0] !== 'ice') return false;
    if (v.length > 1 && v.indexOf('ice') < 0) return false;
    if (facets && facets.length) return facetCount(facets, 'ice') > 0;
    return true;
  }

  function whenChipsVisible(intent, venueTypes, facets) {
    return whenPickerVisible(intent, venueTypes, facets);
  }

  function mapHref() {
    return '';
  }

  function trainerHref(item) {
    var id = item && item.id;
    return 'catalog?trainer_id=' + encodeURIComponent(String(id));
  }

  function arenaHref(item) {
    /* TASK-146: по id, а не по slug. Slug уникален только внутри города, а поиск и
       карта — по всей стране: «ledovyy-dvorets» в Бресте открывал минский дворец.
       Читаемые адреса нужны публичной странице (/p/{city}/{slug}), не мини-аппу. */
    var ref = (item && (item.id != null ? item.id : item.slug)) || '';
    var href = 'arena?ref=' + encodeURIComponent(String(ref));
    /* Карточка открывается на том дне и сеансе, которые человек видел на плитке:
       выбрал «Завтра», тапнул «Завтра 18:00» — попал на завтра с выделенным 18:00,
       а не на «Сегодня» по умолчанию карточки. */
    var live = (item && item.live) || {};
    var day = String(live.local_date || '').slice(0, 10);
    if (String(live.kind || '') === 'session' && /^\d{4}-\d{2}-\d{2}$/.test(day)) {
      href += '&day=' + day;
      if (live.session_id != null) href += '&s=' + encodeURIComponent(String(live.session_id));
    }
    return href;
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
    // Same-origin proxy first: public R2 CDN 404s while /api/public/photos works
    // (trainer profile already prefers file_key for this reason).
    var fk = ph.file_key_list || ph.file_key;
    if (fk) return '/api/public/photos/' + encodeURIComponent(fk);
    if (ph.list_url) return ph.list_url;
    if (ph.url) return ph.url;
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

  /** Максимум услуг в строке специализации: третья уже не читается на 390px. */
  var TRAINER_SPEC_MAX = 2;

  /**
   * «С нуля · Техника» — то, чем тренеры отличаются друг от друга.
   *
   * Услуга есть у каждого тренера в выдаче (её же фильтруют чипы над списком),
   * поэтому это единственный различающий факт, который не оставит половину
   * карточек пустыми. Длинные названия из справочника режутся до сути: карточка
   * не место для «Обучение катанию «с нуля»» во всю ширину.
   */
  function trainerSpecLine(item) {
    var services = (item && item.services) || [];
    var names = [];
    for (var i = 0; i < services.length; i++) {
      var raw = services[i] && services[i].service_name;
      var name = shortServiceName(raw);
      if (name && names.indexOf(name) < 0) names.push(name);
    }
    if (!names.length) return '';
    if (names.length <= TRAINER_SPEC_MAX) return names.join(' · ');
    return names.slice(0, TRAINER_SPEC_MAX).join(' · ') + ' +' + (names.length - TRAINER_SPEC_MAX);
  }

  function shortServiceName(raw) {
    var s = String(raw == null ? '' : raw).trim();
    if (!s) return '';
    // Названия в справочнике — административные («Обучение катанию «с нуля»»).
    // На карточке нужен ярлык, и он обязан совпадать с подписью чипа-фильтра,
    // иначе человек не свяжет выбранный фильтр с тем, что видит в списке.
    if (/с\s*нуля/i.test(s)) return 'С нуля';
    if (/совершенствован/i.test(s)) return 'Техника';
    if (/хоккей/i.test(s)) return 'Хоккей';
    if (/фигурн/i.test(s)) return 'Фигурное';
    return s;
  }

  function formatTrainerPriceFrom(item) {
    var services = (item && item.services) || [];
    var min = null;
    for (var i = 0; i < services.length; i++) {
      var s = services[i] || {};
      var v = s.price_byn_min != null ? s.price_byn_min : s.price_byn;
      if (v == null) continue;
      var n = Number(v);
      if (isNaN(n)) continue;
      if (min == null || n < min) min = n;
    }
    if (min == null) return '';
    var num = min === Math.floor(min) ? String(min) : min.toFixed(2);
    // «BYN» захардкожен так же, как в каталоге (formatCatalogServicePrice):
    // валюты в услуге нет, и расходиться с каталогом на одном и том же товаре
    // хуже, чем разделить с ним известное ограничение по Москве.
    return 'от ' + num + ' BYN';
  }

  function formatTrainerExperience(profile) {
    var years = Number(profile && profile.experience_years);
    if (!years || years < 1) return '';
    return years + ' ' + pluralRu(years, 'год', 'года', 'лет') + ' опыта';
  }

  function trainerCardView(item) {
    item = item || {};
    var p = item.profile || {};
    var parts = [];
    /* Роль впереди места: «Спортивный психолог» отвечает на «кто это», а название
       арены — только на «где». Для старых анкет без роли сервер подставляет «Тренер»,
       но его не показываем: это подпись по умолчанию, а не факт о человеке. */
    var role = String(p.specialist_role || '').trim();
    if (role && role !== 'Тренер') parts.push(role);

    if (item.primary_arena_name) {
      parts.push(String(item.primary_arena_name));
    }
    /* Онлайн — независимый флаг анкеты: он может стоять и рядом с залом,
       а не только вместо площадки (см. trainer_profiles.online_enabled). */
    if (p.online_enabled || item.arena_work_format === 'online') {
      parts.push('Онлайн');
    }

    /*
     * Факты для выбора, по убыванию силы: цена → стаж → рейтинг.
     *
     * Каждый добавляется, только если он ЕСТЬ. Ни «цена по запросу», ни «стаж не
     * указан», ни нулевых звёзд: пустой факт не сообщает ничего, но выглядит как
     * недостаток тренера, а не как недостаток данных.
     *
     * Больше одного факта в строку не ставим — рядом с длинным названием арены
     * («Ледовый дворец спорта Минской области») строка и так уходит в две.
     */
    var facts = [];
    var price = formatTrainerPriceFrom(item);
    if (price) facts.push(price);
    if (!facts.length) {
      var exp = formatTrainerExperience(p);
      if (exp) facts.push(exp);
    }
    if (!facts.length) {
      var rating = p.rating_avg;
      var count = Number(p.rating_count) || 0;
      if (rating != null && count > 0) facts.push('★ ' + Number(rating).toFixed(1));
    }
    parts = parts.concat(facts);

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
      spec: trainerSpecLine(item),
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
    var place = item.address ? String(item.address) : item.district ? String(item.district) : '';
    if (place) parts.push(place);
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

  function minskDateIso(now) {
    var parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: MINSK_TZ,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(now);
    var y = '1970';
    var m = '01';
    var d = '01';
    var i;
    for (i = 0; i < parts.length; i++) {
      if (parts[i].type === 'year') y = parts[i].value;
      if (parts[i].type === 'month') m = parts[i].value;
      if (parts[i].type === 'day') d = parts[i].value;
    }
    return y + '-' + m + '-' + d;
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
    var today = minskDateIso(now instanceof Date ? now : new Date());
    if (localDate === today) return 'Сегодня';
    if (localDate === addDaysIso(today, 1)) return 'Завтра';
    // День недели обязателен: под чипом «Выходные» голое «03.10» не говорит, суббота ли это.
    var bits = localDate.split('-');
    var wd = new Date(Date.UTC(Number(bits[0]), Number(bits[1]) - 1, Number(bits[2]))).getUTCDay();
    return WEEKDAYS_SHORT_RU[wd] + ', ' + localDate.slice(8, 10) + '.' + localDate.slice(5, 7);
  }

  var WEEKDAYS_SHORT_RU = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

  /**
   * Попадает ли карточка в выбранное окно времени. Сервер кладёт в окно только сеанс;
   * ближайший сеанс вне окна он помечает outside_window, а место без сеансов (зал,
   * магазин, «расписание уточняется») в окно не попадает по определению.
   */
  function inWindow(item, win) {
    if (!win) return true;
    var live = (item && item.live) || {};
    var kind = String(live.kind || '');
    /* Окно — про сеансы льда. Улица без расписания, магазин, «уточняется» — не
       ответ на чип «Сегодня вечером»; на «Все» они остаются в основной ленте. */
    if (kind !== 'session') return true;
    return !live.outside_window;
  }

  /**
   * TASK-146: окно сортирует, а не фильтрует. Сверху — то, что есть в окне; ниже —
   * остальные со своим ближайшим временем. Две группы разные по смыслу, и лента
   * обязана это показать, иначе «Сегодня 16:15» под чипом «Завтра» — обман.
   */
  function splitByWindow(items, win) {
    var hits = [];
    var rest = [];
    (items || []).forEach(function (it) {
      (inWindow(it, win) ? hits : rest).push(it);
    });
    return { hits: hits, rest: rest };
  }

  var WINDOW_MISS = {
    today_evening: 'Сегодня вечером нет',
    today: 'Сегодня нет',
    tomorrow: 'Завтра нет',
    weekend: 'На выходных нет',
  };

  function windowMissLabel(win) {
    if (!win) return '';
    return WINDOW_MISS[win.key] || String(win.label || '') + ' нет';
  }

  /** Разделитель между «в окне» и «вне окна»: что это за места и что на них показано. */
  function windowBreakView(win, rest, venueTypes) {
    rest = rest || [];
    if (!win || !rest.length) return null;
    var noun = venueNoun(rest, venueTypes);
    var n = rest.length;
    return {
      title: windowMissLabel(win),
      sub: n + ' ' + pluralRu(n, noun[0], noun[1], noun[2]) + ' · их ближайшее время',
    };
  }

  /**
   * TASK-146: «Рядом» — сортировка текущей ленты по расстоянию, внутри групп окна.
   * Сервер ставит уровень данных выше расстояния (tier A первым), а человек, который
   * нажал «Рядом», спрашивает именно «что ближе». Без расстояния — в конец, порядок
   * сервера внутри равных сохраняется.
   */
  function sortByDistance(items) {
    return (items || [])
      .map(function (it, i) {
        var d = it && it.distance_km;
        return { it: it, i: i, d: d == null || isNaN(Number(d)) ? Infinity : Number(d) };
      })
      .sort(function (a, b) {
        return a.d - b.d || a.i - b.i;
      })
      .map(function (x) {
        return x.it;
      });
  }

  function orderForFeed(items, win, byDistance) {
    var parts = splitByWindow(items, win);
    if (byDistance) {
      parts.hits = sortByDistance(parts.hits);
      parts.rest = sortByDistance(parts.rest);
    }
    return parts;
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
      // Вне выбранного окна — не «сеанс», а «ближайший»: строка не должна выдавать себя за ответ.
      if (when && live.outside_window) when = 'Ближайший: ' + when;
      var prices = formatThreePrices(live);
      var more = Number(live.more_count);
      if (when) parts.push(when);
      if (prices) parts.push(prices);
      if (more > 0) {
        parts.push('ещё ' + more + ' ' + pluralRu(more, 'сеанс', 'сеанса', 'сеансов'));
      }
      return parts.join(' · ');
    }
    // TASK-146: магазин и зал — без сеансов; сервер уже сказал, что там есть и когда открыто.
    if (kind === 'place' || kind === 'closed') return String(live.text || '').trim();
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
  function boardCardView(item, now, opts) {
    item = item || {};
    opts = opts || {};
    var live = item.live || {};
    var isSession = String(live.kind || '') === 'session';
    var off = !!opts.window && !inWindow(item, opts.window);
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
      /* Подпись склоняет сервер по venue_type: на зале это «карточку зала».
         Хардкод «катка» здесь и был тем, что ломалось на первой же не-ледовой
         площадке. Фолбэк — для ответов старого API без поля. */
      depth = String(item.venue_cta || '').trim() || 'Открыть карточку места';
    }
    // TASK-146: парсер давно не читал сайт катка — время показываем, но не выдаём за свежее.
    var stale = isSession && !!(item.freshness && item.freshness.schedule_stale);
    if (stale) depth = 'Расписание могло измениться';
    return {
      stale: stale,
      href: arenaHref(item),
      photo: item.card || item.thumb || '',
      initial: initialOf(name),
      // TASK-148: иконка типа с сервера — содержимое бесфотошной плашки.
      // Фолбэк на монограмму, если ответ старого API без venue_icon.
      venueIcon: String(item.venue_icon || ''),
      isSession: isSession,
      day: isSession ? sessionDayLabel(live, now) : '',
      time: isSession ? String(live.starts_at_local || '').slice(0, 5) : '',
      name: name,
      where: formatMeta(item),
      prices: prices,
      status: isSession ? '' : formatLiveLine(item, now),
      depth: depth,
      tone: liveTone(item),
      // TASK-146: тип места — цветная рейка карточки (DEC-006: своя семантика,
      // не статус записи) и ближайший сеанс для «Позвать».
      venueType: String(item.venue_type || 'ice'),
      arenaId: item.id,
      sessionId: isSession && live.session_id != null ? live.session_id : null,
      inviteLabel: isSession ? sessionDayLabel(live, now) + ' ' + String(live.starts_at_local || '').slice(0, 5) : '',
      // TASK-146: карточка вне окна — приглушённая, время не герой, и прямо сказано почему.
      offWindow: off,
      offLabel: off ? windowMissLabel(opts.window) + (isSession ? ' · ближайший' : '') : '',
    };
  }

  /**
   * TASK-096 AC-002: an empty state must offer the way out, not merely name it in prose.
   * Each shape now carries `action` (and sometimes `secondary`) — an intent the view turns into a
   * real button: `intent:<id>` switches the chip, `city` opens the city picker, `clear-service`
   * drops the service filter, `retry` reloads.
   */
  function formatEmptyList(intent, opts) {
    opts = opts || {};
    var trainers = Number(opts.trainerCount) || 0;
    var rinks = Number(opts.mapRinkCount) || 0;
    if (intent === INTENTS.skate && trainers > 0 && rinks <= 0) {
      return {
        kind: 'coming-soon',
        title: 'Скоро добавим катки',
        body: 'В этом городе уже есть тренеры. Расписание массового катания подключим — нажмите, если хотите кататься здесь.',
        cta: 'Хочу кататься здесь',
        action: { label: 'Хочу кататься здесь', kind: 'ice-interest' },
        secondary: { label: 'Показать тренеров', kind: 'intent:coach' },
      };
    }
    if (intent === INTENTS.skate) {
      return {
        title: 'Сейчас нет массового катания',
        body: 'В этом городе нет будущих сеансов — но тренеры здесь есть.',
        action: { label: 'Показать тренеров', kind: 'intent:coach' },
        secondary: { label: 'Сменить город', kind: 'city' },
      };
    }
    if (intent === INTENTS.group) {
      return {
        title: 'Групп с набором нет',
        body: 'Площадки появятся, когда откроется набор. Пока можно записаться к тренеру.',
        action: { label: 'Показать тренеров', kind: 'intent:coach' },
        secondary: { label: 'Сменить город', kind: 'city' },
      };
    }
    if (intent === INTENTS.coach) {
      if (opts.serviceName) {
        return {
          title: 'Нет тренеров по этой услуге',
          body: 'В городе есть другие тренеры — снимите фильтр по услуге.',
          action: { label: 'Показать всех тренеров', kind: 'clear-service' },
          secondary: { label: 'Сменить город', kind: 'city' },
        };
      }
      if (opts.hasSkate === false) {
        return {
          title: 'В этом городе пока нет тренеров',
          body: 'Смените город — расписания катков здесь пока тоже нет.',
          action: { label: 'Сменить город', kind: 'city' },
        };
      }
      return {
        title: 'В этом городе пока нет тренеров',
        body: 'Посмотрите массовые катания или выберите другой город.',
        action: { label: 'Показать массовые катания', kind: 'intent:skate' },
        secondary: { label: 'Сменить город', kind: 'city' },
      };
    }
    return {
      title: 'В этом городе пока нет катков',
      body: 'Посмотрите тренеров города или выберите другой город.',
      action: { label: 'Показать тренеров', kind: 'intent:coach' },
      secondary: { label: 'Сменить город', kind: 'city' },
    };
  }

  /** Search dropdown with no hits. Was «Ничего не найдено» — a literal dead end. */
  function formatEmptySearch(query) {
    var q = String(query || '').trim();
    return {
      title: q ? 'По запросу «' + q + '» ничего нет' : 'Ничего не найдено',
      body: 'Поиск ищет по каткам, тренерам и городам. Можно открыть весь лёд города списком.',
      action: { label: 'Показать весь лёд города', kind: 'clear-search' },
    };
  }

  /**
   * How the Ice list should paint. Items from the previous lens must not be
   * re-skinned as the other card (wide skate board → compact trainer row).
   *
   * loadedIntent === null means "we have not confirmed this lens". Leftover
   * rows in memory still belong to the other card and must not paint.
   */
  function listPaintMode(opts) {
    opts = opts || {};
    var intent = coerceIntent(opts.intent);
    var items = opts.items || [];
    var loading = !!opts.loading;
    var loaded = opts.loadedIntent ? coerceIntent(opts.loadedIntent) : null;
    if (loaded !== intent) {
      if (loading || items.length) return 'skeleton';
    }
    if (loading && !items.length) return 'skeleton';
    if (!items.length) return 'empty';
    return 'items';
  }

  function listHostId(intent) {
    return coerceIntent(intent) === INTENTS.coach ? 'iceListCoach' : 'iceListSkate';
  }

  function formatSortCaption(opts) {
    opts = opts || {};
    var total = Number(opts.total);
    if (isNaN(total)) total = (opts.items || []).length;
    var intent = coerceIntent(opts.intent);
    var loaded = opts.loadedIntent ? coerceIntent(opts.loadedIntent) : null;
    var wrongLens = !!(loaded && loaded !== intent);
    // TASK-095: пока данных нет, «Пока нет катков» — не пустое состояние, а ложь
    // о результате запроса, которого ещё не было. Подпись ждёт вместе со списком.
    if ((opts.loading && !total) || wrongLens) {
      return intent === INTENTS.coach ? 'Ищем тренеров…' : 'Ищем катки…';
    }
    // TASK-146 (Q-006): окно времени. Пусто в окне — не тупик, а «вот ближайшее».
    var win = opts.window;
    if (win && opts.intent !== INTENTS.coach && total > 0) {
      var winLabel = String(win.label || '');
      if (!Number(win.hits)) return winLabel + ' сеансов нет · показываем ближайшие';
      var wn = venueNoun(opts.items || [], opts.venueTypes);
      var hits = Number(win.hits);
      var filtered = opts.venueTypes && opts.venueTypes.length;
      var count = filtered ? hits : total;
      return count + ' ' + pluralRu(count, wn[0], wn[1], wn[2]) + ' · ' + winLabel.toLowerCase();
    }
    if (opts.intent === INTENTS.coach) {
      var coachWord = pluralRu(total, 'тренер', 'тренера', 'тренеров');
      var svc = opts.serviceLabel ? ' · ' + opts.serviceLabel : '';
      if (total === 0) return 'Пока нет тренеров' + svc;
      return total + ' ' + coachWord + svc;
    }
    var items = opts.items || [];
    var noun = venueNoun(items, opts.venueTypes);
    var word = pluralRu(total, noun[0], noun[1], noun[2]);
    var hasA = items.some(function (it) {
      return String(it.tier || '').toUpperCase() === 'A';
    });
    if (hasA) return total + ' ' + word + ' · сначала с актуальным расписанием';
    if (total === 0) return 'Пока нет ' + noun[2] + ' · смените город или чип';
    // «Расписание уточняется» — вопрос ко льду; у магазина и зала расписания нет.
    if (noun[0] !== 'каток') return total + ' ' + word;
    return total + ' ' + word + ' · расписание уточняется';
  }

  /**
   * TASK-146. Чем считать результаты: «1 каток» для зала и магазина было неправдой.
   * Один тип в выдаче (или в фильтре) — его существительное; смесь — «места».
   */
  var VENUE_NOUNS = {
    ice: ['каток', 'катка', 'катков'],
    outdoor: ['каток', 'катка', 'катков'],
    gym: ['зал', 'зала', 'залов'],
    choreo: ['зал', 'зала', 'залов'],
    pool: ['бассейн', 'бассейна', 'бассейнов'],
    shop: ['магазин', 'магазина', 'магазинов'],
    other: ['место', 'места', 'мест'],
  };

  function venueNoun(items, venueTypes) {
    var keys = [];
    (venueTypes || []).forEach(function (k) {
      if (keys.indexOf(k) < 0) keys.push(k);
    });
    if (!keys.length) {
      (items || []).forEach(function (it) {
        var k = String((it && it.venue_type) || 'ice');
        if (keys.indexOf(k) < 0) keys.push(k);
      });
    }
    if (!keys.length) return VENUE_NOUNS.ice;
    var first = VENUE_NOUNS[keys[0]] || VENUE_NOUNS.other;
    for (var i = 1; i < keys.length; i++) {
      if ((VENUE_NOUNS[keys[i]] || VENUE_NOUNS.other)[0] !== first[0]) return VENUE_NOUNS.other;
    }
    return first;
  }

  // «Места», а не «Катки»: по слову «заточка» находятся и мастерские, и залы.
  var SEARCH_LABELS = { arena: 'Места', trainer: 'Тренеры', city: 'Города' };

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
          serviceIds: state.serviceIds || [],
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
    venueTypeParam: venueTypeParam,
    venueChipsView: venueChipsView,
    PLACE_TAB_KEYS: PLACE_TAB_KEYS,
    PLACE_MENU_KEYS: PLACE_MENU_KEYS,
    facetCount: facetCount,
    catalogScope: catalogScope,
    catalogModesView: catalogModesView,
    placeMenuNeeded: placeMenuNeeded,
    placeTabsView: placeTabsView,
    placeMenuView: placeMenuView,
    placeMenuLabel: placeMenuLabel,
    applyCatalogMode: applyCatalogMode,
    catalogSearchPlaceholder: catalogSearchPlaceholder,
    formatNearGeoBlockedMessage: formatNearGeoBlockedMessage,
    whenPickerVisible: whenPickerVisible,
    whenPickerLabel: whenPickerLabel,
    mapShowsArenas: mapShowsArenas,
    formatCoachMapEmpty: formatCoachMapEmpty,
    buildSearchUrl: buildSearchUrl,
    buildTrainersUrl: buildTrainersUrl,
    buildServicesUrl: buildServicesUrl,
    buildIceCitiesUrl: buildIceCitiesUrl,
    buildIceInterestUrl: buildIceInterestUrl,
    buildGroupsProbeUrl: buildGroupsProbeUrl,
    filterIceCities: filterIceCities,
    rankServiceChips: rankServiceChips,
    rankPopularCities: rankPopularCities,
    shouldShowGroupChip: shouldShowGroupChip,
    shouldShowSkateChip: shouldShowSkateChip,
    sanitizeIntent: sanitizeIntent,
    pickCityIntent: pickCityIntent,
    serviceChipLabel: serviceChipLabel,
    cityCountryLabel: cityCountryLabel,
    coerceIntent: coerceIntent,
    catalogHref: catalogHref,
    iceCoachHref: iceCoachHref,
    intentFromSearch: intentFromSearch,
    cityIdFromSearch: cityIdFromSearch,
    whenChipsView: whenChipsView,
    whenChipsVisible: whenChipsVisible,
    venueFromSearch: venueFromSearch,
    whenFromSearch: whenFromSearch,
    mapHref: mapHref,
    trainerHref: trainerHref,
    arenaHref: arenaHref,
    intentChipAction: intentChipAction,
    trainerCardView: trainerCardView,
    listRowCta: listRowCta,
    trainersMovedHint: trainersMovedHint,
    formatMeta: formatMeta,
    formatDistanceKm: formatDistanceKm,
    liveTone: liveTone,
    formatThreePrices: formatThreePrices,
    formatLiveLine: formatLiveLine,
    sessionDayLabel: sessionDayLabel,
    inWindow: inWindow,
    splitByWindow: splitByWindow,
    windowMissLabel: windowMissLabel,
    windowBreakView: windowBreakView,
    sortByDistance: sortByDistance,
    orderForFeed: orderForFeed,
    boardCardView: boardCardView,
    formatEmptyList: formatEmptyList,
    formatEmptySearch: formatEmptySearch,
    formatSortCaption: formatSortCaption,
    listPaintMode: listPaintMode,
    listHostId: listHostId,
    groupSearchResults: groupSearchResults,
    pickFallbackCity: pickFallbackCity,
    saveIceState: saveIceState,
    loadIceState: loadIceState,
  };
});
