/**
 * Единая CRM-палитра для тренерских Mini App.
 * Telegram colorScheme — источник истины (не prefers-color-scheme ОС).
 * Подключать сразу после telegram-web-app.js, ДО theme.css.
 */
(function () {
  var GLIDE_CTA_FILL = '#34C6C4';
  var GLIDE_CTA_TEXT = '#062A29';
  /* Cream canvas (landing's --paper, design/prototypes/2026-08-24-live-link-hero.html) — was #FBFAF7, read as near-pure-white. Cards stay white for the paper/card contrast. */
  var LIGHT_BG = '#F4F2EC';
  var LIGHT_SURFACE = '#FFFFFF';
  var LIGHT_TEXT = '#16292A';
  /*
   * Dark mode: calmer near-black background + muted teal wash (was #1c1c1c bg /
   * full-strength #34C6C4 accent everywhere — read as harsh/neon on screens with
   * lots of cards). CTA buttons stay at full brand strength (GLIDE_CTA_FILL).
   */
  var DARK_BG = '#0d1515';
  var DARK_SURFACE = '#172425';
  var DARK_ACCENT_RGB = '42, 152, 146';

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
      /* Bot API 7.10+: strip above/below WebView (bot name + @username). */
      if (typeof tg.setBottomBarColor === 'function') tg.setBottomBarColor(bgHex);
    } catch (e) {
      /* older clients */
    }
  }

  function applyTrainerMiniAppTheme() {
    var d = document.documentElement;
    var dark = isAppDark();
    d.classList.toggle('trainer-theme-dark', dark);
    d.classList.toggle('trainer-theme-light', !dark);
    d.classList.toggle('hub-is-dark', dark);
    d.classList.toggle('sub-root-dark', dark);
    d.setAttribute('data-app-theme', dark ? 'dark' : 'light');
    d.style.setProperty('--app-cta-fill', GLIDE_CTA_FILL, 'important');
    d.style.setProperty('--app-cta-text', GLIDE_CTA_TEXT, 'important');
    d.style.setProperty('--tg-theme-button-color', GLIDE_CTA_FILL, 'important');
    d.style.setProperty('--tg-theme-button-text-color', GLIDE_CTA_TEXT, 'important');
    d.style.setProperty('--accent-rgb', dark ? DARK_ACCENT_RGB : '52, 198, 196', 'important');
    d.style.setProperty(
      '--accent-rgb-alt',
      dark ? DARK_ACCENT_RGB : '52, 198, 196',
      'important'
    );
    d.style.setProperty('--tg-theme-bg-color', dark ? DARK_BG : LIGHT_BG, 'important');
    d.style.setProperty(
      '--tg-theme-text-color',
      dark ? '#ffffff' : LIGHT_TEXT,
      'important'
    );
    d.style.setProperty(
      '--tg-theme-secondary-bg-color',
      dark ? DARK_SURFACE : LIGHT_SURFACE,
      'important'
    );
    d.style.setProperty('--tg-theme-hint-color', dark ? '#8e8e93' : '#666666', 'important');
    d.style.setProperty('--req-accent', GLIDE_CTA_FILL, 'important');
    d.style.setProperty('--req-accent-deep', '#1FA5A3', 'important');
    d.style.colorScheme = dark ? 'dark' : 'light';

    applyTelegramChromeColors(dark);
  }

  function bindThemeEvents() {
    var tg = getTg();
    if (!tg) return;
    if (typeof tg.onEvent === 'function') {
      try {
        tg.onEvent('themeChanged', applyTrainerMiniAppTheme);
      } catch (e) {
        /* older clients */
      }
    }
  }

  function boot() {
    applyTrainerMiniAppTheme();
    bindThemeEvents();
    var tg = getTg();
    if (tg && typeof tg.ready === 'function') tg.ready();
    /* Re-lock after Telegram applies themeParams (often overwrites button_color to amber). */
    [0, 50, 120, 300, 800, 1500].forEach(function (ms) {
      setTimeout(applyTrainerMiniAppTheme, ms);
    });
  }

  boot();

  window.__applyTrainerMiniAppTheme = applyTrainerMiniAppTheme;
  window.__applyTrainerHomeTheme = applyTrainerMiniAppTheme;
  window.__applyTrainerClientsTheme = applyTrainerMiniAppTheme;
  window.__applyTrainerGroupsTheme = applyTrainerMiniAppTheme;
  window.__applyTrainerPassProductsTheme = applyTrainerMiniAppTheme;
  window.__applyScheduleEditorTheme = applyTrainerMiniAppTheme;
  window.__applySubscriptionTheme = applyTrainerMiniAppTheme;
  window.__applyRequestsTheme = applyTrainerMiniAppTheme;
  window.__applyTelegramChromeColors = function () {
    applyTelegramChromeColors(isAppDark());
  };
})();
