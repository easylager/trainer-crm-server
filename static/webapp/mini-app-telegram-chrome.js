/**
 * Mini App host bootstrap: runtime detection, auth material for API calls, Telegram chrome quirks, theme aliases.
 * Telegram stays the default; other hosts can extend MiniAppRuntime before this script (override getCredential / ready).
 */
(function (global) {
  'use strict';

  function detectPlatformId() {
    if (global.Telegram && global.Telegram.WebApp) return 'telegram';
    return 'unknown';
  }

  /** @type {'telegram'|'unknown'} */
  var platformId = detectPlatformId();

  function getTg() {
    return global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null;
  }

  /**
   * Raw credential string for the current host (Telegram: WebApp.initData).
   * Other hosts: set MiniAppRuntime._credentialOverride to a non-empty string before API calls.
   */
  function getCredential() {
    var rt = global.MiniAppRuntime;
    if (rt && typeof rt._credentialOverride === 'string' && rt._credentialOverride.length) {
      return rt._credentialOverride;
    }
    var tg = getTg();
    if (platformId === 'telegram' && tg && tg.initData) return String(tg.initData);
    return '';
  }

  /**
   * HTTP headers for /api/webapp/* (Telegram keeps X-Telegram-Init-Data until API exposes a neutral name).
   */
  function authHeaders() {
    var c = getCredential();
    var h = {};
    if (c) {
      h['X-Telegram-Init-Data'] = c;
      h['X-Mini-App-Platform'] = platformId;
    }
    return h;
  }

  function appendInitToUrl(url) {
    var c = getCredential();
    if (!c) return url;
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    return url + sep + 'init_data=' + encodeURIComponent(c);
  }

  /** Map Telegram themeParams + CSS vars → stable --miniapp-* tokens for non-Tg hosts later. */
  function applyThemeAliases() {
    var root = document.documentElement;
    var tg = getTg();
    if (tg && tg.themeParams) {
      var tp = tg.themeParams;
      function hex(key) {
        var v = tp[key];
        if (v == null || v === '') return null;
        return String(v).indexOf('#') === 0 ? String(v) : '#' + String(v);
      }
      var pairs = [
        ['bg_color', '--miniapp-bg'],
        ['text_color', '--miniapp-text'],
        ['hint_color', '--miniapp-hint'],
        ['link_color', '--miniapp-link'],
        ['button_color', '--miniapp-button'],
        ['button_text_color', '--miniapp-button-text'],
        ['secondary_bg_color', '--miniapp-secondary-bg']
      ];
      for (var i = 0; i < pairs.length; i++) {
        var hx = hex(pairs[i][0]);
        if (hx) root.style.setProperty(pairs[i][1], hx);
      }
    }
    /* Fallback: mirror computed --tg-theme-* when SDK did not fill themeParams yet */
    var mirror = [
      ['--miniapp-bg', '--tg-theme-bg-color'],
      ['--miniapp-text', '--tg-theme-text-color'],
      ['--miniapp-hint', '--tg-theme-hint-color'],
      ['--miniapp-link', '--tg-theme-link-color'],
      ['--miniapp-button', '--tg-theme-button-color'],
      ['--miniapp-button-text', '--tg-theme-button-text-color'],
      ['--miniapp-secondary-bg', '--tg-theme-secondary-bg-color']
    ];
    try {
      var cs = global.getComputedStyle(root);
      for (var j = 0; j < mirror.length; j++) {
        var to = mirror[j][0];
        var from = mirror[j][1];
        if (root.style.getPropertyValue(to)) continue;
        var val = cs.getPropertyValue(from);
        if (val && String(val).trim()) root.style.setProperty(to, String(val).trim());
      }
    } catch (e) { /* noop */ }
  }

  function runtimeReady() {
    var tg = getTg();
    if (tg) {
      if (typeof tg.ready === 'function') tg.ready();
    }
    applyThemeAliases();
    if (tg && typeof tg.onEvent === 'function') {
      try {
        tg.onEvent('themeChanged', function () {
          applyThemeAliases();
        });
      } catch (e1) { /* noop */ }
    }
  }

  global.MiniAppRuntime = {
    platformId: platformId,
    /** @type {string|null} Non-null override for hosts without Telegram.WebApp.initData. */
    _credentialOverride: null,
    getCredential: getCredential,
    authHeaders: authHeaders,
    appendInitToUrl: appendInitToUrl,
    applyThemeAliases: applyThemeAliases,
    ready: runtimeReady
  };
})(window);

/**
 * Telegram Mini App: keep native header as close (X), not BackButton.
 * Calling WebApp.BackButton.show() replaces the X with a system back arrow — avoid that globally.
 */
(function () {
  if (window.MiniAppRuntime) window.MiniAppRuntime.ready();
  var tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) return;
  if (tg.BackButton) {
    tg.BackButton.hide();
    try {
      tg.BackButton.onClick(function () {});
    } catch (e) { /* noop */ }
  }
})();

/**
 * Open a private Telegram chat from Mini App.
 * - https://t.me/… — WebApp.openTelegramLink / openLink (works in web + native).
 * - tg://user?id=… — do NOT use WebApp APIs: they log "Url protocol is not supported" and burn the
 *   user-gesture, so the browser then blocks the fallback. Use sync location.assign on native; on
 *   platform=web, tg:// is unsupported — prefer t.me (API can fill username via getChat) or showAlert.
 */
