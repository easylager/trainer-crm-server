/**
 * TASK-389: замер «нажатие на вкладку бара → содержимое показано» и холодного старта.
 * Чистая модель без DOM: оболочка клиента кладёт метку нажатия в sessionStorage, а на новой
 * странице, когда содержимое показано, собирает событие. Ничего персонального: вкладки,
 * миллисекунды, платформа Telegram, флаг season_ui.
 * Browser: window.TabTimingModel. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.TabTimingModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var TABS = ['home', 'catalog', 'bookings', 'kk', 'me', 'more'];
  /* Дольше минуты — не переход, а брошенная вкладка или уснувший телефон: в выборку не берём. */
  var MAX_TAP_AGE_MS = 60000;
  var MAX_MS = 120000;
  var NAV_TYPES = ['navigate', 'reload', 'back_forward', 'prerender'];

  function isTab(id) {
    return TABS.indexOf(id) >= 0;
  }

  /** Метка нажатия: «откуда|куда|эпоха мс». Пустая строка — метку не ставим. */
  function encodeTap(from, to, nowMs) {
    if (!isTab(to) || typeof nowMs !== 'number' || !isFinite(nowMs)) return '';
    return (isTab(from) ? from : '') + '|' + to + '|' + Math.round(nowMs);
  }

  /** Разбор метки. null — метки нет, она битая или протухла. */
  function decodeTap(raw, nowMs) {
    if (typeof raw !== 'string') return null;
    var p = raw.split('|');
    if (p.length !== 3 || !isTab(p[1])) return null;
    var at = Number(p[2]);
    if (!isFinite(at) || at <= 0) return null;
    var age = nowMs - at;
    if (age < 0 || age > MAX_TAP_AGE_MS) return null;
    return { from: isTab(p[0]) ? p[0] : null, to: p[1], at: at };
  }

  function clampMs(v) {
    var n = Math.round(Number(v));
    if (!isFinite(n) || n < 0) return null;
    return Math.min(n, MAX_MS);
  }

  function cleanPlatform(v) {
    var s = String(v || '').toLowerCase();
    return /^[a-z0-9_]{1,16}$/.test(s) ? s : 'unknown';
  }

  /**
   * Событие по моменту «содержимое показано».
   * input: {tapRaw, firstPage, nowMs (эпоха), sinceOriginMs (performance.now()), tab (вкладка этой
   *         страницы), nav (тип навигации), platform, seasonUi}
   * Результат: {kind:'tab'|'cold', from, to, ms, page_ms, nav, platform, season_ui} или null.
   *  tab  — нажатие на вкладку; ms от нажатия до показа, page_ms — от начала новой страницы.
   *  cold — первая страница сессии, открытая не нажатием; ms от начала страницы (timeOrigin).
   * Перезагрузка, «назад», переход по ссылке не из бара и страница без вкладки — не событие.
   */
  function buildEvent(input) {
    var i = input || {};
    var tab = isTab(i.tab) ? i.tab : null;
    if (!tab) return null;
    var nav = NAV_TYPES.indexOf(i.nav) >= 0 ? i.nav : 'navigate';
    var pageMs = clampMs(i.sinceOriginMs);
    if (pageMs === null) return null;
    var base = {
      nav: nav,
      platform: cleanPlatform(i.platform),
      season_ui: i.seasonUi === true,
    };
    var tap = decodeTap(i.tapRaw, i.nowMs);
    if (tap) {
      if (tap.to !== tab || nav !== 'navigate') return null;
      var ms = clampMs(i.nowMs - tap.at);
      if (ms === null) return null;
      return Object.assign({ kind: 'tab', from: tap.from, to: tab, ms: ms, page_ms: pageMs }, base);
    }
    if (i.firstPage === true && nav === 'navigate') {
      return Object.assign({ kind: 'cold', from: null, to: tab, ms: pageMs, page_ms: pageMs }, base);
    }
    return null;
  }

  return {
    TABS: TABS,
    MAX_TAP_AGE_MS: MAX_TAP_AGE_MS,
    encodeTap: encodeTap,
    decodeTap: decodeTap,
    buildEvent: buildEvent,
  };
});
