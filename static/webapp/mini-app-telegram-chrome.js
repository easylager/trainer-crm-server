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
 * Open a private Telegram chat from Mini App. Plain <a href="tg://..."> often does nothing in WebView;
 * prefer https://t.me/username via openLink; fallback tg://user?id= via openTelegramLink/openLink.
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
    // Prefer openTelegramLink for both https://t.me/... and tg:// (opens inside Telegram; closes Mini App).
    try {
      if (typeof w.openTelegramLink === 'function') {
        w.openTelegramLink(url);
        return true;
      }
    } catch (e) { /* older clients */ }
    try {
      if (typeof w.openLink === 'function') {
        w.openLink(url);
        return true;
      }
    } catch (e2) { /* proceed */ }
  }
  try {
    window.location.href = url;
  } catch (e3) { /* noop */ }
  return true;
};
