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

  function parseArenaDeepLink(sp) {
    sp = String(sp || '').trim();
    var arena = /^arena[_-]([1-9][0-9]*)(?:_s_([1-9][0-9]*))?$/i.exec(sp);
    if (!arena) return null;
    return { arenaId: arena[1], sessionId: arena[2] || null };
  }

  function arenaLegacyMiniAppPath(arenaId, sessionId) {
    var arenaPath = 'arena?ref=' + encodeURIComponent(String(arenaId));
    if (sessionId != null) arenaPath += '&s=' + encodeURIComponent(String(sessionId));
    return arenaPath;
  }

  function arenaPlacePath(publicPath, sessionId) {
    var path = String(publicPath || '').trim();
    if (!path) return '';
    if (sessionId != null) return path + '?s=' + encodeURIComponent(String(sessionId));
    return path;
  }

  /**
   * TASK-257: при serverPlaceCard — public_path из GET /api/public/arenas/{id}, иначе arena?ref=.
   */
  function resolveArenaDeepLinkTarget(sp, options) {
    options = options || {};
    var parsed = parseArenaDeepLink(sp);
    if (!parsed) return Promise.resolve(null);
    var legacy = { key: 'arena', path: arenaLegacyMiniAppPath(parsed.arenaId, parsed.sessionId) };
    if (!options.serverPlaceCard) return Promise.resolve(legacy);
    var fetchCard = options.fetchPublicArenaCard;
    if (typeof fetchCard !== 'function') return Promise.resolve(legacy);
    return Promise.resolve()
      .then(function () {
        return fetchCard(parsed.arenaId);
      })
      .then(function (card) {
        var pub = card && card.public_path;
        if (!pub) return legacy;
        return { key: 'place', path: arenaPlacePath(pub, parsed.sessionId) };
      })
      .catch(function () {
        return legacy;
      });
  }

  /**
   * ``trainer_7`` / ``trainer_7_a_3`` (place_links.trainer_start_param) — карточка тренера,
   * тот же путь, что тап по тренеру на карточке катка (arena-card-model.buildBookingHref).
   */
  function trainerDeepLinkTarget(sp) {
    var m = /^trainer_([1-9][0-9]*)(?:_a_([1-9][0-9]*))?$/i.exec(String(sp || '').trim());
    if (!m) return null;
    var path = m[2]
      ? 'catalog?from=arena&trainer_id=' + m[1] + '&arena_id=' + m[2]
      : 'catalog?trainer_id=' + m[1];
    return { key: 'catalog', path: path };
  }

  function deepLinkTarget(sp) {
    sp = String(sp || '').trim();
    var parsed = parseArenaDeepLink(sp);
    if (parsed) {
      return { key: 'arena', path: arenaLegacyMiniAppPath(parsed.arenaId, parsed.sessionId) };
    }
    if (/^catalog$/i.test(sp)) return { key: 'ice', path: 'ice' };
    var coach = trainerDeepLinkTarget(sp);
    if (coach) return coach;
    var catalog =
      /^catalog_([1-9][0-9]*)(?:_(skate|coach|shop|gym|ice|outdoor|choreo|pool|other|ohm|service))?(?:_(today_evening|today|tomorrow|weekend))?$/i.exec(
        sp
      );
    // «Кто кого»: приглашение в лигу друзей (TASK-298/299).
    var league = /^kk_([A-Za-z0-9]{4,16})$/.exec(sp);
    if (league) return { key: 'kto-kogo', path: 'kto-kogo?join=' + league[1].toUpperCase() };
    // Кнопки карточек в чате (TASK-300): kkl_КОД — приглашение, kkr[_КОД] — итог «в точку!».
    var fromCard = /^kk([lr])(?:_([A-Za-z0-9]{4,16}))?$/.exec(sp);
    if (fromCard) {
      var cardKind = fromCard[1] === 'l' ? 'league' : 'result';
      if (fromCard[2]) return { key: 'kto-kogo', path: 'kto-kogo?join=' + fromCard[2].toUpperCase() + '&from=' + cardKind };
      if (cardKind === 'result') return { key: 'kto-kogo', path: 'kto-kogo?from=result' };
    }
    // Сообщения бота «Кто кого» (TASK-335): kkn[_<матч>[_h|_a]] — к матчу или сразу ход за сторону,
    // kkmo_<гонка> — итоги месяца, kkoff — выключить напоминания.
    var kkPick = /^kkn(?:_([1-9][0-9]*)(?:_([ha]))?)?$/.exec(sp);
    if (kkPick) {
      if (kkPick[2]) return { key: 'kto-kogo', path: 'kto-kogo?pick=' + kkPick[1] + '&side=' + (kkPick[2] === 'h' ? 'home' : 'away') };
      return { key: 'kto-kogo', path: 'kto-kogo' };
    }
    var kkMonth = /^kkmo_([1-9][0-9]*)$/.exec(sp);
    if (kkMonth) return { key: 'kto-kogo', path: 'kto-kogo?month=' + kkMonth[1] };
    if (sp === 'kkoff') return { key: 'kto-kogo', path: 'kto-kogo?remind=off' };
    // Домашний матч — ивент (TASK-304): kkm_<матч>[_<код компании>] — «Подробнее» и «Позвать» из чата.
    var matchEvent = /^kkm_([1-9][0-9]*)(?:_([A-Za-z0-9]{4,16}))?$/.exec(sp);
    if (matchEvent) {
      return { key: 'client-match', path: 'client-match?id=' + matchEvent[1] + (matchEvent[2] ? '&c=' + matchEvent[2] : '') };
    }
    var company = /^company_([1-9][0-9]*)$/i.exec(sp);
    if (company) return { key: 'ice-company', path: 'ice-company?s=' + company[1] };
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
    var u = new URL(String(relativePath || ''), new URL('/webapp/', loc.href));
    return u.pathname + u.search;
  }

  function maybePublicRedirect(ctx) {
    ctx = ctx || (typeof window !== 'undefined' ? window : {});
    var loc = ctx.location;
    if (!loc) return false;
    var p = loc.pathname;
    var hockeyList = p === '/hockey' || p === '/hockey/';
    if (p !== '/' && !hockeyList && !/^\/(p|c|m|t)\//.test(p)) return false;
    var tg = ctx.Telegram && ctx.Telegram.WebApp;
    var query = new URLSearchParams(loc.search || '');
    var hashParams = new URLSearchParams(String(loc.hash || '').replace(/^#/, ''));
    var storage;
    var active = !!((tg && tg.initData) || query.get('init_data') || hashParams.get('tgWebAppData'));
    try {
      storage = ctx.sessionStorage;
      if (active && storage) storage.setItem('glide_mini_app_active_v1', '1');
      if (storage && storage.getItem('glide_mini_app_active_v1') === '1') active = true;
    } catch (e) { /* storage может быть запрещён */ }
    if (!active) return false;

    var sp = String(readStartParam(ctx) || '').trim();
    var target = deepLinkTarget(sp);
    try {
      if (storage && storage.getItem(DEEP_LINK_FLAG) === sp) target = null;
    } catch (e2) { /* */ }
    var path = target && target.path;
    if (!path) {
      if (p === '/') path = 'client-home';
      /* Список сайта /hockey → каталог матчей Mini App. Город сайта — slug, каталог ждёт название: не подставляем. */
      else if (hockeyList) path = 'client-matches' + (/^[a-z0-9-]{1,64}$/.test(query.get('club') || '') ? '?team=' + query.get('club') : '');
      else if (/^\/m\/[1-9][0-9]*-/.test(p)) path = 'client-match?id=' + p.split('/')[2].split('-')[0];
      else if (/^\/t\/[1-9][0-9]*(?:-|$)/.test(p)) path = 'catalog?trainer_id=' + p.split('/')[2].split('-')[0];
      else {
        var attr = p.indexOf('/p/') === 0 ? 'data-arena-id' : 'data-city-id';
        var tag = ctx.document && ctx.document.querySelector('script[' + attr + ']');
        var id = tag && tag.getAttribute(attr);
        if (!/^[1-9][0-9]*$/.test(String(id || ''))) return false;
        path = attr === 'data-arena-id' ? 'arena?ref=' + id : 'ice?city_id=' + id;
      }
    }
    var url = new URL(resolveWebappPath(path, loc), loc.href);
    query.forEach(function (value, key) {
      if (hockeyList && (key === 'city' || key === 'club')) return;
      if (!url.searchParams.has(key)) url.searchParams.set(key, value);
    });
    if (p.indexOf('/c/') === 0 && !url.searchParams.has('when') && query.get('w')) {
      url.searchParams.set('when', query.get('w'));
    }
    if (!url.searchParams.has('init_data') && !hashParams.get('tgWebAppData') && tg && tg.initData) {
      url.searchParams.set('init_data', tg.initData);
    }
    try {
      if (target && storage) storage.setItem(DEEP_LINK_FLAG, sp);
    } catch (e3) { /* */ }
    loc.replace(url.pathname + url.search + (loc.hash || ''));
    return true;
  }

  /**
   * Синхронный redirect из <head> entry-страницы. Возвращает true, если ушли со страницы.
   */
  function maybeEarlyRedirect(ctx) {
    ctx = ctx || {};
    var loc = ctx.location || (typeof location !== 'undefined' ? location : null);
    var storage = ctx.sessionStorage;
    if (!loc || !/^\/(?:webapp|static\/webapp)\//.test(loc.pathname || '')) return false;
    if (!storage && typeof sessionStorage !== 'undefined') storage = sessionStorage;
    var sp = String(readStartParam(ctx) || '').trim();
    /* Arena startapp ждёт mini_app_server_place_card из /client/session — обрабатывает shell. */
    if (parseArenaDeepLink(sp)) return false;
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
    parseArenaDeepLink: parseArenaDeepLink,
    arenaLegacyMiniAppPath: arenaLegacyMiniAppPath,
    arenaPlacePath: arenaPlacePath,
    resolveArenaDeepLinkTarget: resolveArenaDeepLinkTarget,
    deepLinkTarget: deepLinkTarget,
    pathnameKey: pathnameKey,
    isAlreadyOnTarget: isAlreadyOnTarget,
    resolveWebappPath: resolveWebappPath,
    maybePublicRedirect: maybePublicRedirect,
    maybeEarlyRedirect: maybeEarlyRedirect,
  };
});

/* entry-страница подключает этот файл синхронно в <head> — уходим до разбора body */
(function () {
  if (typeof window === 'undefined' || !window.GlideDeepLink) return;
  function recover() {
    return window.GlideDeepLink.maybePublicRedirect(window);
  }
  try {
    if (!recover()) window.GlideDeepLink.maybeEarlyRedirect(window);
    window.document.addEventListener('DOMContentLoaded', recover);
    window.addEventListener('pageshow', recover);
  } catch (e) { /* не ломаем загрузку хаба */ }
})();
