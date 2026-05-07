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
        if (btn.getAttribute('data-hub-relay') === '1') {
          var Rh = window.TrainerRelayHelpers;
          if (Rh && typeof Rh.openRelayFromHubButton === 'function' && Rh.openRelayFromHubButton(btn)) {
            return;
          }
          var wg = window.Telegram && window.Telegram.WebApp;
          if (wg && typeof wg.showAlert === 'function') {
            try {
              wg.showAlert('Не удалось открыть переписку через бота. Обновите страницу или откройте мини-приложение снова.');
            } catch (eRelay) {
              /* noop */
            }
          }
          return;
        }
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

/**
 * Mini App recoverable errors (missing/flaky initData, expired auth): Russian copy + reload.
 * Backend sets X-Miniapp-Auth-Error on credential 401; fetch guard shows overlay globally.
 */
(function (global) {
  'use strict';

  var OVERLAY_ID = 'miniAppRecoverableErrorOverlay';
  var HDR = 'X-Miniapp-Auth-Error';
  var fetchGuardInstalled = false;
  var overlayShown = false;

  var LEGACY_AUTH_DETAIL_EN =
    /missing\s+init\s+data|invalid\s+or\s+expired\s+init\s+data|invalid\s+or\s+expired\s+launch\s+params/i;

  /**
   * Turn known English API/auth snippets into neutral Russian for inline error slots.
   */
  function humanizeDetail(detail) {
    if (detail == null || detail === '') return '';
    if (typeof detail === 'object') return '';
    var s = String(detail).trim();
    if (!s) return '';
    if (LEGACY_AUTH_DETAIL_EN.test(s)) return 'Что-то пошло не так';
    if (
      /\b(unauthorized|internal server error|bad gateway|gateway timeout|service unavailable|request timeout)\b/i.test(
        s
      )
    ) {
      return 'Что-то пошло не так';
    }
    return s;
  }

  function webappApiUrl(url) {
    return String(url || '').indexOf('/api/webapp') >= 0;
  }

  function showRecoverableOverlay() {
    if (overlayShown) return;
    overlayShown = true;
    var existing = document.getElementById(OVERLAY_ID);
    var el = existing || document.createElement('div');
    el.id = OVERLAY_ID;
    el.className = 'bd-trainer-gate bd-trainer-gate--overlay mini-app-recoverable-err';
    el.setAttribute('role', 'alertdialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-live', 'assertive');
    el.innerHTML =
      '<div class="bd-trainer-gate__card">' +
      '<div class="bd-trainer-gate__icon" aria-hidden="true">⚠️</div>' +
      '<h2 class="bd-trainer-gate__title">Что-то пошло не так</h2>' +
      '<p class="bd-trainer-gate__hint">Нажмите «Обновить» или закройте мини-приложение и откройте снова из бота.</p>' +
      '<div class="bd-trainer-gate__actions">' +
      '<button type="button" class="bd-btn bd-btn--primary" data-miniapp-recover="reload">Обновить</button>' +
      '</div>' +
      '</div>';
    if (!existing && document.body) document.body.appendChild(el);
    el.style.display = 'flex';
    var btn = el.querySelector('[data-miniapp-recover="reload"]');
    if (btn) {
      btn.onclick = function () {
        try {
          global.location.reload();
        } catch (e) {
          global.location.href = global.location.href.split('#')[0];
        }
      };
    }
    try {
      var sk = document.getElementById('skeleton');
      if (sk) sk.style.display = 'none';
    } catch (e2) {}
  }

  function inspectUnauthorized(url, res) {
    if (!res || res.status !== 401 || !webappApiUrl(url)) return;
    var h = '';
    try {
      h = res.headers.get(HDR) || '';
    } catch (e) {
      h = '';
    }
    if (h === '1') {
      showRecoverableOverlay();
      return;
    }
    var ct = (res.headers.get('content-type') || '').toLowerCase();
    if (ct.indexOf('application/json') === -1) return;
    res
      .clone()
      .json()
      .then(function (body) {
        var det = body && body.detail;
        var ds = typeof det === 'string' ? det : '';
        if (LEGACY_AUTH_DETAIL_EN.test(ds) || ds === 'Что-то пошло не так') showRecoverableOverlay();
      })
      .catch(function () {});
  }

  function installFetchGuard() {
    if (fetchGuardInstalled) return;
    fetchGuardInstalled = true;
    var orig = global.fetch;
    global.fetch = function (input, init) {
      var url = '';
      try {
        if (typeof input === 'string') url = input;
        else if (input && typeof input.url === 'string') url = input.url;
      } catch (e) {
        url = '';
      }
      return orig.apply(this, arguments).then(function (res) {
        inspectUnauthorized(url, res);
        return res;
      });
    };
  }

  global.MiniAppErrorUi = {
    humanizeDetail: humanizeDetail,
    showRecoverableOverlay: showRecoverableOverlay,
    installFetchGuard: installFetchGuard,
  };

  /**
   * Prefer blur-only phone masking (no live `input` handler).
   * WebKit (Telegram iOS) closes the paste/callout when `value` is rewritten during the gesture.
   * Use maxTouchPoints first — WKWebView may report `pointer: fine` on phones/tablets.
   */
  global.miniAppIsTouchPrimary = function () {
    try {
      if ((global.navigator.maxTouchPoints || 0) > 0) return true;
      var mq = global.matchMedia;
      return !!(mq && mq('(hover: none) and (pointer: coarse)').matches);
    } catch (e) {
      return false;
    }
  };

  /** Strip leading Belarus country dial tokens; UI already shows +375. Only trims left-spaces removed with tokens (no `.trim()` of whole string). */
  global.stripLeadingDialCodeTokensFor375Field = function (str) {
    var t = String(str || '').replace(/^\uFEFF/, '');
    for (var i = 0; i < 8; i++) {
      var prev = t;
      t = t
        .replace(/^\s+/, '')
        .replace(/^\+\s*375/i, '')
        .replace(/^375(?=\d)/i, '')
        .replace(/^80(?=\d)/i, '')
        .replace(/^\+(?=\s*\d)/, '');
      if (t === prev) break;
    }
    return t;
  };

  /** Up to 9 national digits; strips 00… / 375 / 80 from pasted full MSISDN so UI +375 prefix never duplicates. */
  global.extractNational375Digits = function (raw) {
    var d = String(raw || '').replace(/\D/g, '');
    while (d.length >= 2 && d.slice(0, 2) === '00') d = d.slice(2);
    while (d.length > 9 && d.indexOf('375') === 0) d = d.slice(3);
    if (d.indexOf('80') === 0 && d.length >= 9) d = d.slice(2);
    while (d.length > 9 && d.indexOf('375') === 0) d = d.slice(3);
    if (d.length > 9) d = d.slice(0, 9);
    return d;
  };

  /** «XX XXX-XX-XX» for inputs that render +375 outside the field. */
  global.formatNational375MaskedFragment = function (digits) {
    var d = global.extractNational375Digits(digits);
    var f = '';
    if (d.length > 0) f = d.slice(0, 2);
    if (d.length > 2) f += ' ' + d.slice(2, 5);
    if (d.length > 5) f += '-' + d.slice(5, 7);
    if (d.length > 7) f += '-' + d.slice(7, 9);
    return f;
  };

  /** Digits strictly before caret (mask chars excluded) — stable anchor when reformatting. */
  function national375DigitsBeforeCaret(str, caretIndex) {
    var n = 0;
    var lim = Math.min(Math.max(0, caretIndex), str.length);
    for (var i = 0; i < lim; i++) {
      if (/\d/.test(str.charAt(i))) n++;
    }
    return n;
  }

  /** Index after the digitCount-th digit (0 = before any digit); for restoring caret after mask apply. */
  function national375IndexAfterDigitCount(str, digitCount) {
    if (digitCount <= 0) return 0;
    var seen = 0;
    for (var i = 0; i < str.length; i++) {
      if (/\d/.test(str.charAt(i))) {
        seen++;
        if (seen === digitCount) return i + 1;
      }
    }
    return str.length;
  }

  /** «(XX) XXX-XX-XX» — fragment after literal +375 in the UI (operator in parens). */
  global.formatNational375MaskedFragmentParen = function (raw) {
    var d = global.extractNational375Digits(raw);
    var n = d.length;
    if (n === 0) return '';
    if (n === 1) return '(' + d;
    if (n === 2) return '(' + d + ')';
    var out = '(' + d.slice(0, 2) + ') ' + d.slice(2, Math.min(n, 5));
    if (n > 5) out += '-' + d.slice(5, Math.min(n, 7));
    if (n > 7) out += '-' + d.slice(7, 9);
    return out;
  };

  /** Idempotent ``(XX) XXX-XX-XX`` apply; caret by digit index (same as fragment mask). */
  global.applyNational375ParenMaskedToInput = function (el) {
    if (!el) return;
    var raw = String(el.value || '');
    var ss = typeof el.selectionStart === 'number' ? el.selectionStart : raw.length;
    var se = typeof el.selectionEnd === 'number' ? el.selectionEnd : ss;
    var caret = Math.min(ss, se);
    var work = global.stripLeadingDialCodeTokensFor375Field(raw);
    var digitsBefore;
    if (work !== raw) {
      var chop = raw.length - work.length;
      var caret2 = caret - chop;
      if (caret2 < 0) caret2 = 0;
      digitsBefore = national375DigitsBeforeCaret(work, caret2);
    } else {
      digitsBefore = national375DigitsBeforeCaret(work, caret);
    }
    var f = global.formatNational375MaskedFragmentParen(work);
    if (work === f) return;
    el.value = f;
    var newPos = national375IndexAfterDigitCount(f, digitsBefore);
    try {
      el.setSelectionRange(newPos, newPos);
    } catch (errCaret) {}
  };

  /** Paste helper for +(375) fragment with parentheses grouping. */
  function handleNational375ParenPhonePaste(e) {
    var cd = e.clipboardData || global.clipboardData;
    if (!cd || typeof cd.getData !== 'function') return;
    var textRaw = cd.getData('text/plain');
    if (textRaw == null || String(textRaw).trim() === '') return;
    e.preventDefault();
    var el = e.target;
    var cur = String(el.value || '');
    var start = typeof el.selectionStart === 'number' ? el.selectionStart : cur.length;
    var end = typeof el.selectionEnd === 'number' ? el.selectionEnd : start;
    var pasteNationals = global.extractNational375Digits(String(textRaw));
    var merged;
    if (pasteNationals.length >= 9) {
      merged = String(textRaw);
    } else {
      var pasteChunk = global.stripLeadingDialCodeTokensFor375Field(String(textRaw));
      merged = cur.slice(0, start) + pasteChunk + cur.slice(end);
    }
    var masked = global.formatNational375MaskedFragmentParen(merged);
    el.value = masked;
    try {
      var len = masked.length;
      el.setSelectionRange(len, len);
    } catch (errPasteCaret) {}
  }

  /** Same as ``wireNational375PhoneInputMask`` but renders ``(29) XXX-XX-XX`` (after UI +375). */
  global.wireNational375ParenPhoneInputMask = function (el) {
    if (!el || el.tagName !== 'INPUT' || el.dataset.crmNat375ParenMask === '1') return;
    el.dataset.crmNat375ParenMask = '1';
    el.addEventListener('paste', handleNational375ParenPhonePaste, false);
    el.addEventListener('input', function () {
      global.applyNational375ParenMaskedToInput(el);
    });
    el.addEventListener('blur', function () {
      global.applyNational375ParenMaskedToInput(el);
    });
  };

  /** Idempotent mask apply (national fragment). Preserves caret by digit index so mid-field edits stay usable. */
  global.applyNational375MaskedToInput = function (el) {
    if (!el) return;
    var raw = String(el.value || '');
    var ss = typeof el.selectionStart === 'number' ? el.selectionStart : raw.length;
    var se = typeof el.selectionEnd === 'number' ? el.selectionEnd : ss;
    var caret = Math.min(ss, se);
    var work = global.stripLeadingDialCodeTokensFor375Field(raw);
    var digitsBefore;
    if (work !== raw) {
      var chop = raw.length - work.length;
      var caret2 = caret - chop;
      if (caret2 < 0) caret2 = 0;
      digitsBefore = national375DigitsBeforeCaret(work, caret2);
    } else {
      digitsBefore = national375DigitsBeforeCaret(work, caret);
    }
    var f = global.formatNational375MaskedFragment(work);
    if (work === f) return;
    el.value = f;
    var newPos = national375IndexAfterDigitCount(f, digitsBefore);
    try {
      el.setSelectionRange(newPos, newPos);
    } catch (errCaret) {}
  };

  /** Merge clipboard into selection, normalize pasted +375… to national fragment (single-field UX). */
  function handleNational375PhonePaste(e) {
    var cd = e.clipboardData || global.clipboardData;
    if (!cd || typeof cd.getData !== 'function') return;
    var textRaw = cd.getData('text/plain');
    if (textRaw == null || String(textRaw).trim() === '') return;
    e.preventDefault();
    var el = e.target;
    var cur = String(el.value || '');
    var start = typeof el.selectionStart === 'number' ? el.selectionStart : cur.length;
    var end = typeof el.selectionEnd === 'number' ? el.selectionEnd : start;
    var pasteNationals = global.extractNational375Digits(String(textRaw));
    var merged;
    if (pasteNationals.length >= 9) {
      merged = String(textRaw);
    } else {
      var pasteChunk = global.stripLeadingDialCodeTokensFor375Field(String(textRaw));
      merged = cur.slice(0, start) + pasteChunk + cur.slice(end);
    }
    var masked = global.formatNational375MaskedFragment(merged);
    el.value = masked;
    try {
      var len = masked.length;
      el.setSelectionRange(len, len);
    } catch (errPasteCaret) {}
  }

  /**
   * Belarus +375 booking-style fields (national digits in control).
   * Paste: custom handler; input/blur apply mask with caret preserved (assign-without-care breaks taps between digits).
   */
  global.wireNational375PhoneInputMask = function (el) {
    if (!el || el.tagName !== 'INPUT' || el.dataset.crmNat375Mask === '1') return;
    el.dataset.crmNat375Mask = '1';
    el.addEventListener('paste', handleNational375PhonePaste, false);
    el.addEventListener('input', function () {
      global.applyNational375MaskedToInput(el);
    });
    el.addEventListener('blur', function () {
      global.applyNational375MaskedToInput(el);
    });
  };

  installFetchGuard();
})(window);
