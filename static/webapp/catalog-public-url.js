/**
 * Публичный URL места для анонимного веб-каталога (TASK-191-B).
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

  function slugifyCity(name) {
    return String(name || '')
      .trim()
      .toLowerCase()
      .replace(/ё/g, 'е')
      .replace(/[^a-z0-9а-я]+/gi, '-')
      .replace(/^-+|-+$/g, '');
  }

  function isTelegramMiniApp() {
    var g = typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : null;
    var tg = g && g.Telegram && g.Telegram.WebApp;
    return !!(tg && (tg.initData || tg.platform));
  }

  function publicPlacePath(item, cityName) {
    var slug = item && item.slug;
    var city = cityName || (item && (item.city_name || item.city)) || '';
    if (!slug || !city) return null;
    return '/p/' + encodeURIComponent(slugifyCity(city)) + '/' + encodeURIComponent(String(slug));
  }

  function arenaHref(item, cityName, miniAppHref) {
    if (isTelegramMiniApp()) {
      return miniAppHref;
    }
    var pub = publicPlacePath(item, cityName);
    return pub || miniAppHref;
  }

  return {
    slugifyCity: slugifyCity,
    isTelegramMiniApp: isTelegramMiniApp,
    publicPlacePath: publicPlacePath,
    arenaHref: arenaHref,
  };
});
