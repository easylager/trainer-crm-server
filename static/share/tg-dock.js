/**
 * Плашка «Открыть в Telegram»: в потоке у начала страницы, после прокрутки — пилюля внизу.
 * Внутри Mini App (data-client-shell) не подключается.
 */
(function () {
  'use strict';

  var dock = document.querySelector('.b-tgdock');
  if (!dock || document.body.hasAttribute('data-client-shell')) return;

  var THRESHOLD = 48;

  function sync() {
    dock.classList.toggle('is-floating', window.scrollY > THRESHOLD);
  }

  window.addEventListener('scroll', sync, { passive: true });
  sync();
})();
