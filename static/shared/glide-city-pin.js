/**
 * Город открытой страницы /c/ и /p/ пишется в glide_city на каждый pageshow.
 * Повтор из HTTP-кэша и возврат из bfcache не исполняют Set-Cookie ответа.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    var api = factory();
    root.GlideCityPin = api;
    if (api.wireGlideCityPin) api.wireGlideCityPin(root);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function wireGlideCityPin(g, opts) {
    opts = opts || {};
    var doc = g && g.document;
    var script = opts.script || (doc && doc.currentScript);
    var slug = opts.slug || (script && script.getAttribute && script.getAttribute('data-glide-city'));
    if (!slug || !g || typeof g.addEventListener !== 'function') return;
    var fetchFn = opts.fetch || g.fetch;
    if (typeof fetchFn !== 'function') return;

    function pin() {
      fetchFn('/api/public/glide-city', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug: slug }),
        keepalive: true,
      }).catch(function () {});
    }

    g.addEventListener('pageshow', pin);
  }

  return { wireGlideCityPin: wireGlideCityPin };
});
