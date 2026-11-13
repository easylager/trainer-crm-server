/**
 * TASK-351: источник записи — откуда пришёл человек, который записывается.
 *
 * Зеркало src/application/booking_source.py. Источник сеанса Mini App (первое касание):
 *   * ?via=link | share | p<каток> | c<город> | k<город> в адресе — кнопки бота и страницы сайта;
 *   * start_param из Telegram: trainer_7_v_p3 (со страницы тренера, пришли с катка 3),
 *     trainer_7 (страница тренера), trainer_7_a_3 (старая строка тренера на катке),
 *     catalog_12_coach («Все тренеры» со страницы города).
 * Если сеанс начался без источника, а тренера выбрали в самом Mini App — «miniapp».
 * Хранится в sessionStorage: переживает переход catalog → book, но не следующий запуск.
 * Run tests: node --test tests/js/booking-source.test.js
 *
 * TASK-397: те же страницы шлют события карточки (просмотр, кнопки, форма, первое
 * касание после регистрации). В тело события не попадают контакт и подпись запуска.
 */
(function (global, factory) {
  var api = factory(global);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (global) global.GlideBookingSource = api;
})(typeof window !== 'undefined' ? window : typeof globalThis !== 'undefined' ? globalThis : this, function (global) {
  'use strict';

  var ENTRY_KEY = 'glide_booking_source_v1';
  var APP_KEY = 'glide_booking_source_app_v1';
  var VIA_PLACE = { p: 'site_place', c: 'site_city', k: 'site_catalog' };
  var VIA_RE = /^([pck])([1-9][0-9]{0,8})$/;
  var TRAINER_RE = /^trainer_[1-9][0-9]*((?:_[a-z]+_[A-Za-z0-9]+)*)$/i;
  var CITY_COACH_RE = /^catalog_([1-9][0-9]*)_coach(?:_[a-z_]+)?$/i;

  function fromVia(via) {
    via = String(via || '').trim().toLowerCase();
    if (via === 'link' || via === 'share') return { source: via };
    var m = VIA_RE.exec(via);
    if (!m) return null;
    var out = { source: VIA_PLACE[m[1]] };
    if (m[1] === 'p') out.source_arena_id = parseInt(m[2], 10);
    else out.source_city_id = parseInt(m[2], 10);
    return out;
  }

  function fromStartParam(sp) {
    sp = String(sp || '').trim();
    if (!sp) return null;
    var coach = TRAINER_RE.exec(sp);
    if (coach) {
      // Хвосты _a_/_s_/_v_ в любом порядке (TASK-357); слот источник не задаёт.
      var tail = coach[1] || '';
      var via = /_v_([pck][1-9][0-9]{0,8})(?=_|$)/i.exec(tail);
      if (via) return fromVia(via[1]);
      var arena = /_a_([1-9][0-9]*)(?=_|$)/i.exec(tail);
      if (arena) return { source: 'site_place', source_arena_id: parseInt(arena[1], 10) };
      return { source: 'site_trainer' };
    }
    var city = CITY_COACH_RE.exec(sp);
    if (city) return { source: 'site_city', source_city_id: parseInt(city[1], 10) };
    return null;
  }

  function storage(ctx) {
    try {
      return (ctx && ctx.sessionStorage) || global.sessionStorage || null;
    } catch (e) {
      return null;
    }
  }

  function read(ctx, key) {
    try {
      var s = storage(ctx);
      var raw = s && s.getItem(key);
      var v = raw ? JSON.parse(raw) : null;
      return v && typeof v.source === 'string' ? v : null;
    } catch (e) {
      return null;
    }
  }

  function write(ctx, key, value) {
    try {
      var s = storage(ctx);
      if (s) s.setItem(key, JSON.stringify(value));
    } catch (e) { /* без storage — источник только на этой странице */ }
  }

  function startParam(ctx) {
    var G = (ctx && ctx.GlideDeepLink) || global.GlideDeepLink;
    if (G && typeof G.readStartParam === 'function') return G.readStartParam(ctx || global);
    var tg = (ctx && ctx.Telegram) || global.Telegram;
    var wa = tg && tg.WebApp;
    return (wa && wa.initDataUnsafe && wa.initDataUnsafe.start_param) || '';
  }

  /** Запомнить источник сеанса по адресу и start_param. Первое касание не перезаписывается. */
  function capture(ctx) {
    ctx = ctx || global;
    var stored = read(ctx, ENTRY_KEY);
    if (stored) return stored;
    var src = null;
    try {
      var loc = ctx.location;
      if (loc) src = fromVia(new URLSearchParams(loc.search || '').get('via'));
    } catch (e) { /* */ }
    if (!src) src = fromStartParam(startParam(ctx));
    if (src) write(ctx, ENTRY_KEY, src);
    return src;
  }

  /** Тренера выбрали в самом Mini App (список, карточка катка, витрина). */
  function noteInApp(place, ctx) {
    place = place || {};
    var out = { source: 'miniapp' };
    var a = parseInt(place.arenaId, 10);
    var c = parseInt(place.cityId, 10);
    if (a > 0) out.source_arena_id = a;
    if (c > 0) out.source_city_id = c;
    write(ctx || global, APP_KEY, out);
    return out;
  }

  /** Источник для тела записи: вход сеанса, иначе выбор в Mini App, иначе null. */
  function current(ctx) {
    ctx = ctx || global;
    return capture(ctx) || read(ctx, APP_KEY);
  }

  var REG_TID_KEY = 'trainer_crm_client_register_tid';
  var FIRST_TAP_KEY = 'glide_link_reg_first_tap_v1';

  /** Кнопка карточки → код события. «Записаться» — кнопка слота с классом cta. */
  function ctaAction(act, className) {
    act = String(act || '');
    if (act === 'write') return 'write';
    if (act === 'copy-phone') return 'call';
    if (act === 'request') return 'request';
    if (act === 'slot' || act === 'win') {
      return (/\bcta\b/.test(String(className || ''))) ? 'book' : 'slot';
    }
    return null;
  }

  /** Первое касание после регистрации по ссылке тренера: хаб, карточка или слот. */
  function classifyFirstTap(act, href) {
    act = String(act || '');
    href = String(href || '');
    if (act === 'slot' || act === 'win' || /(?:^|[?&])slot_id=/.test(href) || /\/book(?:[.?#]|$)/.test(href)) {
      return 'slot';
    }
    if (act === 'trainer' || /(?:^|[?&])trainer_id=/.test(href) || /\/trainers(?:[.?#]|$)/.test(href)) {
      return 'card';
    }
    return 'hub';
  }

  function postCardEvent(ctx, body) {
    try {
      var tg = (ctx.Telegram && ctx.Telegram.WebApp) || null;
      var init = tg && tg.initData;
      if (!init || typeof ctx.fetch !== 'function') return;
      ctx.fetch('/api/webapp/client/trainer-card-event', {
        method: 'POST',
        keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': init },
        body: JSON.stringify(body),
      }).catch(function () { /* учёт не мешает экрану */ });
    } catch (e) { /* */ }
  }

  function installMeasure(ctx) {
    var doc = ctx && ctx.document;
    if (!doc || doc.__glideCardMeasure) return;
    doc.__glideCardMeasure = true;
    var pinned = 0;
    function tidFromUrl() {
      try {
        var n = parseInt(new URLSearchParams(ctx.location.search || '').get('trainer_id'), 10);
        return n > 0 ? n : 0;
      } catch (e) { return 0; }
    }
    pinned = tidFromUrl();
    function viaNow() {
      try { return new URLSearchParams(ctx.location.search || '').get('via') || ''; }
      catch (e) { return ''; }
    }
    function signedVia() {
      var src = fromStartParam(startParam(ctx));
      if (!src) return '';
      if (src.source === 'link' || src.source === 'share') return src.source;
      if (src.source === 'site_place' && src.source_arena_id) return 'p' + src.source_arena_id;
      if (src.source === 'site_city' && src.source_city_id) return 'c' + src.source_city_id;
      if (src.source === 'site_catalog' && src.source_city_id) return 'k' + src.source_city_id;
      return '';
    }
    function attr() {
      return signedVia() || viaNow();
    }
    var seenCard = 0;
    var seenForm = 0;
    function onClick(ev) {
      var node = ev.target;
      if (node && node.nodeType !== 1) node = node.parentElement;
      while (node && node !== doc) {
        if (node.getAttribute) break;
        node = node.parentElement;
      }
      var actNode = node;
      while (actNode && actNode !== doc && !(actNode.getAttribute && actNode.getAttribute('data-act'))) {
        actNode = actNode.parentElement;
      }
      var act = actNode && actNode.getAttribute ? (actNode.getAttribute('data-act') || '') : '';
      var tidAttr = actNode && actNode.getAttribute ? parseInt(actNode.getAttribute('data-tid'), 10) : 0;
      if (tidAttr > 0) pinned = tidAttr;
      var tid = pinned || tidFromUrl();
      if (tid > 0 && act) {
        var action = ctaAction(act, actNode.className);
        if (action) {
          postCardEvent(ctx, { event: 'card_cta_tap', trainer_id: tid, action: action, via: attr() });
        }
      }
      try {
        var path = (ctx.location && ctx.location.pathname) || '';
        if (path.indexOf('client-register') !== -1) return;
        var store = storage(ctx);
        if (!store || store.getItem(FIRST_TAP_KEY)) return;
        var regTid = parseInt(store.getItem(REG_TID_KEY) || '', 10);
        if (!(regTid > 0)) return;
        var link = '';
        var hop = node;
        while (hop && hop !== doc) {
          if (hop.getAttribute && hop.getAttribute('href')) { link = hop.getAttribute('href'); break; }
          hop = hop.parentElement;
        }
        if (!act && !link) return;
        var target = classifyFirstTap(act, link);
        store.setItem(FIRST_TAP_KEY, '1');
        postCardEvent(ctx, { event: 'link_reg_first_tap', trainer_id: regTid, target: target, via: attr() });
      } catch (e) { /* */ }
    }
    doc.addEventListener('click', onClick, true);
    if (typeof ctx.MutationObserver !== 'function') return;
    var root = doc.body || doc.documentElement;
    if (!root) return;
    var observer = new ctx.MutationObserver(function () {
      var scope = doc.getElementById ? (doc.getElementById('app') || root) : root;
      var tid = pinned || tidFromUrl();
      if (tid > 0 && scope.querySelector && scope.querySelector('.hro, .noph') && seenCard !== tid) {
        seenCard = tid;
        postCardEvent(ctx, { event: 'trainer_card_view', trainer_id: tid, via: attr() });
      }
      var form = scope.querySelector && scope.querySelector('[data-act="submit"]');
      if (!form && doc.getElementById) {
        var screen = doc.getElementById('screenForm');
        if (screen && screen.classList && screen.classList.contains('book-form-ready')) form = screen;
      }
      if (tid > 0 && form && seenForm !== tid) {
        seenForm = tid;
        postCardEvent(ctx, { event: 'booking_form_open', trainer_id: tid, via: attr() });
      }
    });
    observer.observe(root, { childList: true, subtree: true });
  }

  try {
    if (global && global.location) capture(global);
    if (global && global.document) installMeasure(global);
  } catch (e) { /* учёт не мешает загрузке */ }

  return {
    ENTRY_KEY: ENTRY_KEY,
    APP_KEY: APP_KEY,
    fromVia: fromVia,
    fromStartParam: fromStartParam,
    capture: capture,
    noteInApp: noteInApp,
    current: current,
    ctaAction: ctaAction,
    classifyFirstTap: classifyFirstTap,
  };
});
