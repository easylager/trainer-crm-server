/**
 * Волна 0 empty-states: клиентские цели Метрики + GA4 на публичных SSR-страницах.
 * Не трогает Mini App. Ошибки счётчиков глотаем; клики и переходы не ждём ответа.
 *
 * Подключение: <script src="/static/shared/glide-track.js" data-ym-id="…" data-ga-id="…" defer></script>
 * Контекст страницы: #glide-es-context (JSON) или data-glide-es-* на <html>.
 * Клики: [data-glide-track="es_fallback_click|es_watch_start|ticket_buy|trainer_click|telegram_cta"]
 * (ссылки и кнопки; переход не ждём).
 */
(function (root) {
  'use strict';

  var doc = root.document;
  if (!doc) return;

  var script = doc.currentScript;
  var ymId = script && script.getAttribute('data-ym-id');
  var gaId = script && script.getAttribute('data-ga-id');
  var esViewSent = false;

  function asObject(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return value;
  }

  function readContext() {
    var out = {};
    try {
      var el = doc.getElementById('glide-es-context');
      if (el && el.textContent) {
        var parsed = JSON.parse(el.textContent);
        out = asObject(parsed);
      }
    } catch (e) {
      /* ignore bad JSON */
    }
    var html = doc.documentElement;
    if (html) {
      ['state', 'page_type', 'city', 'arena_id', 'city_id', 'variant'].forEach(function (key) {
        var attr = html.getAttribute('data-glide-es-' + key.replace('_', '-'));
        if (attr && out[key] == null) out[key] = attr;
      });
    }
    return out;
  }

  function mergeParams(base, extra) {
    var out = {};
    var k;
    base = asObject(base);
    extra = asObject(extra);
    for (k in base) if (Object.prototype.hasOwnProperty.call(base, k) && base[k] != null && base[k] !== '') out[k] = base[k];
    for (k in extra) if (Object.prototype.hasOwnProperty.call(extra, k) && extra[k] != null && extra[k] !== '') out[k] = extra[k];
    return out;
  }

  function track(name, params) {
    if (!name) return;
    var payload = mergeParams(readContext(), params);
    try {
      if (ymId && typeof root.ym === 'function') {
        try {
          root.ym(Number(ymId) || ymId, 'reachGoal', String(name), payload);
        } catch (eYm) {
          /* blocked / not ready */
        }
      }
    } catch (eOuterYm) {
      /* never throw */
    }
    try {
      if (typeof root.gtag === 'function') {
        try {
          var g = mergeParams(payload, { transport_type: 'beacon' });
          if (gaId) g.send_to = gaId;
          root.gtag('event', String(name), g);
        } catch (eGa) {
          /* blocked / not ready */
        }
      }
    } catch (eOuterGa) {
      /* never throw */
    }
  }

  function fireEsViewOnce() {
    if (esViewSent) return;
    var ctx = readContext();
    if (!ctx.state) return;
    esViewSent = true;
    track('es_view', {
      state: ctx.state,
      page_type: ctx.page_type,
      city: ctx.city,
      arena_id: ctx.arena_id,
      city_id: ctx.city_id,
      variant: ctx.variant,
    });
  }

  function clickParams(a) {
    var extra = {};
    var trackName = a.getAttribute('data-glide-track') || '';
    var fallback = a.getAttribute('data-glide-fallback');
    var action = a.getAttribute('data-glide-action');
    var target = a.getAttribute('data-glide-target') || a.getAttribute('href') || '';
    var pos = a.getAttribute('data-glide-pos');
    var arenaId = a.getAttribute('data-glide-arena-id');
    var state = a.getAttribute('data-glide-state');
    var surface = a.getAttribute('data-glide-surface');
    if (fallback) extra.fallback = fallback;
    if (action) extra.action = action;
    if (target) extra.target = String(target).slice(0, 200);
    if (pos) extra.pos = pos;
    if (arenaId) extra.arena_id = arenaId;
    if (state) extra.state = state;
    if (surface) extra.surface = surface;
    if (trackName === 'es_watch_start' && !extra.arena_id) {
      try {
        var m = /(?:startapp|start)=watch_(\d+)/i.exec(a.getAttribute('href') || '');
        if (m) extra.arena_id = m[1];
      } catch (eHref) {
        /* ignore */
      }
    }
    return extra;
  }

  function onClick(ev) {
    var t = ev && ev.target;
    if (!t || !t.closest) return;
    var el = t.closest('[data-glide-track]');
    if (!el) return;
    var name = el.getAttribute('data-glide-track');
    if (!name) return;
    track(name, clickParams(el));
  }

  function boot() {
    fireEsViewOnce();
    doc.addEventListener('click', onClick, true);
  }

  root.GlideTrack = {
    track: track,
    readContext: readContext,
  };

  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);
