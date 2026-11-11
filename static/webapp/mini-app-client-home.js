/**
 * Client mini apps: navigate to hub (client-home) preserving Telegram init_data in URL.
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

  function navigateClientHome() {
    /* Canonical app route is /webapp/client-home (no .html) — see src/api/app.py */
    window.location.href = withInit(webappBasePath() + 'client-home');
  }

  window.navigateClientHome = navigateClientHome;

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
    /* TASK-375: при season_ui «назад» на страницах из «Ещё» (data-season-back) виден всегда:
       история есть — history.back(), нет — client-me. Флаг выключен — ветка ниже не меняется. */
    var S = window.ClientSeasonBack;
    if (S && btn.hasAttribute('data-season-back') && S.isSeasonUi(window)) {
      btn.hidden = false;
      btn.onclick = function () {
        S.goBack(window);
      };
      return;
    }
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
    if (b) b.onclick = navigateClientHome;
    wireBack();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
