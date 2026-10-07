/**
 * Публичный URL места для анонимного веб-каталога (TASK-191-B).
 * Путь приходит с API как ``public_path`` (серверный place_path / city_slug).
 * В Telegram Mini App остаётся arena?ref=…
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.CatalogPublicUrl = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function isTelegramMiniApp() {
    var g = typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : null;
    var tg = g && g.Telegram && g.Telegram.WebApp;
    var initData = tg && tg.initData;
    return !!(initData && String(initData).length > 0);
  }

  function publicHrefFromItem(item) {
    var path = item && item.public_path;
    if (!path) return null;
    var live = (item && item.live) || {};
    if (String(live.kind || '') === 'session' && live.session_id != null) {
      return path + '?s=' + encodeURIComponent(String(live.session_id));
    }
    return path;
  }

  function arenaHref(item, miniAppHref) {
    if (isTelegramMiniApp()) {
      return miniAppHref;
    }
    var pub = publicHrefFromItem(item);
    return pub || miniAppHref;
  }

  return {
    isTelegramMiniApp: isTelegramMiniApp,
    publicHrefFromItem: publicHrefFromItem,
    arenaHref: arenaHref,
  };
});
