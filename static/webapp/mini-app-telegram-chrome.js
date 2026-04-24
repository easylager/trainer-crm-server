/**
 * Telegram Mini App: keep native header as close (X), not BackButton.
 * Calling WebApp.BackButton.show() replaces the X with a system back arrow — avoid that globally.
 */
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) return;
  if (typeof tg.ready === 'function') tg.ready();
  if (tg.BackButton) {
    tg.BackButton.hide();
    try {
      tg.BackButton.onClick(function () {});
    } catch (e) { /* noop */ }
  }
})();

/**
 * Open a private Telegram chat from Mini App.
 * - Plain <a href="tg://..."> is unreliable in WebView; use WebApp APIs first.
 * - `openLink` for tg:// may hand off to the system browser (broken) — avoid as primary for tg://.
 * - On some iOS builds `openTelegramLink` is flaky; we add <a>.click() + location fallbacks.
 */
window.openTelegramChatFromMiniApp = function (opts) {
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
  if (w) {
    if (typeof w.openTelegramLink === 'function') {
      try {
        w.openTelegramLink(url);
        return true;
      } catch (e) { /* continue */ }
    }
    // https://t.me/... — extra path for mobile clients where openTelegramLink is a no-op
    if (url.indexOf('https://t.me/') === 0 && typeof w.openLink === 'function') {
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
    // tg:// — last resort inside WebApp: some Android builds route in-app via openLink
    if (url.indexOf('tg://') === 0 && typeof w.openLink === 'function') {
      try {
        w.openLink(url, { try_instant_view: false });
        return true;
      } catch (e4) { /* continue */ }
    }
  }

  // Programmatic anchor (helps on some iOS WebViews)
  try {
    var a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener noreferrer';
    a.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;pointer-events:auto;';
    // tg:// must stay in the same webview context
    a.target = url.indexOf('tg://') === 0 ? '_self' : '_blank';
    (document.body || document.documentElement).appendChild(a);
    a.click();
    setTimeout(function () {
      try {
        if (a && a.parentNode) a.parentNode.removeChild(a);
      } catch (x) { /* noop */ }
    }, 0);
  } catch (e5) { /* continue */ }
  try {
    window.location.href = url;
  } catch (e6) { /* noop */ }
  return true;
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
