/**
 * Единая CRM-палитра для клиентских Mini App (как catalog/book/client-requests).
 * Подключать сразу после telegram-web-app.js, до основных стилей страницы.
 */
(function () {
  function isAppDark() {
    var tg = window.Telegram && window.Telegram.WebApp;
    if (tg && tg.colorScheme) return tg.colorScheme === 'dark';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function applyClientMiniAppTheme() {
    var d = document.documentElement;
    var dark = isAppDark();
    d.style.setProperty('--app-cta-fill', '#f5a623', 'important');
    d.style.setProperty('--app-cta-text', '#1a1a1a', 'important');
    d.style.setProperty('--tg-theme-button-color', '#f5a623', 'important');
    d.style.setProperty('--tg-theme-button-text-color', '#1a1a1a', 'important');
    d.style.setProperty('--tg-theme-bg-color', dark ? '#1c1c1c' : '#fffbec');
    d.style.setProperty('--tg-theme-text-color', dark ? '#ffffff' : '#1a1a1a');
    d.style.setProperty('--tg-theme-secondary-bg-color', dark ? '#2c2c2e' : '#fff5e1');
    d.style.setProperty('--tg-theme-hint-color', dark ? '#8e8e93' : '#666666');
    d.style.setProperty('--app-danger', '#ff3b30');
    if (d.hasAttribute('data-client-requests')) {
      d.classList.toggle('client-requests--dark', dark);
    }
  }

  applyClientMiniAppTheme();
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyClientMiniAppTheme);
  }
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg && typeof tg.onEvent === 'function') {
    try {
      tg.onEvent('themeChanged', applyClientMiniAppTheme);
    } catch (e) {
      /* older clients */
    }
  }
  window.__applyClientMiniAppTheme = applyClientMiniAppTheme;
  window.__applyCatalogTheme = applyClientMiniAppTheme;
  window.__applyBookTheme = applyClientMiniAppTheme;
  window.__applyClientRequestsTheme = applyClientMiniAppTheme;
})();
