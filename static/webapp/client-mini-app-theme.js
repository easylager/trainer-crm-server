/**
 * Единая CRM-палитра для клиентских Mini App.
 * Telegram colorScheme — источник истины (не prefers-color-scheme ОС).
 * Подключать сразу после telegram-web-app.js, ДО theme.css.
 */
(function () {
  var GLIDE_CTA_FILL = '#34C6C4';
  var GLIDE_CTA_TEXT = '#062A29';
  var LIGHT_BG = '#FBFAF7';
  var LIGHT_SURFACE = '#FFFFFF';
  var LIGHT_TEXT = '#16292A';
  var DARK_BG = '#1c1c1c';
  var DARK_SURFACE = '#2c2c2e';

  function getTg() {
    return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  }

  function isAppDark() {
    var tg = getTg();
    if (tg && tg.colorScheme) return tg.colorScheme === 'dark';
    return false;
  }

  function applyTelegramChromeColors(dark) {
    var tg = getTg();
    if (!tg) return;
    var bgHex = dark ? DARK_BG : LIGHT_BG;
    try {
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
      if (typeof tg.setBottomBarColor === 'function') tg.setBottomBarColor(bgHex);
    } catch (e) {
      /* older clients */
    }
  }

  function applyClientMiniAppTheme() {
    var d = document.documentElement;
    var dark = isAppDark();
    d.classList.toggle('client-mini-dark', dark);
    d.classList.toggle('trainer-theme-light', !dark);
    d.classList.toggle('trainer-theme-dark', dark);
    d.classList.toggle('hub-is-dark', dark);
    d.classList.toggle('sub-root-dark', dark);
    d.setAttribute('data-app-theme', dark ? 'dark' : 'light');
    if (d.hasAttribute('data-client-requests')) {
      d.classList.toggle('client-requests--dark', dark);
    }
    d.style.setProperty('--app-cta-fill', GLIDE_CTA_FILL, 'important');
    d.style.setProperty('--app-cta-text', GLIDE_CTA_TEXT, 'important');
    d.style.setProperty('--tg-theme-button-color', GLIDE_CTA_FILL, 'important');
    d.style.setProperty('--tg-theme-button-text-color', GLIDE_CTA_TEXT, 'important');
    d.style.setProperty('--accent-rgb', '52, 198, 196', 'important');
    d.style.setProperty('--accent-rgb-alt', '52, 198, 196', 'important');
    d.style.setProperty('--tg-theme-bg-color', dark ? DARK_BG : LIGHT_BG, 'important');
    d.style.setProperty('--tg-theme-text-color', dark ? '#ffffff' : LIGHT_TEXT, 'important');
    d.style.setProperty(
      '--tg-theme-secondary-bg-color',
      dark ? DARK_SURFACE : LIGHT_SURFACE,
      'important'
    );
    d.style.setProperty('--tg-theme-hint-color', dark ? '#8e8e93' : '#666666', 'important');
    d.style.setProperty('--app-danger', '#ff3b30', 'important');
    d.style.colorScheme = dark ? 'dark' : 'light';

    applyTelegramChromeColors(dark);
  }

  function bindThemeEvents() {
    var tg = getTg();
    if (!tg || typeof tg.onEvent !== 'function') return;
    try {
      tg.onEvent('themeChanged', applyClientMiniAppTheme);
    } catch (e) {
      /* older clients */
    }
  }

  function boot() {
    applyClientMiniAppTheme();
    bindThemeEvents();
    var tg = getTg();
    if (tg && typeof tg.ready === 'function') tg.ready();
    [0, 50, 120, 300, 800, 1500].forEach(function (ms) {
      setTimeout(applyClientMiniAppTheme, ms);
    });
  }

  boot();

  window.__applyClientMiniAppTheme = applyClientMiniAppTheme;
  window.__applyClientHubTheme = applyClientMiniAppTheme;
  window.__applyCatalogTheme = applyClientMiniAppTheme;
  window.__applyBookTheme = applyClientMiniAppTheme;
  window.__applyClientRequestsTheme = applyClientMiniAppTheme;
  window.__applyTelegramChromeColors = function () {
    applyTelegramChromeColors(isAppDark());
  };
})();
