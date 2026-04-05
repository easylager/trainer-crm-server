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

  function navigateTrainerHome() {
    /* Canonical app route is /webapp/trainer-home (no .html) — see src/api/app.py */
    window.location.href = withInit(webappBasePath() + 'trainer-home');
  }

  window.navigateTrainerHome = navigateTrainerHome;

  function wire() {
    var b = document.getElementById('btnHome');
    if (b) b.onclick = navigateTrainerHome;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
