/**
 * startapp-диплинки Mini App (TASK-223 / P1-4).
 * Парсер start_param и ранний redirect до загрузки тела entry-страницы.
 * Контракт совпадает с src/application/place_links.py и mini-app-client-shell.js.
 */
(function (global, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (global) {
    global.GlideDeepLink = api;
  }
})(typeof window !== 'undefined' ? window : typeof global !== 'undefined' ? global : this, function () {
  'use strict';

  var DEEP_LINK_FLAG = 'glide_start_param_used_v1';

  function readStartParam(ctx) {
    ctx = ctx || {};
    var loc = ctx.location || (typeof location !== 'undefined' ? location : null);
    var tg =
      ctx.Telegram ||
      (typeof window !== 'undefined' && window.Telegram) ||
      (typeof global !== 'undefined' && global.Telegram);
    var webApp = tg && tg.WebApp;
    var fromTg = webApp && webApp.initDataUnsafe && webApp.initDataUnsafe.start_param;
    if (fromTg) return String(fromTg);
    if (!loc) return '';
    try {
      var hash = loc.hash || '';
      var m = /(?:^|[&#])tgWebAppStartParam=([^&]+)/.exec(hash);
      if (m) return decodeURIComponent(m[1]);
    } catch (e) { /* ignore */ }
    try {
      var qp = new URLSearchParams(loc.search || '');
      return qp.get('tgWebAppStartParam') || qp.get('startapp') || '';
    } catch (e2) {
      return '';
    }
  }

  function deepLinkTarget(sp) {
    sp = String(sp || '').trim();
    var arena = /^arena[_-]([1-9][0-9]*)(?:_s_([1-9][0-9]*))?$/i.exec(sp);
    if (arena) {
      var arenaPath = 'arena?ref=' + arena[1];
      if (arena[2]) arenaPath += '&s=' + arena[2];
      return { key: 'arena', path: arenaPath };
    }
    if (/^catalog$/i.test(sp)) return { key: 'ice', path: 'ice' };
    var catalog =
      /^catalog_([1-9][0-9]*)(?:_(skate|coach|shop|gym|ice|outdoor|choreo|pool|other|ohm|service))?(?:_(today_evening|today|tomorrow|weekend))?$/i.exec(
        sp
      );
    if (catalog) {
      var q = 'city_id=' + catalog[1];
      var intent = (catalog[2] || '').toLowerCase();
      var when = (catalog[3] || '').toLowerCase();
      var venueToken =
        intent === 'shop' ||
        intent === 'gym' ||
        intent === 'ice' ||
        intent === 'outdoor' ||
        intent === 'choreo' ||
        intent === 'pool' ||
        intent === 'other';
      if (venueToken) q += '&venue=' + intent;
      else if (intent) q += '&intent=' + intent;
      else if (when) q += '&intent=skate';
      if (when) q += '&when=' + when;
      return { key: 'ice', path: 'ice?' + q };
    }
    return null;
  }

  function pathnameKey(loc) {
    loc = loc || (typeof location !== 'undefined' ? location : { pathname: '' });
    var p = String(loc.pathname || '').replace(/\/$/, '');
    var seg = p.split('/').pop() || '';
    return seg.replace(/\.html$/, '');
  }

  function isAlreadyOnTarget(loc, target) {
    var current = pathnameKey(loc);
    if (current === target.key && target.key === 'arena') return true;
    if (current === target.key) {
      var wantQ = target.path.indexOf('?') >= 0 ? '?' + target.path.split('?')[1] : '';
      if (String(loc.search || '') === wantQ) return true;
    }
    return false;
  }

  function resolveWebappPath(relativePath, loc) {
    var u = new URL(String(relativePath || ''), loc.href);
    return u.pathname + u.search;
  }

  /**
   * Синхронный redirect из <head> entry-страницы. Возвращает true, если ушли со страницы.
   */
  function maybeEarlyRedirect(ctx) {
    ctx = ctx || {};
    var loc = ctx.location || (typeof location !== 'undefined' ? location : null);
    var storage = ctx.sessionStorage;
    if (!loc) return false;
    if (!storage && typeof sessionStorage !== 'undefined') storage = sessionStorage;
    var sp = String(readStartParam(ctx) || '').trim();
    var target = deepLinkTarget(sp);
    if (!target) return false;
    try {
      if (storage && storage.getItem(DEEP_LINK_FLAG) === sp) return false;
      if (storage) storage.setItem(DEEP_LINK_FLAG, sp);
    } catch (e) { /* без storage — как в шелле */ }
    if (isAlreadyOnTarget(loc, target)) return false;
    var pathAndQuery = resolveWebappPath(target.path, loc);
    var hash = loc.hash || '';
    loc.replace(pathAndQuery + hash);
    return true;
  }

  return {
    DEEP_LINK_FLAG: DEEP_LINK_FLAG,
    readStartParam: readStartParam,
    deepLinkTarget: deepLinkTarget,
    pathnameKey: pathnameKey,
    isAlreadyOnTarget: isAlreadyOnTarget,
    maybeEarlyRedirect: maybeEarlyRedirect,
  };
});

/* entry-страница подключает этот файл синхронно в <head> — уходим до разбора body */
(function () {
  if (typeof window === 'undefined' || !window.GlideDeepLink) return;
  try {
    window.GlideDeepLink.maybeEarlyRedirect();
  } catch (e) { /* не ломаем загрузку хаба */ }
})();