window.openTelegramChatFromMiniApp = function (opts) {
  if (window.MiniAppRuntime && window.MiniAppRuntime.platformId !== 'telegram') {
    return false;
  }
  opts = opts || {};
  var un = String(opts.username || '').replace(/^@/, '').trim();
  var tid = opts.telegramId;
  var url;
  if (un) {
    url = 'https://t.me/' + encodeURIComponent(un);
  } else if (tid != null && tid !== '') {
    url = 'tg://user?id=' + encodeURIComponent(String(tid));
  } else {
    return false;
  }

  var w = window.Telegram && window.Telegram.WebApp;
  var isTgUser = url.indexOf('tg://') === 0;
  var isTme = url.indexOf('https://t.me/') === 0;

  if (isTgUser) {
    if (w && w.platform === 'web') {
      if (typeof w.showAlert === 'function') {
        try {
          w.showAlert(
            'В браузерной версии Telegram нельзя открыть чат только по внутреннему ID. Обновите «Ближайшие записи» — подтянется @username, или откройте тот же мини-апп в приложении Telegram на телефоне.'
          );
        } catch (e0) { /* noop */ }
      }
      return false;
    }
    try {
      window.location.assign(url);
    } catch (e1) { /* noop */ }
    return true;
  }

  if (isTme && w) {
    if (typeof w.openTelegramLink === 'function') {
      try {
        w.openTelegramLink(url);
        return true;
      } catch (e) { /* continue */ }
    }
    if (typeof w.openLink === 'function') {
      try {
        w.openLink(url, { try_instant_view: false });
        return true;
      } catch (e2) {
        try {
          w.openLink(url);
          return true;
        } catch (e3) { /* continue */ }
      }
    }
  }

  try {
    var a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener noreferrer';
    a.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;pointer-events:auto;';
    a.target = '_blank';
    (document.body || document.documentElement).appendChild(a);
    a.click();
    setTimeout(function () {
      try {
        if (a && a.parentNode) a.parentNode.removeChild(a);
      } catch (x) { /* noop */ }
    }, 0);
  } catch (e4) { /* continue */ }
  try {
    window.location.href = url;
  } catch (e5) { /* noop */ }
  return true;
};

/**
 * Native «Поделиться» из Mini App: `t.me/share/url` **обязан** содержать `url=`, иначе клиент
 * открывает веб-страницу шаринга во внешнем браузере (страница «установите Telegram»).
 *
 * Текст (`text=`) — без дубля URL из первой строки (или последней — совместимость со старым форматом).
 *
 * @param {{ shareUrl?: string, share_url?: string, shareBody?: string, share_body?: string, fullMessage?: string }} opts
 * @returns {boolean}
 */
window.openTelegramShareUrlFromMiniApp = function (opts) {
  opts = opts || {};
  var shareUrl = String(opts.shareUrl || opts.share_url || '').trim();
  var shareBody = String(opts.shareBody || opts.share_body || '').trim();
  var fullMessage = String(opts.fullMessage || opts.full_message || '').trim();

  if (!shareUrl && fullMessage) {
    var rawLines = fullMessage.replace(/\r\n/g, '\n').split('\n');
    while (rawLines.length && !rawLines[0].trim()) {
      rawLines.shift();
    }
    while (rawLines.length && !rawLines[rawLines.length - 1].trim()) {
      rawLines.pop();
    }
    var firstLine = rawLines.length ? rawLines[0].trim() : '';
    var lastLine = rawLines.length ? rawLines[rawLines.length - 1].trim() : '';
    if (/^https:\/\/t\.me\//i.test(firstLine)) {
      shareUrl = firstLine;
      shareBody = rawLines.slice(1).join('\n').replace(/^\s+/, '').trimEnd();
    } else if (/^https:\/\/t\.me\//i.test(lastLine)) {
      shareUrl = lastLine;
      var tail = rawLines.slice();
      tail.pop();
      while (tail.length && !tail[tail.length - 1].trim()) {
        tail.pop();
      }
      shareBody = tail.join('\n').trimEnd();
    }
  }

  if (!shareUrl) {
    var tg0 = window.Telegram && window.Telegram.WebApp;
    if (tg0 && typeof tg0.showAlert === 'function') {
      try {
        tg0.showAlert(
          'Не удалось подготовить ссылку для «Поделиться». Обновите Telegram или попробуйте позже.'
        );
      } catch (e0) {
        /* noop */
      }
    }
    return false;
  }

  var href =
    'https://t.me/share/url?url=' +
    encodeURIComponent(shareUrl) +
    (shareBody ? '&text=' + encodeURIComponent(shareBody) : '');

  var tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) return false;

  if (typeof tg.openTelegramLink === 'function') {
    try {
      tg.openTelegramLink(href);
      return true;
    } catch (e1) {
      /* fall through */
    }
  }

  if (typeof tg.showAlert === 'function') {
    try {
      tg.showAlert(
        'Не удалось открыть окно «Поделиться». Обновите приложение Telegram до последней версии.'
      );
    } catch (e2) {
      /* noop */
    }
  }
  return false;
};

/**
 * Wire «написать» buttons in hub lists (Ближайшие записи). Delegation + bubble
 * competes with parent row click on iOS; use capture on each button.
 */
window.wireHubSlotMessageButtons = function (root) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll('button.hub-slot-msg').forEach(function (btn) {
    btn.addEventListener(
      'click',
      function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (typeof window.openTelegramChatFromMiniApp === 'function') {
          window.openTelegramChatFromMiniApp({
            username: btn.getAttribute('data-dm-un'),
            telegramId: btn.getAttribute('data-dm-tid'),
          });
        }
      },
      true
    );
  });
};
