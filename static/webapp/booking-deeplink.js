/**
 * Booking deep-link normalizer + book.html → catalog strangler shim.
 */
(function (global) {
  'use strict';

  var PRESERVED_PARAMS = [
    'trainer_id',
    'slot_id',
    'service_id',
    'arena_id',
    'request_id',
    'from',
    'city_id',
    'force_service_choice',
    'action',
    'init_data',
  ];

  function parseBookingDeepLink(search) {
    var qp = new URLSearchParams(search || global.location.search || '');
    var trainerRaw = qp.get('trainer_id');
    var trainerId = trainerRaw != null ? parseInt(trainerRaw, 10) : NaN;
    return {
      trainerId: !isNaN(trainerId) && trainerId > 0 ? trainerId : null,
      slotId: qp.get('slot_id') || null,
      serviceId: qp.get('service_id') || null,
      arenaId: qp.get('arena_id') || null,
      requestId: qp.get('request_id') || null,
      from: qp.get('from') || '',
      cityId: qp.get('city_id') || null,
      forceServiceChoice: qp.get('force_service_choice') === '1',
      action: qp.get('action') || '',
      initData: qp.get('init_data') || '',
      host: (global.location.pathname || '').indexOf('catalog') >= 0 ? 'catalog' : 'book',
    };
  }

  function buildCatalogPathFromState(state, extra) {
    extra = extra || {};
    var parts = [];
    if (state.trainerId != null) parts.push('trainer_id=' + encodeURIComponent(String(state.trainerId)));
    if (state.slotId) parts.push('slot_id=' + encodeURIComponent(String(state.slotId)));
    if (state.serviceId) parts.push('service_id=' + encodeURIComponent(String(state.serviceId)));
    if (state.arenaId) parts.push('arena_id=' + encodeURIComponent(String(state.arenaId)));
    if (state.requestId) parts.push('request_id=' + encodeURIComponent(String(state.requestId)));
    if (state.from) parts.push('from=' + encodeURIComponent(String(state.from)));
    if (state.cityId) parts.push('city_id=' + encodeURIComponent(String(state.cityId)));
    if (extra.tab) parts.push('tab=' + encodeURIComponent(String(extra.tab)));
    if (extra.action) parts.push('action=' + encodeURIComponent(String(extra.action)));
    if (state.action && !extra.action) parts.push('action=' + encodeURIComponent(String(state.action)));
    var initData = state.initData;
    if (!initData && global.Telegram && global.Telegram.WebApp && global.Telegram.WebApp.initData) {
      initData = global.Telegram.WebApp.initData;
    }
    if (initData) parts.push('init_data=' + encodeURIComponent(initData));
    return 'catalog' + (parts.length ? '?' + parts.join('&') : '');
  }

  function buildBookPathFromState(state) {
    var parts = [];
    if (state.trainerId != null) parts.push('trainer_id=' + encodeURIComponent(String(state.trainerId)));
    if (state.slotId) parts.push('slot_id=' + encodeURIComponent(String(state.slotId)));
    if (state.serviceId) parts.push('service_id=' + encodeURIComponent(String(state.serviceId)));
    if (state.arenaId) parts.push('arena_id=' + encodeURIComponent(String(state.arenaId)));
    if (state.requestId) parts.push('request_id=' + encodeURIComponent(String(state.requestId)));
    if (state.from) parts.push('from=' + encodeURIComponent(String(state.from)));
    if (state.cityId) parts.push('city_id=' + encodeURIComponent(String(state.cityId)));
    if (state.forceServiceChoice) parts.push('force_service_choice=1');
    if (state.initData) parts.push('init_data=' + encodeURIComponent(state.initData));
    return 'book' + (parts.length ? '?' + parts.join('&') : '');
  }

  /**
   * book.html strangler: slot deeplink or trainer-only → catalog.
   * Week picker (trainer, no slot) stays when force_service_choice or request_id (needs book host).
   */
  function maybeRedirectBookShimToCatalog() {
    var path = (global.location.pathname || '').replace(/\/$/, '');
    var seg = path.split('/').pop() || '';
    if (seg !== 'book' && seg !== 'book.html') return false;

    var state = parseBookingDeepLink();
    if (!state.trainerId) return false;

    /* Request flow keeps book host until catalog parity for request_id UX */
    if (state.requestId) return false;

    var shouldRedirect = !!state.slotId;
    if (!shouldRedirect && !state.forceServiceChoice) {
      shouldRedirect = true;
    }
    if (!shouldRedirect) return false;

    var extra = {};
    if (state.from === 'hub' && !state.slotId) extra.action = 'book';
    var base = path.replace(/[^/]+$/, '');
    var target = base + buildCatalogPathFromState(state, extra);
    global.location.replace(target);
    return true;
  }

  /**
   * Единая карточка тренера (TASK-402, PDEC-036): при флаге внутренние входы `catalog?trainer_id=…`
   * и `book?trainer_id=…` ведут на `trainers?trainer_id=…` (location.replace, историю не копим).
   * Флаг ставит сервер: window.__UNIFIED_TRAINER_CARD__ (catalog.html и book.html).
   * Не перехватываем: collective= и group_id (остаются в старом каталоге), request_id (заявки, book.html).
   * Возвращает путь или null, если вход шим не касается.
   */
  var UNIFIED_CARD_PARAMS = ['slot_id', 'service_id', 'arena_id', 'city_id', 'from', 'via', 'init_data'];

  function buildUnifiedCardPath(search) {
    var qp = new URLSearchParams(search || '');
    var tid = parseInt(qp.get('trainer_id') || '', 10);
    if (!(tid > 0)) return null;
    if (qp.has('collective') || qp.has('group_id') || qp.has('request_id')) return null;
    var parts = ['trainer_id=' + encodeURIComponent(String(tid))];
    for (var i = 0; i < UNIFIED_CARD_PARAMS.length; i++) {
      var v = qp.get(UNIFIED_CARD_PARAMS[i]);
      if (v) parts.push(UNIFIED_CARD_PARAMS[i] + '=' + encodeURIComponent(v));
    }
    // №35 «Все окна» и №37 «Снова к» приходят как action=book&from=hub.
    // Раньше action отбрасывался и витрина открывала обычную карточку.
    if (qp.get('action') === 'book') parts.push('action=book');
    // №37 «Снова к»: тот же action=book, но карточка вернувшегося, не неделя.
    if (qp.get('entry') === 'rebook') parts.push('entry=rebook');
    return 'trainers?' + parts.join('&');
  }

  function maybeRedirectToUnifiedCard() {
    if (global.__UNIFIED_TRAINER_CARD__ !== true) return false;
    var path = (global.location.pathname || '').replace(/\/$/, '');
    var seg = path.split('/').pop() || '';
    if (seg !== 'catalog' && seg !== 'catalog.html' && seg !== 'book' && seg !== 'book.html') return false;
    var rel = buildUnifiedCardPath(global.location.search);
    if (!rel) return false;
    global.location.replace(path.replace(/[^/]+$/, '') + rel);
    return true;
  }

  function buildHubBookingPath(trainerId, opts) {
    opts = opts || {};
    var state = {
      trainerId: trainerId,
      slotId: opts.slotId || null,
      serviceId: opts.serviceId || null,
      arenaId: opts.arenaId || null,
      from: 'hub',
      initData: '',
    };
    if (state.slotId) return buildCatalogPathFromState(state);
    return buildCatalogPathFromState(state, { action: 'book' });
  }

  global.BookingDeeplink = {
    parseBookingDeepLink: parseBookingDeepLink,
    buildCatalogPathFromState: buildCatalogPathFromState,
    buildBookPathFromState: buildBookPathFromState,
    maybeRedirectBookShimToCatalog: maybeRedirectBookShimToCatalog,
    buildHubBookingPath: buildHubBookingPath,
    buildUnifiedCardPath: buildUnifiedCardPath,
    maybeRedirectToUnifiedCard: maybeRedirectToUnifiedCard,
  };

  if (!maybeRedirectToUnifiedCard()) maybeRedirectBookShimToCatalog();
})(typeof window !== 'undefined' ? window : this);
