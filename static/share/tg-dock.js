/**
 * Плашка «Открыть в Telegram»: в потоке у начала страницы, после прокрутки — пилюля внизу.
 * Заполнитель той же высоты убирает CLS, когда nav уходит в position: fixed.
 */
(function () {
  'use strict';

  var dock = document.querySelector('.b-tgdock');
  if (!dock || document.body.hasAttribute('data-client-shell')) return;

  var host = dock.closest('.b-tgdock-host');
  var spacer = host && host.querySelector('.b-tgdock__spacer');
  var inner = dock.querySelector('.b-tgdock__inner');
  var THRESHOLD = 48;

  // Высота плашки в потоке. Мерить можно только пока она в потоке: плавающая
  // пилюля ниже, и заполнитель по ней дёргал контент на разницу высот.
  var inFlowHeight = 0;

  function sync() {
    var floating = window.scrollY > THRESHOLD;
    if (!dock.classList.contains('is-floating')) inFlowHeight = dock.offsetHeight;
    if (spacer) spacer.style.height = floating ? inFlowHeight + 'px' : '0px';
    dock.classList.toggle('is-floating', floating);
  }

  window.addEventListener('scroll', sync, { passive: true });
  window.addEventListener('resize', sync);
  if (typeof ResizeObserver === 'function' && inner) {
    new ResizeObserver(sync).observe(inner);
  }
  sync();
})();
