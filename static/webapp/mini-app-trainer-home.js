/**
 * Trainer mini apps: navigate to hub (trainer-home.html) preserving Telegram init_data in URL.
 * Wires #btnHome when present (DOM ready or immediately if DOM already loaded).
 */
(function () {
  function webappBasePath() {
    var p = window.location.pathname || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function withInit(url) {
    var tg = window.Telegram && window.Telegram.WebApp;
    var initData = tg && tg.initData ? tg.initData : '';
    if (!initData) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
  }

  /**
   * @param { { subscriptionCelebrationHint?: boolean, reopenGroupSlot?: number|string } } [opts]
   *   subscriptionCelebrationHint: append hub_celebrate=1 so hub can show banner if sessionStorage was cleared (Telegram WebView).
   *   reopenGroupSlot: trainer-home reopens group modal (return from booking detail opened from hub modal).
   */
  function navigateTrainerHome(opts) {
    opts = opts || {};
    /* Canonical app route is /webapp/trainer-home (no .html) — see src/api/app.py */
    var url = withInit(webappBasePath() + 'trainer-home');
    if (opts.subscriptionCelebrationHint) {
      url += (url.indexOf('?') >= 0 ? '&' : '?') + 'hub_celebrate=1';
    }
    if (opts.reopenGroupSlot != null && opts.reopenGroupSlot !== '') {
      var sid = parseInt(String(opts.reopenGroupSlot), 10);
      if (!isNaN(sid) && sid > 0) {
        url += (url.indexOf('?') >= 0 ? '&' : '?') + 'reopen_group_slot=' + encodeURIComponent(String(sid));
      }
    }
    window.location.href = url;
  }

  window.navigateTrainerHome = navigateTrainerHome;

  function canBrowserGoBack() {
    try {
      if (window.navigation && typeof window.navigation.canGoBack === 'function') {
        return window.navigation.canGoBack();
      }
    } catch (e) { /* older WebViews */ }
    return window.history && window.history.length > 1;
  }

  function wireBack() {
    var btn = document.getElementById('btnBack');
    if (!btn || btn.getAttribute('data-skip-history-back') === 'true') return;
    function sync() {
      btn.hidden = !canBrowserGoBack();
    }
    btn.onclick = function () {
      window.history.back();
    };
    sync();
    window.addEventListener('popstate', sync);
  }

  function wire() {
    var b = document.getElementById('btnHome');
    if (b) b.onclick = navigateTrainerHome;
    wireBack();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
