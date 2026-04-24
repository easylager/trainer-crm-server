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
 * - https://t.me/… — WebApp.openTelegramLink / openLink (works in web + native).
 * - tg://user?id=… — do NOT use WebApp APIs: they log "Url protocol is not supported" and burn the
 *   user-gesture, so the browser then blocks the fallback. Use sync location.assign on native; on
 *   platform=web, tg:// is unsupported — prefer t.me (API can fill username via getChat) or showAlert.
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
