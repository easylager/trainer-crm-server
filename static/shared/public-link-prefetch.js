/**
 * Предзагрузка только той ссылки, которой коснулись (FEEL-A).
 * Один <link rel=prefetch> на href; prefetch-запрос не считается просмотром на сервере.
 */
(function (root) {
  'use strict';

  var prefetched = typeof Set !== 'undefined' ? new Set() : null;

  function isPublicCatalogPath(pathname) {
    return pathname === '/' || /^\/c\//.test(pathname) || /^\/p\//.test(pathname);
  }

  function prefetchHref(href) {
    if (!href || !prefetched || !root.document) return;
    try {
      var u = new URL(href, root.location.href);
      if (u.origin !== root.location.origin) return;
      if (!isPublicCatalogPath(u.pathname)) return;
      var key = u.pathname + u.search;
      if (prefetched.has(key)) return;
      prefetched.add(key);
      var link = root.document.createElement('link');
      link.rel = 'prefetch';
      link.href = key;
      root.document.head.appendChild(link);
    } catch (e) {
      /* ignore bad href */
    }
  }

  function onTouchLink(ev) {
    var el = ev.target;
    if (!el || !el.closest) return;
    var a = el.closest('a[href]');
    if (!a) return;
    prefetchHref(a.href);
  }

  if (root.document) {
    root.document.addEventListener('pointerdown', onTouchLink, { passive: true });
    root.document.addEventListener('touchstart', onTouchLink, { passive: true });
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
