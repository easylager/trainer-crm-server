/**
 * TASK-256: подключает клиентский Mini App shell к серверной /p/… только при initData.
 * В обычном браузере скрипт сразу выходит — без вкладок, темы и лишних отступов.
 */
(function (global) {
  'use strict';

  function isPlacePage() {
    var p = global.location && global.location.pathname || '';
    return /^\/p\/[^/]+\/[^/]+/.test(p);
  }

  function initData() {
    var rt = global.MiniAppRuntime;
    if (rt && typeof rt.getCredential === 'function') {
      var c = rt.getCredential();
      if (c) return String(c);
    }
    var tg = global.Telegram && global.Telegram.WebApp;
    return tg && tg.initData ? String(tg.initData) : '';
  }

  function webappV() {
    var tag = global.document.currentScript;
    return (tag && tag.getAttribute('data-webapp-v')) || '0';
  }

  function loadStyle(href) {
    var link = global.document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    global.document.head.appendChild(link);
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = global.document.createElement('script');
      s.src = src;
      s.onload = function () {
        resolve();
      };
      s.onerror = function () {
        reject(new Error('script ' + src));
      };
      global.document.head.appendChild(s);
    });
  }

  function wireBackButton() {
    var tg = global.Telegram && global.Telegram.WebApp;
    if (!tg || !tg.BackButton) return;
    try {
      tg.BackButton.show();
      tg.BackButton.onClick(function () {
        if (global.history.length > 1) {
          global.history.back();
          return;
        }
        if (global.ClientShell && typeof global.ClientShell.navigate === 'function') {
          global.ClientShell.navigate('ice');
          return;
        }
        global.location.href = '/webapp/ice';
      });
    } catch (e) { /* */ }
  }

  function markHeroForTransition() {
    if (!('onpagereveal' in global)) return;
    global.addEventListener('pagereveal', function () {
      var img = global.document.querySelector('.b-hero__img');
      if (img) img.setAttribute('data-vt-hero', '1');
    });
  }

  function activateShell() {
    var body = global.document.body;
    if (!body) return;
    body.setAttribute('data-client-shell', 'tabs');
    body.classList.add('ar-pilot', 'ar-pilot--place');
    if (global.ClientShell && typeof global.ClientShell.init === 'function') {
      global.ClientShell.init({ mode: 'tabs' });
      if (typeof global.ClientShell.setForcedTab === 'function') {
        global.ClientShell.setForcedTab('catalog');
      }
    }
    wireBackButton();
    markHeroForTransition();
  }

  function boot() {
    if (!isPlacePage()) return;
    if (!initData()) return;

    var v = webappV();
    var w = '/webapp/';
    var shareV =
      (global.document.currentScript && global.document.currentScript.getAttribute('data-share-v')) || '0';

    loadStyle(w + 'theme.css?v=' + encodeURIComponent(v));
    loadStyle(w + 'mini-app-client-theme.css?v=' + encodeURIComponent(v));
    loadStyle(w + 'mini-app-components.css?v=' + encodeURIComponent(v));
    loadStyle(w + 'mini-app-client-shell.css?v=' + encodeURIComponent(v));
    loadStyle('/static/share/place-tg-shell.css?v=' + encodeURIComponent(shareV));

    var chain = [
      'https://telegram.org/js/telegram-web-app.js',
      w + 'mini-app-full-height.js?v=' + v,
      w + 'client-mini-app-theme.js?v=' + v,
      w + 'mini-app-telegram-chrome.js?v=' + v,
      w + 'mini-app-empty-state.js?v=' + v,
      w + 'mini-app-more-icons.js?v=' + v,
      w + 'mini-app-client-shell.js?v=' + v,
    ];

    var i = 0;
    function next() {
      if (i >= chain.length) {
        activateShell();
        return;
      }
      var src = chain[i];
      i += 1;
      loadScript(src).then(next).catch(function () {
        /* SDK с CDN мог не загрузиться — продолжаем с заглушкой initData в тестах. */
        next();
      });
    }
    next();
  }

  if (global.document.readyState === 'loading') {
    global.document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(window);
