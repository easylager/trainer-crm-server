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
  var TRAINER_RE = /^trainer_[1-9][0-9]*(?:_a_([1-9][0-9]*))?(?:_v_([pck][1-9][0-9]{0,8}))?$/i;
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
      if (coach[2]) return fromVia(coach[2]);
      if (coach[1]) return { source: 'site_place', source_arena_id: parseInt(coach[1], 10) };
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

  try {
    if (global && global.location) capture(global);
  } catch (e) { /* учёт не мешает загрузке */ }

  return {
    ENTRY_KEY: ENTRY_KEY,
    APP_KEY: APP_KEY,
    fromVia: fromVia,
    fromStartParam: fromStartParam,
    capture: capture,
    noteInApp: noteInApp,
    current: current,
  };
});
