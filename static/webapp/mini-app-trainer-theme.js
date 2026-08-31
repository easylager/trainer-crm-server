/**
 * Единая CRM-палитра для тренерских Mini App.
 * Telegram colorScheme — источник истины (не prefers-color-scheme ОС).
 * Подключать сразу после telegram-web-app.js, ДО theme.css.
 */
(function () {
  /*
   * ЗНАЧЕНИЯ ЗЕРКАЛЯТ theme.css. Telegram ставит свои --tg-theme-* инлайном,
   * поэтому здесь мы перебиваем их через !important — и любое расхождение с
   * theme.css выиграет ЭТОТ файл. Меняете гамму — меняйте оба места.
   * Обоснование палитры: design/prototypes/2026-08-26-glide-color-concepts.html
   */
  var GLIDE_CTA_FILL = '#45B9BB';
  var GLIDE_CTA_TEXT = '#04262A';
  /* ICE PAPER: холодная бумага вместо кремовой — кремовая тянула тил в «клинический». */
  var LIGHT_BG = '#F1F3F2';
  var LIGHT_SURFACE = '#FFFFFF';
  var LIGHT_TEXT = '#101617';
  var LIGHT_HINT = '#5E6B6B';
  /*
   * ARENA: нейтрали ахроматические — в фоне нет ни грамма зелёного. Раньше он был
   * (#0d1515 / #172425 — это тил, сведённый в тень), поэтому акцент того же тона
   * не читался как акцент, и приходилось глушить его до 42,152,146. Теперь глушить
   * не нужно: тил идёт в полную силу бренда, но занимает только действие и активное
   * состояние.
   *
   * Текст — мягкий белый, а не #ffffff: чистый белый на почти чёрном даёт 18.5:1,
   * ореол вокруг букв на OLED и резь вечером. #E6E9EA — 16.0:1.
   */
  var DARK_BG = '#0B0C0E';
  var DARK_SURFACE = '#141618';
  var DARK_TEXT = '#E6E9EA';
  var DARK_HINT = '#868D93';
  var ACCENT_RGB = '69, 185, 187';

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
    d.style.setProperty('--accent-rgb', ACCENT_RGB, 'important');
    d.style.setProperty('--accent-rgb-alt', ACCENT_RGB, 'important');
    d.style.setProperty('--tg-theme-bg-color', dark ? DARK_BG : LIGHT_BG, 'important');
    d.style.setProperty(
      '--tg-theme-text-color',
      dark ? DARK_TEXT : LIGHT_TEXT,
      'important'
    );
    d.style.setProperty(
      '--tg-theme-secondary-bg-color',
      dark ? DARK_SURFACE : LIGHT_SURFACE,
      'important'
    );
    d.style.setProperty('--tg-theme-hint-color', dark ? DARK_HINT : LIGHT_HINT, 'important');
    d.style.setProperty('--req-accent', GLIDE_CTA_FILL, 'important');
    d.style.setProperty('--req-accent-deep', '#2E9A9C', 'important');
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
