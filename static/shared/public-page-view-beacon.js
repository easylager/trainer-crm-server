/**
 * Учёт просмотра /, /c/, /p/ через sendBeacon (FEEL-A).
 * Шлём сразу при разборе страницы, а не на pageshow: тот ждёт все картинки, и кто уходил
 * раньше, просмотром не становился. Возврат из bfcache скрипт заново не выполняет — его
 * не считаем. Пререндер Chrome ждём до показа страницы человеку.
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

  var doc = root.document;
  if (doc && doc.prerendering) {
    doc.addEventListener('prerenderingchange', send, { once: true });
  } else {
    send();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
