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

    var base = path.replace(/[^/]+$/, '');
    var target = base + buildCatalogPathFromState(state);
    global.location.replace(target);
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
    var parts = ['trainer_id=' + encodeURIComponent(String(trainerId)), 'from=hub'];
    if (state.serviceId) parts.push('service_id=' + encodeURIComponent(String(state.serviceId)));
    if (state.arenaId) parts.push('arena_id=' + encodeURIComponent(String(state.arenaId)));
    return 'book?' + parts.join('&');
  }

  global.BookingDeeplink = {
    parseBookingDeepLink: parseBookingDeepLink,
    buildCatalogPathFromState: buildCatalogPathFromState,
    buildBookPathFromState: buildBookPathFromState,
    maybeRedirectBookShimToCatalog: maybeRedirectBookShimToCatalog,
    buildHubBookingPath: buildHubBookingPath,
  };

  maybeRedirectBookShimToCatalog();
})(typeof window !== 'undefined' ? window : this);
