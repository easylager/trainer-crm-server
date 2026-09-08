/**
 * Shared empty state for the client Mini App (TASK-096, AC-002).
 *
 * Why this is not part of mini-app-client-shell.js: half the screens that need an empty state
 * (абонементы, сертификаты, покупка) deliberately do not load the shell — they have no tab bar.
 * They were left with `<div class="empty">Пока нет абонементов.</div>`: a dead end that says what
 * is missing and never what to do about it. An empty state is a component, not a shell feature.
 *
 * Contract — one rule, enforced by tests/js/client-empty-states.test.js:
 * every empty state has a way out. Either `ctaPath` (another screen), `ctaHref` (an explicit URL)
 * or `onCta` (an in-page action: retry, clear a filter, change a city). A state with no exit is
 * a bug, so `render` refuses to draw one and says so in the console.
 *
 * Requires: mini-app-components.css for `.client-empty-state` (loaded on every client screen).
 * Optional: ClientShell — used for navigation and haptics when present.
 */
(function (global) {
  'use strict';

  var ICONS = {
    // Same geometry as the shell's tab icons so an empty state reads as the same product.
    calendar:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    ice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v18M5 7l14 10M19 7L5 17"/></svg>',
    ticket:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4V8z"/><path d="M10 6v12"/></svg>',
    gift:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="9" width="18" height="12" rx="2"/><path d="M3 13h18M12 9v12"/><path d="M12 9S10.5 4 8 4a2.5 2.5 0 0 0 0 5zM12 9s1.5-5 4-5a2.5 2.5 0 0 1 0 5z"/></svg>',
    search:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    city: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 21V8l5-3v16M14 21V4l6 3v14M4 21h16"/><path d="M7 11h0M7 15h0M17 11h0M17 15h0"/></svg>',
    retry:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3.2-6.9"/><path d="M21 3v6h-6"/></svg>',
  };

  function escHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function webappBasePath() {
    var shell = global.ClientShell;
    if (shell && typeof shell.webappBasePath === 'function') return shell.webappBasePath();
    var p = (global.location && global.location.pathname) || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function haptic() {
    var shell = global.ClientShell;
    if (shell && typeof shell.hapticSelection === 'function') {
      shell.hapticSelection();
      return;
    }
    var tg = global.Telegram && global.Telegram.WebApp;
    if (tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged) {
      try {
        tg.HapticFeedback.selectionChanged();
      } catch (e) {
        /* haptics are decoration — never let them break a tap */
      }
    }
  }

  function goToPath(path) {
    var shell = global.ClientShell;
    if (shell && typeof shell.navigate === 'function') {
      shell.navigate(path);
      return;
    }
    // Shell-free screens still have to carry initData across a full page load.
    var url = webappBasePath() + path;
    if (shell && typeof shell.withInit === 'function') url = shell.withInit(url);
    else if (typeof global.withInitData === 'function') url = global.withInitData(url);
    global.location.href = url;
  }

  /**
   * @param {Element} container
   * @param {{icon?:string, title:string, hint?:string, ctaLabel:string,
   *          ctaPath?:string, ctaHref?:string, onCta?:function,
   *          secondaryLabel?:string, secondaryPath?:string, onSecondary?:function}} options
   */
  function render(container, options) {
    if (!container) return false;
    options = options || {};

    var hasExit = !!(options.ctaPath || options.ctaHref || options.onCta);
    if (!options.ctaLabel || !hasExit) {
      // Loud on purpose. AC-002 forbids «ничего не найдено» without a way forward, and a
      // silent fallback would let one back in the next time someone is in a hurry.
      if (global.console && global.console.error) {
        global.console.error(
          'MiniAppEmptyState: an empty state needs ctaLabel plus one of ctaPath/ctaHref/onCta',
          options.title || ''
        );
      }
      return false;
    }

    var icon = options.icon || ICONS.search;
    var html =
      '<div class="client-empty-state" role="status">' +
      '<div class="client-empty-state__icon">' +
      icon +
      '</div>' +
      '<p class="client-empty-state__title">' +
      escHtml(options.title) +
      '</p>';
    if (options.hint) {
      html += '<p class="client-empty-state__hint">' + escHtml(options.hint) + '</p>';
    }
    html +=
      '<button type="button" class="btn-primary btn-block client-empty-state__cta">' +
      escHtml(options.ctaLabel) +
      '</button>';
    if (options.secondaryLabel && (options.secondaryPath || options.onSecondary)) {
      html +=
        '<button type="button" class="btn-neutral btn-block client-empty-state__secondary">' +
        escHtml(options.secondaryLabel) +
        '</button>';
    }
    html += '</div>';
    container.innerHTML = html;

    var cta = container.querySelector('.client-empty-state__cta');
    if (cta) {
      cta.addEventListener('click', function () {
        haptic();
        if (typeof options.onCta === 'function') {
          options.onCta();
          return;
        }
        if (options.ctaHref) {
          global.location.href = options.ctaHref;
          return;
        }
        goToPath(options.ctaPath);
      });
    }
    var secondary = container.querySelector('.client-empty-state__secondary');
    if (secondary) {
      secondary.addEventListener('click', function () {
        haptic();
        if (typeof options.onSecondary === 'function') {
          options.onSecondary();
          return;
        }
        goToPath(options.secondaryPath);
      });
    }
    return true;
  }

  /**
   * `render` plus a last-resort text fallback, for call sites that must never leave the container
   * blank. Only fires when the state itself is malformed — a missing script is guarded at the
   * call site, the way every other shared Mini App module is used in this repo.
   */
  function renderOrFallback(container, options) {
    if (render(container, options)) return true;
    if (container && options && options.fallbackText) {
      container.innerHTML = '<div class="empty">' + escHtml(options.fallbackText) + '</div>';
    }
    return false;
  }

  global.MiniAppEmptyState = {
    ICONS: ICONS,
    render: render,
    renderOrFallback: renderOrFallback,
  };
})(window);
