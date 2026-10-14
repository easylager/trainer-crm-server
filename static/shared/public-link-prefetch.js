/**
 * Prefetch только HTML /, /c/, /p/ по намерению (FEEL-A).
 * Один <link rel=prefetch> на href; просмотр — через public-page-view-beacon.js.
 */
(function (root) {
  'use strict';

  var prefetched = typeof Set !== 'undefined' ? new Set() : null;
  var hoverTimer = null;
  var HOVER_MS = 65;

  function connectionSlowOrSaveData() {
    var nav = root.navigator;
    if (!nav) return false;
    if (nav.connection && nav.connection.saveData) return true;
    var et = nav.connection && nav.connection.effectiveType;
    return et === '2g' || et === 'slow-2g';
  }

  function isHtmlCatalogPage(pathname) {
    if (pathname === '/') return true;
    if (!/^\/(c|p)\/[^/]+/.test(pathname)) return false;
    var lower = pathname.toLowerCase();
    if (lower.endsWith('.png') || lower.endsWith('.webp') || lower.endsWith('.jpg')) return false;
    if (/\/og\.png$|\/story\.png$|\/story$/.test(lower)) return false;
    return true;
  }

  function linkFromEvent(ev) {
    var el = ev.target;
    if (!el || !el.closest) return null;
    var a = el.closest('a[href]');
    if (!a || (a.hasAttribute && a.hasAttribute('download'))) return null;
    return a;
  }

  function prefetchHref(href) {
    if (!href || !prefetched || !root.document || connectionSlowOrSaveData()) return;
    try {
      var u = new URL(href, root.location.href);
      if (u.origin !== root.location.origin) return;
      if (!isHtmlCatalogPage(u.pathname)) return;
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

  function onPointerDown(ev) {
    if (ev.pointerType !== 'touch') return;
    var a = linkFromEvent(ev);
    if (!a) return;
    prefetchHref(a.href);
  }

  function onPointerEnter(ev) {
    if (ev.pointerType && ev.pointerType !== 'mouse') return;
    var a = linkFromEvent(ev);
    if (!a) return;
    if (hoverTimer) clearTimeout(hoverTimer);
    var href = a.href;
    hoverTimer = setTimeout(function () {
      hoverTimer = null;
      prefetchHref(href);
    }, HOVER_MS);
  }

  function clearHover() {
    if (hoverTimer) {
      clearTimeout(hoverTimer);
      hoverTimer = null;
    }
  }

  if (root.document) {
    root.document.addEventListener('pointerdown', onPointerDown, { passive: true });
    root.document.addEventListener('pointerenter', onPointerEnter, { passive: true });
    root.document.addEventListener('pointerleave', clearHover, { passive: true });
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
