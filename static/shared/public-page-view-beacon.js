/**
 * Учёт просмотра /, /c/, /p/ через sendBeacon (FEEL-A).
 * HTML может прийти из prefetch без GET на origin; bfcache-возврат (pageshow.persisted) не шлём.
 */
(function (root) {
  'use strict';

  var script = root.document && root.document.currentScript;
  if (!script) return;

  var surface = script.getAttribute('data-surface') || '';
  var cityId = script.getAttribute('data-city-id') || '';
  var arenaId = script.getAttribute('data-arena-id') || '';
  var sent = false;

  function beaconUrl() {
    var q = new URLSearchParams();
    q.set('surface', surface);
    if (cityId) q.set('city_id', cityId);
    if (arenaId) q.set('arena_id', arenaId);
    try {
      var pathname = root.location.pathname || '';
      if (pathname) q.set('path', pathname);
    } catch (e) {
      /* ignore */
    }
    try {
      var sp = new URLSearchParams(root.location.search || '');
      ['s', 'src', 'i'].forEach(function (k) {
        var v = sp.get(k);
        if (v) q.set(k, v);
      });
    } catch (e) {
      /* ignore */
    }
    return '/api/public/catalog/page-view?' + q.toString();
  }

  function send() {
    if (sent || !surface) return;
    if (!root.navigator || typeof root.navigator.sendBeacon !== 'function') return;
    sent = true;
    root.navigator.sendBeacon(beaconUrl());
  }

  root.addEventListener('pageshow', function (ev) {
    if (ev.persisted) return;
    send();
  });
})(typeof globalThis !== 'undefined' ? globalThis : this);
