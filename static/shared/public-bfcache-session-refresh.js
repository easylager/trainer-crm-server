/**
 * После возврата из bfcache (pageshow.persisted): если страница открыта >10 мин назад,
 * тихо подтягиваем HTML и меняем только блок списка сеансов.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    var api = factory();
    root.GlideBfCacheSessionRefresh = api;
    if (api.wireBfCacheSessionRefresh) {
      api.wireBfCacheSessionRefresh(root);
    }
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var STALE_MS = 10 * 60 * 1000;
  var LIST_SELECTOR = '[data-glide-session-list-root]';

  function findSessionListRoot(doc) {
    if (!doc || typeof doc.querySelector !== 'function') return null;
    var marked = doc.querySelector(LIST_SELECTOR);
    if (marked) return marked;
    return doc.getElementById ? doc.getElementById('schedule') : null;
  }

  function wireBfCacheSessionRefresh(g, opts) {
    opts = opts || {};
    var fetchFn = opts.fetch || (g && g.fetch);
    var DOMParserCtor = opts.DOMParser || (g && g.DOMParser);
    var nowFn = opts.now || function () {
      return Date.now();
    };
    if (!g || typeof g.addEventListener !== 'function' || !g.document || !fetchFn || !DOMParserCtor) {
      return;
    }

    var loadedAt = nowFn();

    g.addEventListener('pageshow', function (ev) {
      if (!ev || !ev.persisted) return;
      if (nowFn() - loadedAt < STALE_MS) return;

      var rootEl = findSessionListRoot(g.document);
      if (!rootEl) return;

      var scrollY = (g.scrollY != null ? g.scrollY : g.pageYOffset) || 0;
      var url = (g.location.pathname || '') + (g.location.search || '');

      fetchFn(url, { credentials: 'same-origin', headers: { Accept: 'text/html' } })
        .then(function (res) {
          if (!res || !res.ok) throw new Error('fetch');
          return res.text();
        })
        .then(function (html) {
          var doc = new DOMParserCtor().parseFromString(html, 'text/html');
          var fresh = findSessionListRoot(doc);
          if (!fresh) return;
          rootEl.innerHTML = fresh.innerHTML;
          if (typeof g.scrollTo === 'function') {
            g.scrollTo(0, scrollY);
          }
        })
        .catch(function () {});
    });
  }

  return {
    STALE_MS: STALE_MS,
    findSessionListRoot: findSessionListRoot,
    wireBfCacheSessionRefresh: wireBfCacheSessionRefresh,
  };
});
