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

  /**
   * Client hub: светлый «вечерний лёд» — не near-black: приподнятый slate + воздух, CTA бирюза, хром небесный.
   */
  function applyClientHubIceTokens(root, dark) {
    root.classList.toggle('hub-is-dark', dark);
    if (dark) {
      root.style.setProperty('--app-cta-fill', '#2dd4bf', 'important');
      root.style.setProperty('--app-cta-text', '#0f172a', 'important');
      root.style.setProperty('--tg-theme-button-color', '#2dd4bf', 'important');
      root.style.setProperty('--tg-theme-button-text-color', '#0f172a', 'important');
      root.style.setProperty('--tg-theme-bg-color', '#1e293b');
      root.style.setProperty('--tg-theme-text-color', '#f8fafc');
      root.style.setProperty('--tg-theme-secondary-bg-color', '#334155');
      root.style.setProperty('--tg-theme-hint-color', '#b8c9db');
    } else {
      root.style.setProperty('--app-cta-fill', '#14b8a6', 'important');
      root.style.setProperty('--app-cta-text', '#ffffff', 'important');
      root.style.setProperty('--tg-theme-button-color', '#14b8a6', 'important');
      root.style.setProperty('--tg-theme-button-text-color', '#ffffff', 'important');
      root.style.setProperty('--tg-theme-bg-color', '#f8fafc');
      root.style.setProperty('--tg-theme-text-color', '#0f172a');
      root.style.setProperty('--tg-theme-secondary-bg-color', '#ffffff');
      root.style.setProperty('--tg-theme-hint-color', '#64748b');
    }
    root.style.setProperty('--app-danger', '#ff3b30');
  }

  function applyClientMiniAppTheme() {
    var d = document.documentElement;
    var dark = isAppDark();
    if (d.hasAttribute('data-client-hub')) {
      applyClientHubIceTokens(d, dark);
      return;
    }
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
