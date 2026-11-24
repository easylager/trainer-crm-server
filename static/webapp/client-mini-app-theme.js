/**
 * Единая CRM-палитра для клиентских Mini App.
 * Telegram colorScheme — источник истины (не prefers-color-scheme ОС).
 * Подключать сразу после telegram-web-app.js, ДО theme.css.
 */
(function () {
  /*
   * ЗНАЧЕНИЯ ЗЕРКАЛЯТ theme.css (см. mini-app-trainer-theme.js — тот же контракт).
   * Telegram ставит свои --tg-theme-* инлайном, поэтому здесь мы перебиваем их
   * через !important; любое расхождение с theme.css выиграет ЭТОТ файл.
   * Обоснование палитры: design/prototypes/2026-08-26-glide-color-concepts.html
   */
  var GLIDE_CTA_FILL = '#45B9BB';
  var GLIDE_CTA_TEXT = '#04262A';
  /* ICE PAPER: холодная бумага вместо кремовой. */
  var LIGHT_BG = '#F1F3F2';
  var LIGHT_SURFACE = '#FFFFFF';
  var LIGHT_TEXT = '#101617';
  var LIGHT_HINT = '#5E6B6B';
  /* ARENA: ахроматические нейтрали, мягкий белый текст (не #ffffff — ореол на OLED). */
  var DARK_BG = '#0B0C0E';
  var DARK_SURFACE = '#141618';
  var DARK_TEXT = '#E6E9EA';
  var DARK_HINT = '#868D93';
  var ACCENT_RGB = '69, 185, 187';

  function getTg() {
    return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  }

  /* TASK-445 (glide-home-v1): у аккаунтов redesign_s1 все экраны светлые — тема Telegram
     не перекрашивает. PDEC-040 батч C: под redesign_s4 светлая пинится и на старых
     страницах Лёд/каток/«Я» — v2-экраны в её мире только светлые. Признак читаем
     из того же кэша флагов, что и оболочка (cw_ui_flags_v1), синхронно до первого
     кадра; свежее значение придёт событием client-shell:ui-flags — на него
     переприменяем тему. */
  var REDESIGN_BG = '#f5f6f8';
  /* PDEC-040 батч C (рескин): под s4 светлые и старые страницы, которые
     .gv2skin перекрашивает под v2 — v2-экраны тёмной темы не имеют. */
  var REDESIGN_S4_PAGES = { ice: 1, arena: 1, 'client-me': 1, 'client-home': 1 };
  function themePageKey() {
    var p = (window.location && window.location.pathname || '').replace(/\/$/, '');
    return (p.split('/').pop() || '').replace(/\.html$/, '');
  }
  function redesignPinned() {
    try {
      var tg = getTg();
      var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
      var uid = u && u.id != null ? String(u.id) : '';
      if (!uid) return false;
      var c = JSON.parse(window.localStorage.getItem('cw_ui_flags_v1') || 'null');
      if (!c || String(c.u) !== uid) return false;
      if (c.redesign_s1 === true) return true;
      return !!(c.redesign_s4 === true && REDESIGN_S4_PAGES[themePageKey()]);
    } catch (e) {
      return false;
    }
  }

  function isAppDark() {
    /* data-force-theme на <html> — жёсткий замок экрана (витрина тренеров всегда светлая,
       новая главная v2 — тоже). */
    var forced = document.documentElement.getAttribute('data-force-theme');
    if (forced === 'light') return false;
    if (forced === 'dark') return true;
    if (redesignPinned()) return false;
    var tg = getTg();
    if (tg && tg.colorScheme) return tg.colorScheme === 'dark';
    return false;
  }

  function applyTelegramChromeColors(dark) {
    var tg = getTg();
    if (!tg) return;
    var pinned = redesignPinned();
    var bgHex = pinned ? REDESIGN_BG : dark ? DARK_BG : LIGHT_BG;
    try {
      if (pinned) {
        /* Своя палитра передаётся только с Bot API 6.1/7.10 — через isVersionAtLeast,
           иначе старые клиенты молча её игнорируют или падают. */
        var v = typeof tg.isVersionAtLeast === 'function' ? tg.isVersionAtLeast.bind(tg) : function () { return false; };
        if (v('6.1')) {
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        }
        if (v('7.10') && typeof tg.setBottomBarColor === 'function') tg.setBottomBarColor(bgHex);
        return;
      }
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
    /* Сайтные --g-* (каталог, катки, хаб) переключаются по body.tg-dark. */
    if (document.body) document.body.classList.toggle('tg-dark', dark);
    if (d.hasAttribute('data-client-requests')) {
      d.classList.toggle('client-requests--dark', dark);
    }
    d.style.setProperty('--app-cta-fill', GLIDE_CTA_FILL, 'important');
    d.style.setProperty('--app-cta-text', GLIDE_CTA_TEXT, 'important');
    d.style.setProperty('--tg-theme-button-color', GLIDE_CTA_FILL, 'important');
    d.style.setProperty('--tg-theme-button-text-color', GLIDE_CTA_TEXT, 'important');
    d.style.setProperty('--accent-rgb', ACCENT_RGB, 'important');
    d.style.setProperty('--accent-rgb-alt', ACCENT_RGB, 'important');
    d.style.setProperty('--tg-theme-bg-color', redesignPinned() ? REDESIGN_BG : dark ? DARK_BG : LIGHT_BG, 'important');
    d.style.setProperty('--tg-theme-text-color', dark ? DARK_TEXT : LIGHT_TEXT, 'important');
    d.style.setProperty(
      '--tg-theme-secondary-bg-color',
      dark ? DARK_SURFACE : LIGHT_SURFACE,
      'important'
    );
    d.style.setProperty('--tg-theme-hint-color', dark ? DARK_HINT : LIGHT_HINT, 'important');
    d.style.setProperty('--app-danger', dark ? '#FF6B60' : '#C4342A', 'important');
    d.style.colorScheme = dark ? 'dark' : 'light';

    applyTelegramChromeColors(dark);
  }

  function bindThemeEvents() {
    var tg = getTg();
    if (tg && typeof tg.onEvent === 'function') {
      try {
        tg.onEvent('themeChanged', applyClientMiniAppTheme);
      } catch (e) {
        /* older clients */
      }
    }
    /* Флаги доехали с сервера — переприменяем тему (кэш мог быть пустым на старте). */
    if (typeof window.addEventListener === 'function') {
      window.addEventListener('client-shell:ui-flags', function () {
        setTimeout(applyClientMiniAppTheme, 0);
      });
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
